"""URP <-> A2A Bidirectional Protocol Translator.

Converts:
- A2AMessage / SendMessageRequest -> URP MessageEnvelope
- URP MessageEnvelope -> A2A TaskStatusUpdateEvent / TaskArtifactUpdateEvent
- URP ProcessResult -> A2A Task (completed or failed)
- URP AgentDescriptor -> A2A AgentCard
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from urp.core.data_types import (
    AgentDescriptor,
    FailureCategory,
    LastTaskOutcome,
    MessageEnvelope,
    ProcessResult,
)
from urp.a2a.models import (
    AgentCard,
    AgentCapabilities,
    AgentInterface,
    AgentSkill,
    Artifact,
    Message as A2AMessage,
    Part,
    Role,
    StreamResponse,
    Task as A2ATask,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)


class A2ATranslator:
    """Provides stateless conversion utilities between A2A protocol types and URP primitives."""

    @staticmethod
    def a2a_message_to_envelope(
        message: A2AMessage,
        sender: str = "a2a_client",
        message_type: str = "MESSAGE",
    ) -> MessageEnvelope:
        """Translates an inbound A2A Message into an execution-ready URP MessageEnvelope."""
        # Extract concatenated text from text parts
        extracted_text = message.get_text()

        # Build payload preserving original parts and metadata
        payload: Dict[str, Any] = {
            "text": extracted_text,
            "parts": [p.model_dump(by_alias=True, exclude_none=True) for p in message.parts],
            "role": message.role.value,
        }
        if message.metadata:
            payload["metadata"] = message.metadata

        return MessageEnvelope(
            message_id=message.message_id or str(uuid4()),
            type=message_type,
            payload=payload,
            sender=sender,
            context_id=message.context_id,
            task_id=message.task_id,
            metadata=message.metadata or {},
        )

    @staticmethod
    def envelope_to_a2a_message(
        envelope: MessageEnvelope,
        role: Role = Role.ROLE_AGENT,
    ) -> A2AMessage:
        """Translates an outbound URP MessageEnvelope into an A2A Message."""
        text = ""
        parts: List[Part] = []

        if isinstance(envelope.payload, dict):
            text = envelope.payload.get("text", "")
            raw_parts = envelope.payload.get("parts")
            if raw_parts and isinstance(raw_parts, list):
                for rp in raw_parts:
                    if isinstance(rp, dict):
                        parts.append(Part(**rp))
        elif isinstance(envelope.payload, str):
            text = envelope.payload

        if not parts and text:
            parts.append(Part(text=text, media_type="text/plain"))

        return A2AMessage(
            message_id=envelope.message_id,
            context_id=envelope.context_id,
            task_id=envelope.task_id,
            role=role,
            parts=parts,
            metadata=envelope.metadata or {},
        )

    @staticmethod
    def envelope_to_stream_response(
        envelope: MessageEnvelope,
    ) -> Optional[StreamResponse]:
        """Translates an emitted URP event envelope into an A2A SSE StreamResponse."""
        task_id = envelope.task_id or str(uuid4())
        context_id = envelope.context_id or "default_context"

        # 1. Terminal Outcomes
        if envelope.type == "TASK_COMPLETED":
            result_text = ""
            artifacts: List[Artifact] = []

            if isinstance(envelope.payload, dict):
                result_text = envelope.payload.get("text", "")
                raw_artifacts = envelope.payload.get("artifacts", [])
                for ra in raw_artifacts:
                    if isinstance(ra, dict):
                        # Convert dict to Artifact
                        part_list = [Part(text=ra.get("content", ""))] if "content" in ra else []
                        artifacts.append(
                            Artifact(
                                artifact_id=ra.get("id", str(uuid4())),
                                name=ra.get("name"),
                                parts=part_list,
                                metadata=ra.get("metadata"),
                            )
                        )

            status_msg = A2AMessage.from_text(
                text=result_text or "Task completed successfully.",
                role=Role.ROLE_AGENT,
                context_id=context_id,
                task_id=task_id,
            )

            status_update = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_COMPLETED,
                    message=status_msg,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                ),
                metadata=envelope.metadata or {},
            )
            return StreamResponse(status_update=status_update)

        elif envelope.type in ["TASK_FAILED", "TASK_PRECONDITIONS_VIOLATED", "TASK_POSTCONDITIONS_VIOLATED"]:
            err_msg = ""
            if isinstance(envelope.payload, dict):
                err_msg = envelope.payload.get("error") or envelope.payload.get("details") or envelope.type
            elif isinstance(envelope.payload, str):
                err_msg = envelope.payload
            else:
                err_msg = str(envelope.type)

            status_msg = A2AMessage.from_text(
                text=f"Task failed: {err_msg}",
                role=Role.ROLE_AGENT,
                context_id=context_id,
                task_id=task_id,
            )

            status_update = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_FAILED,
                    message=status_msg,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                ),
                metadata=envelope.metadata or {},
            )
            return StreamResponse(status_update=status_update)

        # 2. In-flight Streaming Text Deltas
        elif envelope.type in ["TEXT_DELTA", "CHUNK"]:
            delta_text = ""
            if isinstance(envelope.payload, dict):
                delta_text = envelope.payload.get("delta") or envelope.payload.get("text") or ""
            elif isinstance(envelope.payload, str):
                delta_text = envelope.payload

            msg_delta = A2AMessage.from_text(
                text=delta_text,
                role=Role.ROLE_AGENT,
                context_id=context_id,
                task_id=task_id,
            )
            status_update = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_WORKING,
                    message=msg_delta,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                ),
                metadata={"is_chunk": True},
            )
            return StreamResponse(status_update=status_update)

        # 3. Sub-task Delegation Events
        elif envelope.type in ["TASK_SUBTASK_STARTED", "TASK_SUBTASK_COMPLETED"]:
            subtask_meta: Dict[str, Any] = {"event_type": envelope.type}
            if isinstance(envelope.payload, dict):
                subtask_meta.update(envelope.payload)
            elif envelope.payload:
                subtask_meta["payload"] = envelope.payload

            status_update = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_WORKING,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                ),
                metadata=subtask_meta,
            )
            return StreamResponse(status_update=status_update)

        # 4. Intermediate Progress & Tool Execution
        elif envelope.type in ["AGENT_TOOL_START", "AGENT_TOOL_END", "AGENT_PROGRESS_UPDATE", "TASK_PROGRESS"]:
            log_meta: Dict[str, Any] = {"event_type": envelope.type}
            if isinstance(envelope.payload, dict):
                log_meta.update(envelope.payload)
            elif envelope.payload:
                log_meta["payload"] = envelope.payload

            status_update = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_WORKING,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                ),
                metadata=log_meta,
            )
            return StreamResponse(status_update=status_update)

        # 3. Direct Message
        elif envelope.type == "MESSAGE":
            msg = A2ATranslator.envelope_to_a2a_message(envelope, role=Role.ROLE_AGENT)
            return StreamResponse(message=msg)

        return None

    @staticmethod
    def process_result_to_task(
        task_id: str,
        context_id: str,
        result: ProcessResult,
    ) -> A2ATask:
        """Builds a terminal A2ATask snapshot from a URP ProcessResult."""
        state = (
            TaskState.TASK_STATE_COMPLETED
            if result.outcome == LastTaskOutcome.TASK_COMPLETED
            else TaskState.TASK_STATE_FAILED
        )

        msg = A2AMessage.from_text(
            text=result.text or "",
            role=Role.ROLE_AGENT,
            context_id=context_id,
            task_id=task_id,
        )

        artifacts: List[Artifact] = []
        for ra in result.artifacts:
            if isinstance(ra, dict):
                part_list = [Part(text=ra.get("content", ""))] if "content" in ra else []
                artifacts.append(
                    Artifact(
                        artifact_id=ra.get("id", str(uuid4())),
                        name=ra.get("name"),
                        parts=part_list,
                        metadata=ra.get("metadata"),
                    )
                )

        return A2ATask(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(
                state=state,
                message=msg,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            ),
            artifacts=artifacts,
            metadata=result.metadata or {},
        )

    @staticmethod
    def descriptor_to_agent_card(
        descriptor: AgentDescriptor,
        base_url: str = "http://localhost:8000",
    ) -> AgentCard:
        """Converts a URP AgentDescriptor into a fully-qualified A2A AgentCard."""
        # Use existing to_agent_card helper as source
        card_dict = descriptor.to_agent_card(base_url=base_url)

        skills = [
            AgentSkill(
                id=cap.lower().replace(" ", "-"),
                name=cap,
                description=f"Capability {cap}",
                tags=[cap.lower()],
            )
            for cap in descriptor.capabilities
        ]

        interfaces = [
            AgentInterface(
                url=f"{base_url.rstrip('/')}/a2a/v1",
                protocol_binding="HTTP+JSON",
                protocol_version="1.0",
            )
        ]

        return AgentCard(
            name=descriptor.name,
            description=card_dict.get("description", ""),
            version=descriptor.version,
            capabilities=AgentCapabilities(
                streaming=True,
                push_notifications=False,
                extended_agent_card=False,
            ),
            supported_interfaces=interfaces,
            skills=skills,
        )
