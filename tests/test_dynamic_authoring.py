import asyncio
import io
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from urp.web.app import create_app
from urp.web.agent_service import AgentHostingService, normalize_agent_name
from urp.web.ecp_service import validate_and_extract_ecp, parse_skill_md_frontmatter
from urp.core import get_registered_agent_types


@pytest.fixture
def temp_workspace():
    tmp_dir = tempfile.mkdtemp(prefix="urp_workspace_authoring_")
    yield tmp_dir
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_parse_skill_md_frontmatter():
    sample = """---
name: yocto-docker-ops
description: Build container validation and Bitbake commands
---

# Operational Instructions
Run docker build.
"""
    meta = parse_skill_md_frontmatter(sample)
    assert meta["name"] == "yocto-docker-ops"
    assert meta["description"] == "Build container validation and Bitbake commands"


def test_validate_and_extract_ecp_from_dir(temp_workspace):
    # Setup source mock ECP directory
    src_ecp = Path(temp_workspace) / "test_ecp_src"
    src_ecp.mkdir(parents=True)
    (src_ecp / "SKILL.md").write_text("""---
name: c-systems-pty
description: PTY orchestration and terminal debugging
---
# Guide
""", encoding="utf-8")
    tools_dir = src_ecp / "tools"
    tools_dir.mkdir()
    script = tools_dir / "check_pty.sh"
    script.write_text("#!/bin/bash\necho ok", encoding="utf-8")

    # Ingest into workspace
    res = validate_and_extract_ecp(workspace_path=temp_workspace, source_dir=src_ecp)
    assert res["skill_name"] == "c-systems-pty"
    assert res["tool_count"] == 1

    extracted_script = Path(temp_workspace) / ".agents" / "skills" / "test_ecp_src" / "tools" / "check_pty.sh"
    assert extracted_script.is_file()
    assert os.access(extracted_script, os.X_OK)


def test_validate_and_extract_ecp_from_zip(temp_workspace):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("my_ecp/SKILL.md", "---\nname: my-test-ecp\ndescription: A test ECP archive\n---\n")
        zf.writestr("my_ecp/tools/run.sh", "#!/bin/bash\necho 123")

    buf.seek(0)
    res = validate_and_extract_ecp(workspace_path=temp_workspace, archive_bytes=buf.getvalue())
    assert res["skill_name"] == "my-test-ecp"
    assert res["tool_count"] == 1

    extracted = Path(temp_workspace) / ".agents" / "skills" / "my_ecp" / "SKILL.md"
    assert extracted.is_file()


@pytest.mark.asyncio
async def test_agent_create_and_register_service(temp_workspace):
    service = AgentHostingService()
    # Temporary configs dir to avoid dirtying repo configs/
    configs_tmp = Path(temp_workspace) / "configs"

    host = await service.create_and_register_agent(
        agent_name="Tiny Infra Specialist",  # will normalize to tiny_infra_specialist
        workspace_path=temp_workspace,
        description="Docker build and system container specialist",
        system_prompt="You are a container specialist.",
        harness="echo",  # Use echo harness for lightning-fast test execution
        configs_dir=configs_tmp,
    )
    assert host is not None
    assert "tiny_infra_specialist" in service.hosts
    assert service.active_agent_name == "tiny_infra_specialist"

    # Declarative config saved
    assert (configs_tmp / "tiny_infra_specialist.json").exists()

    # Project-bound A2A card exported
    assert (Path(temp_workspace) / ".well_known" / "tiny_infra_specialist.json").exists()

    # Send message to newly authored agent
    msg_id = await service.send_message(
        message_type="MESSAGE",
        payload={"text": "Verify docker environment"},
        agent_name="tiny_infra_specialist",
    )
    assert msg_id is not None

    await service.shutdown()


@pytest.mark.asyncio
async def test_api_create_agent_endpoint(temp_workspace):
    app = create_app()
    transport = ASGITransport(app=app)

    # Prepare mock ECP zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("pty_ecp/SKILL.md", "---\nname: pty-skill\ndescription: PTY tool\n---\n")
        zf.writestr("pty_ecp/tools/test.sh", "#!/bin/bash\necho pty")
    buf.seek(0)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/agent/create",
            data={
                "agent_name": "pty_dev_agent",
                "workspace_path": temp_workspace,
                "description": "Systems C Developer with PTY skills",
                "system_prompt": "You are a C systems engineer.",
                "harness": "echo",
            },
            files={
                "ecp_file": ("pty_ecp.zip", buf.getvalue(), "application/zip")
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "created"
        assert data["agent_name"] == "pty_dev_agent"
        assert len(data["extracted_skills"]) == 1

        # Check skill extraction in workspace
        assert (Path(temp_workspace) / ".agents" / "skills" / "pty_ecp" / "SKILL.md").exists()

        # Check discovery via A2A
        r_cards = await client.get("/a2a/v1/agents")
        assert r_cards.status_code == 200
        names = [c["name"] for c in r_cards.json()]
        assert "pty_dev_agent" in names

        # Targeted A2A message to pty_dev_agent
        r_send = await client.post(
            "/message:send?agent_name=pty_dev_agent",
            json={
                "message": {
                    "role": "ROLE_USER",
                    "parts": [{"text": "Build tiny-agent PTY harness"}],
                }
            },
        )
        assert r_send.status_code == 200
        send_data = r_send.json()
        assert send_data["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
        assert "Echo: Build tiny-agent PTY harness" in send_data["task"]["status"]["message"]["parts"][0]["text"]
