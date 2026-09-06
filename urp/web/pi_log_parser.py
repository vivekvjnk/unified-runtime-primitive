"""Parser for Pi Agent JSONL session logs.

Extracts structured LLM interactions (thinking blocks, user prompts, assistant text,
tool executions, delegations, and usage metrics) from raw Pi session files.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("urp.web.pi_log_parser")


def parse_pi_session_log(file_path: str | Path, max_turns: int = 100) -> Dict[str, Any]:
    """Parses a Pi JSONL session log file into structured turns and aggregate metrics."""
    path = Path(file_path).resolve()
    if not path.is_file():
        return {
            "session_file": str(path),
            "exists": False,
            "turns": [],
            "stats": {"total_input_tokens": 0, "total_output_tokens": 0, "total_reasoning_tokens": 0, "turns_count": 0},
        }

    records: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.trim() if hasattr(line, "trim") else line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        logger.error(f"Failed to read Pi session file {path}: {e}")
        return {
            "session_file": str(path),
            "exists": False,
            "error": str(e),
            "turns": [],
            "stats": {},
        }

    # Aggregate session-level stats
    stats = {
        "model": None,
        "provider": None,
        "thinking_level": None,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_reasoning_tokens": 0,
        "total_tokens": 0,
        "total_cost": 0.0,
        "turns_count": 0,
    }

    # Pre-index tool results by toolCallId
    tool_results: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        if rec.get("type") == "model_change":
            stats["model"] = rec.get("modelId") or stats["model"]
            stats["provider"] = rec.get("provider") or stats["provider"]
        elif rec.get("type") == "thinking_level_change":
            stats["thinking_level"] = rec.get("thinkingLevel") or stats["thinking_level"]
        elif rec.get("type") == "message":
            msg = rec.get("message", {})
            if msg.get("role") == "toolResult":
                call_id = msg.get("toolCallId")
                if call_id:
                    tool_results[call_id] = msg

    # Group into structured conversational turns
    turns: List[Dict[str, Any]] = []
    current_turn: Optional[Dict[str, Any]] = None

    for rec in records:
        rtype = rec.get("type")

        if rtype == "message":
            msg = rec.get("message", {})
            role = msg.get("role")

            if role == "user":
                # Start a new turn
                if current_turn:
                    turns.append(current_turn)

                text_content = ""
                content = msg.get("content", [])
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_content += part.get("text", "")
                elif isinstance(content, str):
                    text_content = content

                current_turn = {
                    "id": rec.get("id"),
                    "timestamp": rec.get("timestamp") or msg.get("timestamp"),
                    "user_text": text_content,
                    "model_responses": [],
                }

            elif role == "assistant":
                if not current_turn:
                    current_turn = {
                        "id": rec.get("id"),
                        "timestamp": rec.get("timestamp") or msg.get("timestamp"),
                        "user_text": "",
                        "model_responses": [],
                    }

                # Extract model info & tokens
                model = msg.get("model") or stats["model"]
                provider = msg.get("provider") or stats["provider"]
                usage = msg.get("usage", {}) or {}

                in_tok = usage.get("input", 0)
                out_tok = usage.get("output", 0)
                reason_tok = usage.get("reasoning", 0)
                total_tok = usage.get("totalTokens", 0) or (in_tok + out_tok)
                cost = usage.get("cost", {}).get("total", 0.0) if isinstance(usage.get("cost"), dict) else 0.0

                stats["total_input_tokens"] += in_tok
                stats["total_output_tokens"] += out_tok
                stats["total_reasoning_tokens"] += reason_tok
                stats["total_tokens"] += total_tok
                stats["total_cost"] += cost

                if model:
                    stats["model"] = model
                if provider:
                    stats["provider"] = provider

                # Parse parts: thinking, toolCalls, text
                thinking_blocks: List[str] = []
                text_blocks: List[str] = []
                tool_calls: List[Dict[str, Any]] = []

                content = msg.get("content", [])
                if isinstance(content, list):
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        ptype = part.get("type")
                        if ptype == "thinking":
                            thinking_blocks.append(part.get("thinking", ""))
                        elif ptype == "text":
                            t = part.get("text", "")
                            if t.strip():
                                text_blocks.append(t)
                        elif ptype == "toolCall":
                            call_id = part.get("id")
                            tool_name = part.get("name")
                            args = part.get("arguments", {})

                            # Match with result if available
                            matched_result = tool_results.get(call_id, {})
                            result_content = matched_result.get("content", "")
                            if isinstance(result_content, list):
                                res_texts = [p.get("text", "") for p in result_content if isinstance(p, dict) and p.get("type") == "text"]
                                result_text = "\n".join(res_texts)
                            else:
                                result_text = str(result_content)

                            tool_calls.append({
                                "id": call_id,
                                "name": tool_name,
                                "arguments": args,
                                "result": result_text,
                                "is_error": matched_result.get("isError", False),
                                "is_subtask": (tool_name == "delegate"),
                            })

                response_item = {
                    "id": rec.get("id"),
                    "timestamp": rec.get("timestamp") or msg.get("timestamp"),
                    "model": model,
                    "provider": provider,
                    "stop_reason": msg.get("stopReason"),
                    "usage": {
                        "input": in_tok,
                        "output": out_tok,
                        "reasoning": reason_tok,
                        "total": total_tok,
                        "cost": cost,
                    },
                    "thinking": thinking_blocks,
                    "tool_calls": tool_calls,
                    "text": "\n\n".join(text_blocks),
                    "raw_message": msg,
                }
                current_turn["model_responses"].append(response_item)

    if current_turn:
        turns.append(current_turn)

    stats["turns_count"] = len(turns)
    if len(turns) > max_turns:
        turns = turns[-max_turns:]

    return {
        "session_file": str(path),
        "exists": True,
        "stats": stats,
        "turns": turns,
    }
