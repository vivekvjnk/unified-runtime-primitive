import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

def list_workspace_conversations(workspace_path: str) -> List[Dict[str, Any]]:
    """Lists saved conversation sessions in the workspace."""
    conv_file = os.path.join(os.path.abspath(workspace_path), ".conversation", "conversation_map.json")
    if os.path.exists(conv_file):
        with open(conv_file, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return []
    return []

def load_conversation_history(workspace_path: str, conversation_id: str) -> List[Dict[str, str]]:
    """Reads reconstructed conversation events from the workspace."""
    base_dir = os.path.join(os.path.abspath(workspace_path), ".conversation")
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
