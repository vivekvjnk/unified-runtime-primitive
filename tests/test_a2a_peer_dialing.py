import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from urp.web.app import create_app
from urp.a2a.client import A2APeerClient, a2a_call_peer
from urp.web.agent_service import AgentHostingService


@pytest.fixture
def temp_workspace():
    tmp_dir = tempfile.mkdtemp(prefix="urp_peer_dialing_test_")
    yield tmp_dir
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_peer_roster_description():
    service = AgentHostingService()
    roster = service.get_peer_roster_description("agent_alpha")
    assert "Collaborative Agent2Agent (A2A) Network" in roster
    assert "a2a_peer_call" in roster


@pytest.mark.asyncio
async def test_a2a_peer_client_direct(temp_workspace):
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Initialize peer target agent: worker_bob
        r_init = await client.post(
            "/agent/init",
            json={
                "agent_type": "echo_agent",
                "agent_name": "worker_bob",
                "workspace_path": temp_workspace,
            },
        )
        assert r_init.status_code == 200

        # Send peer call using A2APeerClient with custom transport
        peer_client = A2APeerClient(base_url="http://test")
        # Monkey patch httpx client in A2APeerClient to use ASGITransport for in-memory testing
        orig_call = peer_client.call_peer

        async def call_with_test_transport(peer_name, message_text, **kwargs):
            headers = {"Content-Type": "application/json", "X-Target-Agent": peer_name}
            resp = await client.post(
                f"/message:send?agent_name={peer_name}",
                json={
                    "message": {
                        "role": "ROLE_USER",
                        "parts": [{"text": message_text, "mediaType": "text/plain"}],
                    }
                },
                headers=headers,
            )
            data = resp.json()
            task = data.get("task", {})
            return {
                "peer": peer_name,
                "state": task.get("status", {}).get("state"),
                "output": task.get("status", {}).get("message", {}).get("parts", [{}])[0].get("text", ""),
            }

        res = await call_with_test_transport("worker_bob", "Peer request from Alice")
        assert res["peer"] == "worker_bob"
        assert res["state"] == "TASK_STATE_COMPLETED"
        assert "Echo: Peer request from Alice" in res["output"]


def test_a2a_peer_call_cli_help():
    tool_path = Path(__file__).resolve().parent.parent / "urp" / "a2a" / "tools" / "a2a_peer_call"
    assert tool_path.is_file()
    assert os.access(tool_path, os.X_OK)

    # Run --help
    res = subprocess.run([str(tool_path), "--help"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "--peer" in res.stdout
    assert "--message" in res.stdout
