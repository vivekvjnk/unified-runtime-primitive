#!/usr/bin/env python3
"""
Fake Pi RPC server for fast, deterministic unit & integration testing.
Simulates pi --mode rpc over stdio JSONL without making external LLM calls.
"""
import sys
import json
import time

def main():
    skill_commands = []
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--skill" and i + 1 < len(args):
            skill_dir = args[i + 1]
            skill_commands.append({
                "name": "skill:placement-rules",
                "description": "PCB component placement rules",
                "source": "skill",
                "path": skill_dir,
            })

    last_assistant_text = "Mock response text: VHL_PI_URP_TEST_OK"

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            cmd = json.loads(line)
        except json.JSONDecodeError:
            continue

        cmd_type = cmd.get("type")
        req_id = cmd.get("id")

        if cmd_type == "get_state":
            resp = {
                "id": req_id,
                "type": "response",
                "command": "get_state",
                "success": True,
                "data": {
                    "model": {"id": "mock-model", "name": "Mock Model"},
                    "sessionId": "mock-session-id",
                    "autoCompactionEnabled": True,
                    "messageCount": 0,
                    "pendingMessageCount": 0,
                }
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        elif cmd_type == "get_commands":
            resp = {
                "id": req_id,
                "type": "response",
                "command": "get_commands",
                "success": True,
                "data": {"commands": skill_commands}
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        elif cmd_type == "get_available_models":
            resp = {
                "id": req_id,
                "type": "response",
                "command": "get_available_models",
                "success": True,
                "data": {"models": [{"id": "mock-model", "name": "Mock Model"}]}
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        elif cmd_type == "get_session_stats":
            resp = {
                "id": req_id,
                "type": "response",
                "command": "get_session_stats",
                "success": True,
                "data": {"sessionId": "mock-session-id", "tokens": {"total": 100}}
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        elif cmd_type == "get_last_assistant_text":
            resp = {
                "id": req_id,
                "type": "response",
                "command": "get_last_assistant_text",
                "success": True,
                "data": {"text": last_assistant_text}
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        elif cmd_type == "compact":
            resp = {
                "id": req_id,
                "type": "response",
                "command": "compact",
                "success": False,
                "error": "Nothing to compact (session too small)"
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        elif cmd_type == "bash":
            command = cmd.get("command", "")
            update_evt = {
                "type": "bash_execution_update",
                "id": req_id,
                "delta": "hello vhl\n"
            }
            sys.stdout.write(json.dumps(update_evt) + "\n")
            sys.stdout.flush()

            out_text = "hello vhl\nvhl bridge success" if "echo" in command else "ok"
            resp = {
                "id": req_id,
                "type": "response",
                "command": "bash",
                "success": True,
                "data": {"output": out_text, "exitCode": 0, "cancelled": False, "truncated": False}
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        elif cmd_type == "prompt":
            msg_text = cmd.get("message", "")

            if "PONG_VHL_TEST" in msg_text:
                last_assistant_text = "PONG_VHL_TEST"
            elif "VHL_PI_URP_TEST_OK" in msg_text:
                last_assistant_text = "VHL_PI_URP_TEST_OK"
            else:
                last_assistant_text = f"Mock layout placement result for: {msg_text}"

            resp = {
                "id": req_id,
                "type": "response",
                "command": "prompt",
                "success": True
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

            if "SLOW_PROMPT" in msg_text or "exhaustive" in msg_text.lower():
                events = [
                    {"type": "agent_start"},
                    {"type": "turn_start"},
                ]
            elif "telemetry_vhl_test" in msg_text:
                events = [
                    {"type": "agent_start"},
                    {"type": "turn_start"},
                    {"type": "tool_execution_start", "toolName": "bash", "args": {"command": "echo telemetry_vhl_test"}},
                    {"type": "tool_execution_end", "toolName": "bash", "result": "telemetry_vhl_test\n"},
                    {"type": "turn_end"},
                    {"type": "agent_end"},
                    {"type": "agent_settled"},
                ]
            else:
                events = [
                    {"type": "agent_start"},
                    {"type": "turn_start"},
                    {"type": "message_start", "message": {"role": "assistant"}},
                    {
                        "type": "message_update",
                        "assistantMessageEvent": {
                            "type": "text_delta",
                            "contentIndex": 0,
                            "delta": last_assistant_text
                        }
                    },
                    {"type": "message_end", "message": {"role": "assistant"}},
                    {"type": "turn_end"},
                    {"type": "agent_end"},
                    {"type": "agent_settled"},
                ]

            for evt in events:
                sys.stdout.write(json.dumps(evt) + "\n")
                sys.stdout.flush()

        elif cmd_type in ("steer", "follow_up", "abort", "set_steering_mode", "set_model", "new_session"):
            resp = {
                "id": req_id,
                "type": "response",
                "command": cmd_type,
                "success": True
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        else:
            resp = {
                "id": req_id,
                "type": "response",
                "command": str(cmd_type),
                "success": True
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
