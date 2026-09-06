"""
A2A (Agent2Agent) Client Subsystem.

Provides:
- In-process or HTTP-based peer calling between URP agents.
- Synchronous task delegation to a target peer agent over the A2A protocol.
- Discovery of peer agent cards from the local or remote A2A catalog.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx

from urp.a2a.models import (
    AgentCard,
    Message as A2AMessage,
    Part,
    Role,
    SendMessageRequest,
    SendMessageResponse,
    Task as A2ATask,
    TaskState,
)

logger = logging.getLogger("urp.a2a.client")


class A2APeerClient:
    """Client for communicating with peer agents over the A2A REST protocol."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url.rstrip("/")

    async def list_peers(self) -> List[AgentCard]:
        """Queries the A2A catalog for all available peer agents."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=15.0) as client:
            resp = await client.get("/a2a/v1/agents")
            resp.raise_for_status()
            cards_raw = resp.json()
            return [AgentCard(**c) for c in cards_raw]

    async def get_peer_card(self, peer_name: str) -> Optional[AgentCard]:
        """Fetches the self-describing Agent Card for a specific peer."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=15.0) as client:
            resp = await client.get(f"/.well-known/agent.json?agent_name={peer_name}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return AgentCard(**resp.json())

    async def call_peer(
        self,
        peer_name: str,
        message_text: str,
        context_id: Optional[str] = None,
        task_id: Optional[str] = None,
        sender: str = "a2a_peer_agent",
        timeout: float = 180.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Dispatches a task message turn to a peer agent and awaits completion.
        Returns a dictionary with state, output text, artifacts, and task ID.
        """
        cid = context_id or str(uuid4())
        tid = task_id or str(uuid4())

        req_payload = {
            "message": {
                "role": "ROLE_USER",
                "contextId": cid,
                "taskId": tid,
                "parts": [{"text": message_text, "mediaType": "text/plain"}],
                "metadata": metadata or {},
            }
        }

        headers = {
            "Content-Type": "application/json",
            "X-Target-Agent": peer_name,
        }

        async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client:
            resp = await client.post(
                f"/message:send?agent_name={peer_name}",
                json=req_payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        # Extract output text and state
        task = data.get("task")
        if task:
            status = task.get("status", {})
            state = status.get("state", "TASK_STATE_UNSPECIFIED")
            msg = status.get("message", {})
            parts = msg.get("parts", []) if msg else []
            out_text = parts[0].get("text", "") if parts else ""
            artifacts = task.get("artifacts", [])
            return {
                "peer": peer_name,
                "task_id": tid,
                "context_id": cid,
                "state": state,
                "output": out_text,
                "artifacts": artifacts,
                "raw_task": task,
            }

        # Fallback to direct message response
        msg = data.get("message", {})
        parts = msg.get("parts", [])
        out_text = parts[0].get("text", "") if parts else ""
        return {
            "peer": peer_name,
            "task_id": tid,
            "context_id": cid,
            "state": "TASK_STATE_COMPLETED",
            "output": out_text,
            "artifacts": [],
        }


# Convenience module-level functions
async def a2a_call_peer(
    peer_name: str,
    message: str,
    base_url: str = "http://127.0.0.1:8000",
    context_id: Optional[str] = None,
    task_id: Optional[str] = None,
    timeout: float = 180.0,
) -> Dict[str, Any]:
    """Sends a message to an A2A peer agent and returns the execution result."""
    client = A2APeerClient(base_url=base_url)
    return await client.call_peer(
        peer_name=peer_name,
        message_text=message,
        context_id=context_id,
        task_id=task_id,
        timeout=timeout,
    )
