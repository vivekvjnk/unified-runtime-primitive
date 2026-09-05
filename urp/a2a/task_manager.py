"""A2A In-Memory and Workspace-Backed Task Lifecycle Manager.

Tracks stateful units of work (A2ATask), message history, and output artifacts.
Provides pub/sub subscription queues so SSE streams can cleanly listen to task updates.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

from urp.a2a.models import (
    Artifact,
    Message as A2AMessage,
    Role,
    StreamResponse,
    Task as A2ATask,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)

logger = logging.getLogger("urp.a2a.task_manager")


class A2ATaskManager:
    """Manages active and historical A2A tasks and their subscriber queues."""

    def __init__(self):
        self._tasks: Dict[str, A2ATask] = {}
        self._subscribers: Dict[str, List[asyncio.Queue[StreamResponse]]] = {}
        self._lock = asyncio.Lock()

    async def create_or_get_task(
        self,
        task_id: Optional[str] = None,
        context_id: Optional[str] = None,
        initial_message: Optional[A2AMessage] = None,
    ) -> A2ATask:
        """Creates a new stateful A2A task or returns an existing one."""
        async with self._lock:
            tid = task_id or str(uuid4())
            cid = context_id or str(uuid4())

            if tid in self._tasks:
                task = self._tasks[tid]
                if initial_message:
                    task.history.append(initial_message)
                return task

            history = [initial_message] if initial_message else []
            task = A2ATask(
                id=tid,
                context_id=cid,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_SUBMITTED,
                    message=initial_message,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                ),
                artifacts=[],
                history=history,
            )
            self._tasks[tid] = task
            self._subscribers[tid] = []
            return task

    async def get_task(self, task_id: str) -> Optional[A2ATask]:
        """Retrieves a task by ID."""
        async with self._lock:
            return self._tasks.get(task_id)

    async def list_tasks(
        self,
        context_id: Optional[str] = None,
        status: Optional[TaskState] = None,
        limit: int = 50,
    ) -> List[A2ATask]:
        """Lists tasks matching filters, sorted by status timestamp descending."""
        async with self._lock:
            tasks = list(self._tasks.values())

        if context_id:
            tasks = [t for t in tasks if t.context_id == context_id]
        if status:
            tasks = [t for t in tasks if t.status.state == status]

        tasks.sort(key=lambda t: t.status.timestamp, reverse=True)
        return tasks[:limit]

    async def update_task_status(
        self,
        task_id: str,
        state: TaskState,
        message: Optional[A2AMessage] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[A2ATask]:
        """Updates task state, appends history, and notifies SSE subscribers."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            task.status = TaskStatus(
                state=state,
                message=message,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            if message:
                task.history.append(message)
            if metadata:
                if not task.metadata:
                    task.metadata = {}
                task.metadata.update(metadata)

            # Build status update event for subscribers
            evt = TaskStatusUpdateEvent(
                task_id=task.id,
                context_id=task.context_id or "",
                status=task.status,
                metadata=metadata,
            )
            stream_resp = StreamResponse(status_update=evt)
            subscribers = list(self._subscribers.get(task_id, []))

        # Notify subscribers outside the lock
        for queue in subscribers:
            await queue.put(stream_resp)

        return task

    async def add_task_artifact(
        self,
        task_id: str,
        artifact: Artifact,
    ) -> Optional[A2ATask]:
        """Appends an artifact to task outputs and notifies subscribers."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            task.artifacts.append(artifact)
            evt = TaskArtifactUpdateEvent(
                task_id=task.id,
                context_id=task.context_id or "",
                artifact=artifact,
            )
            stream_resp = StreamResponse(artifact_update=evt)
            subscribers = list(self._subscribers.get(task_id, []))

        for queue in subscribers:
            await queue.put(stream_resp)

        return task

    async def publish_event(
        self,
        task_id: str,
        stream_response: StreamResponse,
    ) -> None:
        """Pushes an arbitrary A2A stream response (e.g. text chunk, tool log) to subscribers."""
        async with self._lock:
            subscribers = list(self._subscribers.get(task_id, []))

        for queue in subscribers:
            await queue.put(stream_response)

    async def subscribe(self, task_id: str) -> asyncio.Queue[StreamResponse]:
        """Subscribes an SSE connection to events for the given task."""
        queue: asyncio.Queue[StreamResponse] = asyncio.Queue()
        async with self._lock:
            if task_id not in self._subscribers:
                self._subscribers[task_id] = []
            self._subscribers[task_id].append(queue)
        return queue

    async def unsubscribe(self, task_id: str, queue: asyncio.Queue[StreamResponse]) -> None:
        """Removes an SSE connection queue from task subscribers."""
        async with self._lock:
            if task_id in self._subscribers and queue in self._subscribers[task_id]:
                self._subscribers[task_id].remove(queue)


# Global singleton task manager for runtime instance
task_manager = A2ATaskManager()
