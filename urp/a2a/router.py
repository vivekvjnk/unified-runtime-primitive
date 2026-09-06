"""A2A HTTP+JSON / REST Protocol Router.

Standard Endpoints:
- GET /.well-known/agent.json (Agent Card discovery)
- GET /a2a/v1/agents (Catalog of all registered agent cards)
- POST /message:send (Synchronous message dispatch)
- POST /message:stream (Streaming turn with SSE text/event-stream)
- GET /tasks/{id} (Task query)
- GET /tasks (Task list with filtering)
- POST /tasks/{id}:cancel (Task cancellation)
- POST /tasks/{id}:subscribe (SSE subscription for ongoing task)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from urp.a2a.models import (
    AgentCard,
    CancelTaskRequest,
    Message as A2AMessage,
    Part,
    Role,
    SendMessageRequest,
    SendMessageResponse,
    StreamResponse,
    Task as A2ATask,
    TaskState,
    TaskStatus,
)
from urp.a2a.task_manager import task_manager
from urp.a2a.translator import A2ATranslator
from urp.core import get_registered_agent_types
from urp.web.agent_service import AgentHostingService

logger = logging.getLogger("urp.a2a.router")

a2a_router = APIRouter(tags=["A2A Protocol"])


def _get_hosting_service(request: Request) -> AgentHostingService:
    """Retrieves the global AgentHostingService instance from the web app state."""
    # If app.state.service exists, use it; otherwise fallback to imported singleton
    from urp.web.routes import service
    return service


# ---------------------------------------------------------------------------
# 1. Agent Discovery (Agent Card)
# ---------------------------------------------------------------------------

@a2a_router.get("/.well-known/agent.json", response_model=AgentCard)
async def get_well_known_agent_card(request: Request):
    """Returns the active agent's self-describing Agent Card."""
    service = _get_hosting_service(request)
    base_url = str(request.base_url).rstrip("/")

    if service.host and service.host.descriptor:
        return A2ATranslator.descriptor_to_agent_card(service.host.descriptor, base_url=base_url)

    # If no agent running yet, pick first registered or fallback
    types = service.get_registered_types()
    if types:
        first_desc = get_registered_agent_types().get(types[0]["id"])
        if first_desc:
            return A2ATranslator.descriptor_to_agent_card(first_desc, base_url=base_url)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No agent configured")


@a2a_router.get("/a2a/v1/agents", response_model=List[AgentCard])
async def list_agent_cards(request: Request):
    """Returns all registered agent cards available in this URP host catalog."""
    base_url = str(request.base_url).rstrip("/")
    descriptors = get_registered_agent_types()
    return [A2ATranslator.descriptor_to_agent_card(desc, base_url=base_url) for desc in descriptors.values()]


# ---------------------------------------------------------------------------
# 2. Message Operations: Synchronous (POST /message:send)
# ---------------------------------------------------------------------------

