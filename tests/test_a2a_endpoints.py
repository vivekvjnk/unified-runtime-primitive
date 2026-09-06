"""Integration tests for A2A HTTP+JSON endpoints, Agent Card discovery, sync and SSE streaming."""

import json
import pytest
from starlette.testclient import TestClient

from urp.web.app import app
from urp.a2a.models import TaskState


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_agent_card_discovery(client):
    """Test 1: GET /.well-known/agent.json returns valid A2A Agent Card."""
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    data = resp.json()

    assert "name" in data
    assert "version" in data
    assert "capabilities" in data
    assert "supportedInterfaces" in data
    assert len(data["supportedInterfaces"]) >= 1
    assert data["supportedInterfaces"][0]["protocolBinding"] == "HTTP+JSON"


def test_agent_catalog(client):
    """Test 2: GET /a2a/v1/agents returns catalog of available agents."""
    resp = client.get("/a2a/v1/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert isinstance(agents, list)
    assert len(agents) >= 1
    names = [a["name"].lower() for a in agents]
    assert any("echo" in n for n in names)


def test_send_message_sync(client):
    """Test 3: POST /message:send executes message and returns completed task."""
    payload = {
        "message": {
            "role": "ROLE_USER",
            "contextId": "test-context-1",
            "taskId": "test-task-1",
            "parts": [{"text": "Hello Echo Agent via A2A"}],
        }
    }
    resp = client.post("/message:send", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert "task" in data
    task = data["task"]
    assert task["id"] == "test-task-1"
    assert task["contextId"] == "test-context-1"
    assert task["status"]["state"] == TaskState.TASK_STATE_COMPLETED.value
    assert "Echo: Hello Echo Agent via A2A" in task["status"]["message"]["parts"][0]["text"]


def test_get_and_list_tasks(client):
    """Test 4: GET /tasks/{id} and GET /tasks query task state."""
    # Retrieve the previously created task
    resp = client.get("/tasks/test-task-1")
    assert resp.status_code == 200
    task = resp.json()
    assert task["id"] == "test-task-1"
    assert task["status"]["state"] == TaskState.TASK_STATE_COMPLETED.value

    # List tasks with filter
    list_resp = client.get("/tasks?context_id=test-context-1")
    assert list_resp.status_code == 200
    tasks = list_resp.json()
    assert len(tasks) >= 1
    assert any(t["id"] == "test-task-1" for t in tasks)


def test_send_message_stream_sse(client):
    """Test 5: POST /message:stream delivers Server-Sent Events (SSE)."""
    payload = {
        "message": {
            "role": "ROLE_USER",
            "contextId": "stream-context-1",
            "taskId": "stream-task-1",
            "parts": [{"text": "Streaming test prompt"}],
        }
    }

    # Stream response
    with client.stream("POST", "/message:stream", json=payload) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        events = []
        for line in response.iter_lines():
            if line and line.startswith("data: "):
                raw_json = line[len("data: "):]
                events.append(json.loads(raw_json))
                # Stop once completed
                if events[-1].get("statusUpdate", {}).get("status", {}).get("state") == TaskState.TASK_STATE_COMPLETED.value:
                    break

        assert len(events) >= 1
        # First event is either the initial task snapshot or status update
        has_task = any("task" in e for e in events)
        has_status = any("statusUpdate" in e for e in events)
        assert has_task or has_status


def test_cancel_terminal_task_error(client):
    """Test 6: POST /tasks/{id}:cancel returns 400 when task already completed."""
    resp = client.post("/tasks/test-task-1:cancel")
    assert resp.status_code == 400
    assert "already in terminal state" in resp.json()["detail"]
