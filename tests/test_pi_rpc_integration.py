import asyncio
import os
from pathlib import Path
import pytest

from urp.harnesses.pi import (
    PiRpcClient,
    PiRpcError,
    PiRpcConnectionError,
    PiRpcTimeoutError,
    PiRpcProcessTerminatedError,
    ExtensionUiRequest,
    ExtensionUiResponse,
)

FAKE_PI_SCRIPT = str(Path(__file__).resolve().parent / "fixtures" / "fake_pi_rpc.py")


@pytest.mark.asyncio
async def test_pi_rpc_lifecycle_and_state(tmp_path):
    """Test 1: Spawns live pi --mode rpc subprocess, queries state, and closes cleanly."""
    client = PiRpcClient(workspace_dir=tmp_path, no_session=True, executable_path=FAKE_PI_SCRIPT)
    assert not client.is_running

    await client.start()
    assert client.is_running

    resp = await client.get_state()
    assert resp.success is True
    assert resp.command == "get_state"
    assert "sessionId" in resp.data
    assert "autoCompactionEnabled" in resp.data

    await client.close()
    assert not client.is_running


@pytest.mark.asyncio
async def test_pi_rpc_direct_bash_execution(tmp_path):
    """Test 2: Direct bash execution with streaming update checks."""
    client = PiRpcClient(workspace_dir=tmp_path, no_session=True, executable_path=FAKE_PI_SCRIPT)
    await client.start()

    bash_updates = []
    
    def handle_event(evt):
        if evt.type == "bash_execution_update":
            bash_updates.append(evt)

    client.on_any_event(handle_event)

    resp = await client.bash(
        command="echo 'hello vhl' && sleep 0.05 && echo 'vhl bridge success'",
        req_id="req-bash-123"
    )

    assert resp.success is True
    assert resp.id == "req-bash-123"
    assert resp.data["exitCode"] == 0
    assert "hello vhl" in resp.data["output"]
    assert "vhl bridge success" in resp.data["output"]

    await client.close()


@pytest.mark.asyncio
async def test_pi_rpc_prompt_event_streaming(tmp_path):
    """Test 3: Prompt sending and streamed events ingestion."""
    client = PiRpcClient(workspace_dir=tmp_path, no_session=True, executable_path=FAKE_PI_SCRIPT)
    await client.start()

    captured_events = []
    settled_event = asyncio.Event()

    def handle_event(evt):
        captured_events.append(evt)
        if evt.type in ("agent_settled", "agent_end"):
            settled_event.set()

    client.on_any_event(handle_event)

    prompt_resp = await client.send_prompt("Reply with exact text 'PONG_VHL_TEST' and nothing else.")
    assert prompt_resp.success is True

    try:
        await asyncio.wait_for(settled_event.wait(), timeout=15.0)
    except asyncio.TimeoutError:
        pass

    event_types = [evt.type for evt in captured_events]
    assert "agent_start" in event_types or "message_start" in event_types or "message_update" in event_types or "turn_start" in event_types

    last_text_resp = await client.get_last_assistant_text()
    assert last_text_resp.success is True
    assert "PONG_VHL_TEST" in (last_text_resp.data.get("text") or "")

    await client.close()


@pytest.mark.asyncio
async def test_pi_rpc_steer_and_abort(tmp_path):
    """Test 4: Abort and steer commands."""
    client = PiRpcClient(workspace_dir=tmp_path, no_session=True, executable_path=FAKE_PI_SCRIPT)
    await client.start()

    abort_resp = await client.abort()
    assert abort_resp.success is True

    steer_mode_resp = await client.send_command({"type": "set_steering_mode", "mode": "one-at-a-time"})
    assert steer_mode_resp.success is True

    await client.close()


@pytest.mark.asyncio
async def test_pi_rpc_extension_ui_subprotocol(tmp_path):
    """Test 5: Extension UI sub-protocol handling."""
    client = PiRpcClient(workspace_dir=tmp_path, no_session=True, executable_path=FAKE_PI_SCRIPT)

    handled_requests = []

    async def custom_ui_handler(req: ExtensionUiRequest) -> ExtensionUiResponse:
        handled_requests.append(req)
        if req.method == "confirm":
            return ExtensionUiResponse(id=req.id, confirmed=True)
        elif req.method == "select":
            return ExtensionUiResponse(id=req.id, value=req.options[0] if req.options else None)
        return ExtensionUiResponse(id=req.id, cancelled=True)

    client.register_ui_handler(custom_ui_handler)
    await client.start()

    sample_ui_req = {
        "type": "extension_ui_request",
        "id": "ui-uuid-1",
        "method": "confirm",
        "title": "Test Confirmation",
        "message": "Do you accept?"
    }

    await client._handle_incoming_line(sample_ui_req)

    assert len(handled_requests) == 1
    assert handled_requests[0].id == "ui-uuid-1"
    assert handled_requests[0].method == "confirm"

    await client.close()


@pytest.mark.asyncio
async def test_pi_rpc_error_handling_and_crash_recovery(tmp_path):
    """Test 6: Process termination and error handling."""
    client = PiRpcClient(workspace_dir=tmp_path, no_session=True, executable_path=FAKE_PI_SCRIPT)
    await client.start()

    if client._process:
        client._process.terminate()
        await client._process.wait()

    with pytest.raises((PiRpcProcessTerminatedError, PiRpcConnectionError)):
        await client.get_state()

    await client.close()


@pytest.mark.asyncio
async def test_pi_rpc_model_switch_and_compaction(tmp_path):
    """Test 7: Model discovery, session stats, and compaction operations."""
    client = PiRpcClient(workspace_dir=tmp_path, no_session=True, executable_path=FAKE_PI_SCRIPT)
    await client.start()

    models_resp = await client.get_available_models()
    assert models_resp.success is True
    assert "models" in models_resp.data

    stats_resp = await client.get_session_stats()
    assert stats_resp.success is True
    assert "sessionId" in stats_resp.data

    compact_resp = await client.compact()
    assert compact_resp.command == "compact"
    assert compact_resp.success is False
    assert "Nothing to compact" in (compact_resp.error or "")

    await client.close()