@a2a_router.post("/message:send", response_model=SendMessageResponse)
async def send_message_sync(req: SendMessageRequest, request: Request):
    """Sends a message to the agent and waits for task completion (or returns task immediately if configured)."""
    service = _get_hosting_service(request)
    if not service.host or not service.host.agent:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No URP agent is currently deployed. Please initialize an agent first.",
        )

    # 1. Anchor Context and Task IDs
    msg = req.message
    cid = msg.context_id or str(uuid4())
    tid = msg.task_id or str(uuid4())
    msg.context_id = cid
    msg.task_id = tid

    # 2. Register/Create A2ATask
    task = await task_manager.create_or_get_task(
        task_id=tid,
        context_id=cid,
        initial_message=msg,
    )

    # 3. Translate A2AMessage -> URP MessageEnvelope
    envelope = A2ATranslator.a2a_message_to_envelope(
        message=msg,
        sender="a2a_client",
        message_type="MESSAGE",
    )
    envelope.streaming = False

    # Check return_immediately configuration
    return_immediately = bool(
        req.configuration and req.configuration.return_immediately
    )

    # Dispatch to mailbox
    await service.host.agent.send(envelope)

    if return_immediately:
        return SendMessageResponse(task=task)

    # Wait for completion via event loop polling
    timeout = 120.0
    start_time = asyncio.get_running_loop().time()
    host_listener = service.host.add_listener()

    try:
        while True:
            if (asyncio.get_running_loop().time() - start_time) > timeout:
                raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Agent execution timed out")

            updated_task = await task_manager.get_task(tid)
            if updated_task and updated_task.status.state in (
                TaskState.TASK_STATE_COMPLETED,
                TaskState.TASK_STATE_FAILED,
                TaskState.TASK_STATE_CANCELED,
                TaskState.TASK_STATE_INPUT_REQUIRED,
            ):
                return SendMessageResponse(task=updated_task)

            # Check latest host events from registered listener
            try:
                event = await asyncio.wait_for(host_listener.get(), timeout=0.2)
                if event.task_id and event.task_id != tid:
                    continue

                stream_resp = A2ATranslator.envelope_to_stream_response(event)
                if stream_resp and stream_resp.status_update:
                    su = stream_resp.status_update
                    updated = await task_manager.update_task_status(
                        task_id=tid,
                        state=su.status.state,
                        message=su.status.message,
                        metadata=su.metadata,
                    )
                    if su.status.state in (
                        TaskState.TASK_STATE_COMPLETED,
                        TaskState.TASK_STATE_FAILED,
                    ):
                        return SendMessageResponse(task=updated)
            except asyncio.TimeoutError:
                pass
    finally:
        if service.host:
            service.host.remove_listener(host_listener)


# ---------------------------------------------------------------------------
# 3. Message Operations: Real-Time Streaming (POST /message:stream)
# ---------------------------------------------------------------------------

@a2a_router.post("/message:stream")
async def send_message_stream(req: SendMessageRequest, request: Request):
    """Sends a message with real-time SSE streaming (Server-Sent Events)."""
    service = _get_hosting_service(request)
    if not service.host or not service.host.agent:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No URP agent is currently deployed. Please initialize an agent first.",
        )

    # 1. Setup IDs
    msg = req.message
    cid = msg.context_id or str(uuid4())
    tid = msg.task_id or str(uuid4())
    msg.context_id = cid
    msg.task_id = tid

    # 2. Register Task & Subscriber
    task = await task_manager.create_or_get_task(task_id=tid, context_id=cid, initial_message=msg)
    queue = await task_manager.subscribe(tid)

    # 3. Translate with streaming=True
    envelope = A2ATranslator.a2a_message_to_envelope(
        message=msg,
        sender="a2a_client",
        message_type="MESSAGE",
    )
    envelope.streaming = True

    # 4. Background consumer pulling from URPHost and feeding task_manager
    host_listener = service.host.add_listener()

    async def bridge_host_events():
        try:
            while True:
                try:
                    evt = await asyncio.wait_for(host_listener.get(), timeout=0.5)
                    # Filter events: if event has a task_id and it belongs to another task, ignore
                    if evt.task_id and evt.task_id != tid:
                        continue

                    # Anchor IDs to this task if absent
                    if not evt.task_id:
                        evt.task_id = tid
                    if not evt.context_id:
                        evt.context_id = cid

                    stream_resp = A2ATranslator.envelope_to_stream_response(evt)
                    if stream_resp:
                        if stream_resp.status_update:
                            su = stream_resp.status_update
                            await task_manager.update_task_status(
                                task_id=tid,
                                state=su.status.state,
                                message=su.status.message,
                                metadata=su.metadata,
                            )
                        else:
                            await task_manager.publish_event(tid, stream_resp)

                    if evt.type in ("TASK_COMPLETED", "TASK_FAILED", "TASK_PRECONDITIONS_VIOLATED", "TASK_POSTCONDITIONS_VIOLATED"):
                        break
                except asyncio.TimeoutError:
                    # Check if task already terminated
                    t = await task_manager.get_task(tid)
                    if t and t.status.state in (TaskState.TASK_STATE_COMPLETED, TaskState.TASK_STATE_FAILED, TaskState.TASK_STATE_CANCELED):
                        break
                except Exception as e:
                    logger.error(f"Error bridging host events: {e}")
                    break
        finally:
            if service.host:
                service.host.remove_listener(host_listener)

    # Dispatch envelope and launch event bridge
    await service.host.agent.send(envelope)
    asyncio.create_task(bridge_host_events())

    # 5. SSE Generator function
    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Yield initial task state snapshot
            initial_resp = StreamResponse(task=task)
            yield f"data: {initial_resp.model_dump_json(by_alias=True, exclude_none=True)}\n\n"

            while True:
                try:
                    resp = await asyncio.wait_for(queue.get(), timeout=60.0)
                    yield f"data: {resp.model_dump_json(by_alias=True, exclude_none=True)}\n\n"

                    # If terminal, terminate SSE stream cleanly
                    if resp.status_update and resp.status_update.status.state in (
                        TaskState.TASK_STATE_COMPLETED,
                        TaskState.TASK_STATE_FAILED,
                        TaskState.TASK_STATE_CANCELED,
                    ):
                        break
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat comment
                    yield ": keep-alive\n\n"
        finally:
            await task_manager.unsubscribe(tid, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# 4. Task Operations: Get, List, Cancel, Subscribe
# ---------------------------------------------------------------------------

@a2a_router.get("/tasks/{task_id}", response_model=A2ATask)
async def get_task_status(task_id: str):
    """Retrieves latest state, artifacts, and history of a task."""
    task = await task_manager.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID '{task_id}' not found",
        )
    return task


