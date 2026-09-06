import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from urp.web.app import create_app
from urp.web.agent_service import AgentHostingService, normalize_agent_name
from urp.core import get_registered_agent_types


@pytest.fixture
def temp_workspace():
    tmp_dir = tempfile.mkdtemp(prefix="urp_workspace_test_")
    yield tmp_dir
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_normalize_agent_name():
    assert normalize_agent_name("Echo Diagnostic Agent") == "echo_diagnostic_agent"
    assert normalize_agent_name("tiny-infra-agent") == "tiny_infra_agent"
    assert normalize_agent_name("pi.gemini.v1") == "pi_gemini_v1"
    assert normalize_agent_name("   dev_agent   ") == "dev_agent"


@pytest.mark.asyncio
async def test_multiagent_service_concurrent_hosts(temp_workspace):
    service = AgentHostingService()

    # Initialize agent 1
    host1 = await service.initialize_agent(
        agent_type="echo_agent",
        agent_name="agent_alpha",
        workspace_path=temp_workspace,
    )
    assert "agent_alpha" in service.hosts
    assert service.active_agent_name == "agent_alpha"

    # Initialize agent 2 concurrently
    host2 = await service.initialize_agent(
        agent_type="echo_agent",
        agent_name="agent_beta",
        workspace_path=temp_workspace,
    )
    assert "agent_beta" in service.hosts
    assert "agent_alpha" in service.hosts
    assert service.active_agent_name == "agent_beta"

    # Check running list
    running = service.list_running_agents()
    names = [r["agent_name"] for r in running]
    assert "agent_alpha" in names
    assert "agent_beta" in names

    # Switch active agent
    service.set_active_agent("agent_alpha")
    assert service.active_agent_name == "agent_alpha"

    # Check A2A .well_known card was written to workspace
    well_known_dir = Path(temp_workspace) / ".well_known"
    assert (well_known_dir / "agent_alpha.json").exists()
    assert (well_known_dir / "agent_beta.json").exists()

    with open(well_known_dir / "agent_alpha.json", "r") as f:
        card = json.load(f)
        assert card["name"] == "agent_alpha"

    # Clean shutdown
    await service.shutdown()
    assert len(service.hosts) == 0


@pytest.mark.asyncio
async def test_workspace_well_known_autodetection(temp_workspace):
    service = AgentHostingService()

    # Create a simulated .well_known/tiny_agent_test.json in workspace
    well_known_dir = Path(temp_workspace) / ".well_known"
    well_known_dir.mkdir(parents=True, exist_ok=True)

    card_data = {
        "name": "tiny_infra_ops",
        "description": "Docker and Yocto container build specialist",
        "version": "1.2.0",
        "skills": [{"name": "DOCKER"}, {"name": "YOCTO"}],
    }
    with open(well_known_dir / "tiny_infra_ops.json", "w") as f:
        json.dump(card_data, f)

    # Scan workspace
    discovered = service.scan_workspace_well_known_agents(temp_workspace)
    assert len(discovered) == 1
    assert discovered[0]["agent_name"] == "tiny_infra_ops"

    # Verify registered in registry
    registered = get_registered_agent_types()
    assert "tiny_infra_ops" in registered
    assert registered["tiny_infra_ops"].capabilities == ["DOCKER", "YOCTO"]

    await service.shutdown()


@pytest.mark.asyncio
async def test_a2a_multiagent_routing(temp_workspace):
    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Initialize two agents via API
        r1 = await client.post(
            "/agent/init",
            json={"agent_type": "echo_agent", "agent_name": "worker_one", "workspace_path": temp_workspace},
        )
        assert r1.status_code == 200

        r2 = await client.post(
            "/agent/init",
            json={"agent_type": "echo_agent", "agent_name": "worker_two", "workspace_path": temp_workspace},
        )
        assert r2.status_code == 200

        # Discover all agents via A2A catalog
        r_agents = await client.get("/a2a/v1/agents")
        assert r_agents.status_code == 200
        cards = r_agents.json()
        card_names = [c["name"] for c in cards]
        assert "worker_one" in card_names
        assert "worker_two" in card_names

        # Query well-known card with agent_name
        r_wk = await client.get("/.well-known/agent.json?agent_name=worker_one")
        assert r_wk.status_code == 200
        assert r_wk.json()["name"] == "worker_one"

        # Send A2A message targeted to worker_one via header
        r_msg1 = await client.post(
            "/message:send",
            headers={"X-Target-Agent": "worker_one"},
            json={
                "message": {
                    "role": "ROLE_USER",
                    "parts": [{"text": "Hello Worker One"}],
                }
            },
        )
        assert r_msg1.status_code == 200
        data1 = r_msg1.json()
        assert data1["task"] is not None
        assert data1["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
        assert "Hello Worker One" in data1["task"]["status"]["message"]["parts"][0]["text"]

        # Send A2A message targeted to worker_two via query param
        r_msg2 = await client.post(
            "/message:send?agent_name=worker_two",
            json={
                "message": {
                    "role": "ROLE_USER",
                    "parts": [{"text": "Hello Worker Two"}],
                }
            },
        )
        assert r_msg2.status_code == 200
        data2 = r_msg2.json()
        assert data2["task"] is not None
        assert data2["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
        assert "Hello Worker Two" in data2["task"]["status"]["message"]["parts"][0]["text"]
