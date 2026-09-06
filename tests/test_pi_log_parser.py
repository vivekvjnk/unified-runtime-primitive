"""Unit tests for the Pi Agent JSONL raw log parser."""

import json
import tempfile
from pathlib import Path
from urp.web.pi_log_parser import parse_pi_session_log


def test_parse_pi_session_log():
    with tempfile.NamedTemporaryFile("w+", suffix=".jsonl", delete=False) as f:
        temp_path = f.name
        # 1. Model change
        f.write(json.dumps({"type": "model_change", "provider": "google-vertex", "modelId": "gemini-3.8-flash"}) + "\n")
        # 2. Thinking level
        f.write(json.dumps({"type": "thinking_level_change", "thinkingLevel": "medium"}) + "\n")
        # 3. User message
        f.write(json.dumps({
            "type": "message",
            "id": "msg-u-1",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Analyze the codebase"}]
            }
        }) + "\n")
        # 4. Assistant message with thinking & tool call
        f.write(json.dumps({
            "type": "message",
            "id": "msg-a-1",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Let's first list files in urp/core."},
                    {"type": "toolCall", "id": "call-1", "name": "bash", "arguments": {"command": "ls urp/core"}},
                    {"type": "text", "text": "I will examine urp/core now."}
                ],
                "model": "gemini-3.8-flash",
                "provider": "google-vertex",
                "usage": {
                    "input": 500,
                    "output": 60,
                    "reasoning": 40,
                    "totalTokens": 560,
                    "cost": {"total": 0.0002}
                },
                "stopReason": "toolUse"
            }
        }) + "\n")
        # 5. Tool result
        f.write(json.dumps({
            "type": "message",
            "message": {
                "role": "toolResult",
                "toolCallId": "call-1",
                "content": [{"type": "text", "text": "host.py\nabstract_urp.py\n"}]
            }
        }) + "\n")

    try:
        parsed = parse_pi_session_log(temp_path)
        assert parsed["exists"] is True
        stats = parsed["stats"]
        assert stats["model"] == "gemini-3.8-flash"
        assert stats["total_input_tokens"] == 500
        assert stats["total_output_tokens"] == 60
        assert stats["total_reasoning_tokens"] == 40
        assert stats["total_tokens"] == 560

        turns = parsed["turns"]
        assert len(turns) == 1
        turn = turns[0]
        assert turn["user_text"] == "Analyze the codebase"

        resp = turn["model_responses"][0]
        assert resp["thinking"] == ["Let's first list files in urp/core."]
        assert resp["text"] == "I will examine urp/core now."
        assert len(resp["tool_calls"]) == 1
        tool = resp["tool_calls"][0]
        assert tool["name"] == "bash"
        assert "host.py" in tool["result"]
    finally:
        Path(temp_path).unlink(missing_ok=True)