@a2a_router.get("/tasks", response_model=List[A2ATask])
async def list_tasks(
    context_id: Optional[str] = None,
    status: Optional[TaskState] = None,
    limit: int = 50,
):
    """Lists tasks with optional context and status filtering."""
    return await task_manager.list_tasks(context_id=context_id, status=status, limit=limit)


@a2a_router.post("/tasks/{task_id}:cancel", response_model=A2ATask)
async def cancel_task(task_id: str, req: Optional[CancelTaskRequest] = None):
    """Cancels a task in progress."""
    task = await task_manager.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID '{task_id}' not found",
        )

    if task.status.state in (
        TaskState.TASK_STATE_COMPLETED,
        TaskState.TASK_STATE_FAILED,
        TaskState.TASK_STATE_CANCELED,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task '{task_id}' is already in terminal state: {task.status.state.value}",
        )

    updated = await task_manager.update_task_status(
        task_id=task_id,
        state=TaskState.TASK_STATE_CANCELED,
        message=A2AMessage.from_text("Task canceled by client", role=Role.ROLE_AGENT),
    )
    return updated or task


@a2a_router.get("/tasks/{task_id}:subscribe")
async def subscribe_task_stream(task_id: str):
    """Attaches an SSE stream to an existing ongoing task."""
    task = await task_manager.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID '{task_id}' not found",
        )

    if task.status.state in (
        TaskState.TASK_STATE_COMPLETED,
        TaskState.TASK_STATE_FAILED,
        TaskState.TASK_STATE_CANCELED,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot subscribe: task '{task_id}' is already in terminal state",
        )

    queue = await task_manager.subscribe(task_id)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Send current task state snapshot
            initial_resp = StreamResponse(task=task)
            yield f"data: {initial_resp.model_dump_json(by_alias=True, exclude_none=True)}\n\n"

            while True:
                try:
                    resp = await asyncio.wait_for(queue.get(), timeout=60.0)
                    yield f"data: {resp.model_dump_json(by_alias=True, exclude_none=True)}\n\n"
                    if resp.status_update and resp.status_update.status.state in (
                        TaskState.TASK_STATE_COMPLETED,
                        TaskState.TASK_STATE_FAILED,
                        TaskState.TASK_STATE_CANCELED,
                    ):
                        break
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            await task_manager.unsubscribe(task_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
