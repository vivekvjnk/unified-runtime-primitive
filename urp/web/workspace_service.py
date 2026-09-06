import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

def list_workspace_conversations(workspace_path: str, agent_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists saved conversation sessions in the workspace from .sessions and .conversation."""
    abs_workspace = os.path.abspath(workspace_path)
    results = []

    # 1. Scan Pi JSONL session files under .sessions/<agent_name> or .sessions/
    session_dirs = []
    if agent_name:
        session_dirs.append(os.path.join(abs_workspace, ".sessions", agent_name))
    session_dirs.append(os.path.join(abs_workspace, ".sessions"))

    seen_ids = set()
    for sdir in session_dirs:
        if os.path.isdir(sdir):
            for root, _, files in os.walk(sdir):
                for f in files:
                    if f.endswith(".jsonl"):
                        sid = Path(f).stem
                        if sid not in seen_ids:
                            seen_ids.add(sid)
                            results.append({
                                "id": sid,
                                "name": f"Session ({Path(root).name}): {sid[:18]}...",
                                "path": os.path.join(root, f),
                                "source": "pi",
                            })

    # 2. Check OpenHands conversation_map.json
    conv_file = os.path.join(abs_workspace, ".conversation", "conversation_map.json")
    if os.path.exists(conv_file):
        with open(conv_file, "r", encoding="utf-8") as f:
            try:
                for item in json.load(f):
                    if item.get("id") not in seen_ids:
                        seen_ids.add(item.get("id"))
                        results.append(item)
            except Exception:
                pass

    return results

def load_conversation_history(workspace_path: str, conversation_id: str, agent_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Reads reconstructed conversation turns and events from the workspace.
    Supports:
    1. Pi session JSONL files under <workspace_path>/.sessions/<agent_name>/*.jsonl
    2. OpenHands SDK JSON event files under <workspace_path>/.conversation/<conversation_id>/events/
    """
    abs_workspace = os.path.abspath(workspace_path)

    # 1. Check for Pi session JSONL files in .sessions/<agent_name> or .sessions/
    from .pi_log_parser import parse_pi_session_log

    session_dirs_to_check = []
    if agent_name:
        session_dirs_to_check.append(os.path.join(abs_workspace, ".sessions", agent_name))
    session_dirs_to_check.append(os.path.join(abs_workspace, ".sessions"))

    for sdir in session_dirs_to_check:
        if os.path.isdir(sdir):
            # Look for matching jsonl files (by conversation_id or newest)
            jsonl_files = sorted(
                [os.path.join(root, f) for root, _, files in os.walk(sdir) for f in files if f.endswith(".jsonl")],
                key=os.path.getmtime,
                reverse=True,
            )
            for jfile in jsonl_files:
                if conversation_id in jfile or not conversation_id or conversation_id == "latest":
                    parsed = parse_pi_session_log(jfile)
                    if parsed.get("turns"):
                        history = []
                        for turn in parsed["turns"]:
                            if turn.get("user_text"):
                                history.append({"role": "user", "text": turn["user_text"]})
                            for resp in turn.get("model_responses", []):
                                if resp.get("text"):
                                    history.append({
                                        "role": "agent",
                                        "text": resp["text"],
                                        "thinking": resp.get("thinking", []),
                                        "tool_calls": resp.get("tool_calls", []),
                                    })
                        return history

    # 2. Check for OpenHands SDK style events under .conversation/
    base_dir = os.path.join(abs_workspace, ".conversation")
    events_dir = os.path.join(base_dir, conversation_id, "events")

    if not os.path.exists(events_dir):
        normalized_id = conversation_id.replace("-", "")
        events_dir = os.path.join(base_dir, normalized_id, "events")

    if not os.path.exists(events_dir):
        return []

    history = []
    try:
        event_files = sorted([f for f in os.listdir(events_dir) if f.endswith(".json")])
    except Exception:
        return []

    for filename in event_files:
        try:
            with open(os.path.join(events_dir, filename), "r", encoding="utf-8") as f:
                event = json.load(f)

                if event.get("kind") == "MessageEvent":
                    role = event.get("source", "user")
                    content = event.get("content", [])
                    if not content and "llm_message" in event:
                        content = event.get("llm_message", {}).get("content", [])

                    text_str = ""
                    if content:
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                text_str += item.get("text", "")
                            elif isinstance(item, str):
                                text_str += item
                    elif "text" in event:
                        text_str = event.get("text", "")

                    if text_str:
                        history.append({"role": role, "text": text_str})

                elif event.get("kind") in ("CmdRunEvent", "ObservationEvent") and event.get("tool_name") == "finish":
                    params = event.get("tool_params") or event.get("arguments") or event.get("observation") or {}
                    msg = params.get("message") or ""
                    if msg:
                        history.append({"role": "agent", "text": msg})
        except Exception:
            pass

    return history

def save_workspace_conversation(workspace_path: str, conversation_id: str, name: str) -> Dict[str, Any]:
    """Saves or updates a conversation entry in conversation_map.json."""
    conv_dir = os.path.join(os.path.abspath(workspace_path), ".conversation")
    os.makedirs(conv_dir, exist_ok=True)
    conv_file = os.path.join(conv_dir, "conversation_map.json")

    conversations = []
    if os.path.exists(conv_file):
        try:
            with open(conv_file, "r", encoding="utf-8") as f:
                conversations = json.load(f)
        except Exception:
            conversations = []

    updated = False
    for conv in conversations:
        if conv["id"] == conversation_id:
            conv["name"] = name
            updated = True
            break

    if not updated:
        conversations.append({"id": conversation_id, "name": name})

    with open(conv_file, "w", encoding="utf-8") as f:
        json.dump(conversations, f, indent=2)

    return {"status": "saved", "id": conversation_id, "name": name}

def browse_filesystem(path: str = ".") -> Dict[str, Any]:
    """Browses the filesystem for the directory picker modal."""
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        return {"error": "Path does not exist"}

    items = [{"name": "..", "path": os.path.dirname(abs_path), "is_dir": True}]
    with os.scandir(abs_path) as it:
        for entry in it:
            if entry.is_dir() and not entry.name.startswith("."):
                items.append({"name": entry.name, "path": entry.path, "is_dir": True})

    return {
        "current_path": abs_path,
        "items": sorted(items, key=lambda x: x["name"]),
    }
