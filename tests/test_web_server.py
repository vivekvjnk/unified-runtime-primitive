import pytest
from fastapi.testclient import TestClient

from urp.web_server import app
from urp.data_types import AgentDescriptor
from urp.agent_registry import register_agent_if_absent
from urp.sample_agent import EchoAgent

client = TestClient(app)

def test_list_agent_types():
    response = client.get("/agent/types")
    assert response.status_code == 200
    types = response.json()
    assert isinstance(types, list)
    type_ids = [t["id"] for t in types]
    assert "echo" in type_ids
    assert "sdk" in type_ids
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
