import pytest
from fastapi.testclient import TestClient

from urp.web import app
from urp.core import AgentDescriptor, register_agent_if_absent
from urp.agents import EchoAgent

client = TestClient(app)

def test_list_agent_types():
    response = client.get("/agent/types")
    assert response.status_code == 200
    types = response.json()
    assert isinstance(types, list)
    type_ids = [t["id"] for t in types]
    assert "echo_agent" in type_ids
    assert "sdk_agent" in type_ids
    assert "pi_agent" in type_ids

def test_web_server_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "URP-HF" in response.text
    assert "marked.min.js" in response.text

def test_browse_directory(tmp_path):
    response = client.get(f"/agent/browse?path={tmp_path}")
    assert response.status_code == 200
    data = response.json()
    assert "current_path" in data
    assert "items" in data
