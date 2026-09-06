import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from urp.core import (
    AbstractURPAgent,
    AgentDescriptor,
    AgentContext,
    FailureCategory,
    LastTaskOutcome,
    MessageEnvelope,
    ProcessResult,
)
from .pi_rpc_client import PiRpcClient
from .rpc_types import RpcEvent, PiRpcError

logger = logging.getLogger("urp.pi_urp_agent")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class PiURPAgent(AbstractURPAgent):
    """
    Base URP Agent backed by the Pi Agent Harness via PiRpcClient.

    Combines URP state machine lifecycle, mailbox-driven execution loop, precondition/postcondition
    hooks, and outcome acknowledgment controls with Pi's high-performance RPC execution engine.
    """

    def __init__(self, descriptor: AgentDescriptor):
        super().__init__(descriptor)
        self.pi_client: Optional[PiRpcClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _on_initialize(self, context: AgentContext) -> None:
        """URP Initialization Hook: Configures and instantiates PiRpcClient."""
        logger.info(f"[{self.descriptor.agent_id}] Initializing PiURPAgent context...")
        config = getattr(context, "configuration", {}) or {}

        workspace_dir = (
            config.get("workspace_dir")
            or getattr(context, "workspace_path", None)
            or os.getcwd()
        )
        model = config.get("model") or os.getenv("LLM_MODEL")
        provider = config.get("provider") or os.getenv("LLM_PROVIDER")
        session_dir = config.get("session_dir")
        no_session = config.get("no_session", False)
        system_prompt = config.get("system_prompt")
        name = config.get("name") or self.descriptor.name
        extra_args = list(config.get("extra_args") or [])
        env = config.get("env")
        executable_path = config.get("executable_path") or "pi"

        # Thinking level from configuration (off, minimal, low, medium, high, xhigh, max)
        self.thinking_level: Optional[str] = config.get("thinking_level") or config.get("thinking")
        if self.thinking_level and "--thinking" not in extra_args:
            extra_args.extend(["--thinking", self.thinking_level])

        # Auto-compaction & reserve/keep tokens flags if provided
        self.auto_compaction: Optional[bool] = config.get("auto_compaction")
        compaction_cfg = config.get("compaction") or {}
        if isinstance(compaction_cfg, dict):
            if "enabled" in compaction_cfg and self.auto_compaction is None:
                self.auto_compaction = compaction_cfg.get("enabled")

        # Configurable settlement timeout defaulting to 10 minutes (600 seconds)
        self.settlement_timeout: float = float(
            config.get("settlement_timeout") or config.get("timeout") or 600.0
        )

        self.pi_client = PiRpcClient(
            workspace_dir=workspace_dir,
            model=model,
            provider=provider,
            session_dir=session_dir,
            no_session=no_session,
            system_prompt=system_prompt,
            name=name,
            extra_args=extra_args,
            env=env,
            executable_path=executable_path,
        )

        # Register wildcard telemetry event forwarder
        self.pi_client.on_any_event(self._handle_pi_telemetry_event)

    def _handle_pi_telemetry_event(self, rpc_evt: RpcEvent) -> None:
        """Schedules async forwarding of Pi RPC events to the URP event bus."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._forward_telemetry_event(rpc_evt))
        except RuntimeError:
            pass

    async def _forward_telemetry_event(self, rpc_evt: RpcEvent) -> None:
        """Maps Pi RPC events to URP telemetry envelopes and emits them."""
        # Handle streaming text deltas if caller requested streaming
        if rpc_evt.type == "message_update":
            if self.is_streaming:
                delta = rpc_evt.data.get("delta")
                if not delta:
                    delta = rpc_evt.data.get("assistantMessageEvent", {}).get("delta")
                if not delta:
                    delta = rpc_evt.data.get("assistant_message_event", {}).get("delta")

                if delta:
                    await self.emit_chunk(delta, event_type="TEXT_DELTA")
            return

        msg_type_map = {
            "tool_execution_start": "AGENT_TOOL_START",
            "tool_execution_end": "AGENT_TOOL_END",
            "compaction_start": "AGENT_COMPACTION_START",
            "compaction_end": "AGENT_COMPACTION_END",
            "error": "AGENT_ERROR_LOG",
        }

        # Check for sub-task delegation via the 'delegate' tool
        if rpc_evt.type == "tool_execution_start" and rpc_evt.data.get("toolName") == "delegate":
            # Emit first-class subtask event
            await self.emit(MessageEnvelope(
                type="TASK_SUBTASK_STARTED",
                payload=rpc_evt.data,
                sender=self.descriptor.agent_id,
                context_id=self._current_message.context_id if self._current_message else None,
                task_id=self._current_message.task_id if self._current_message else None,
            ))

        elif rpc_evt.type == "tool_execution_end" and rpc_evt.data.get("toolName") == "delegate":
            # Emit subtask finished event
            await self.emit(MessageEnvelope(
                type="TASK_SUBTASK_COMPLETED",
                payload=rpc_evt.data,
                sender=self.descriptor.agent_id,
                context_id=self._current_message.context_id if self._current_message else None,
                task_id=self._current_message.task_id if self._current_message else None,
            ))

        urp_event_type = msg_type_map.get(rpc_evt.type)
        if urp_event_type:
            envelope = MessageEnvelope(
                type=urp_event_type,
                payload=rpc_evt.data,
                sender=self.descriptor.agent_id,
                receiver="SUPERVISOR",
                context_id=self._current_message.context_id if self._current_message else None,
                task_id=self._current_message.task_id if self._current_message else None,
            )
            await self.emit(envelope)

    async def _check_start_preconditions(self) -> tuple[bool, str]:
        """URP Start Precondition Hook: Starts PiRpcClient subprocess and verifies state."""
        if not self.pi_client:
            return False, "PiRpcClient instance not initialized"

        try:
            logger.info(f"[{self.descriptor.agent_id}] Starting PiRpcClient subprocess...")
            await self.pi_client.start()

            state_resp = await self.pi_client.get_state()
            if not state_resp.success:
                return False, f"Pi RPC initial state check failed: {state_resp.error}"

            # Apply runtime compaction setting if configured
            if self.auto_compaction is not None:
                await self.pi_client.set_auto_compaction(self.auto_compaction)

            return True, "PiRpcClient started and verified successfully"
        except Exception as e:
            logger.error(f"[{self.descriptor.agent_id}] Failed starting PiRpcClient: {e}")
            return False, f"Failed starting PiRpcClient subprocess: {e}"

    async def process(self, message: MessageEnvelope) -> ProcessResult:
        """
        Core URP execution primitive.
        Translates MessageEnvelope payload into a Pi prompt, monitors streaming events,
        and constructs ProcessResult outcome.
        """
        if not self.pi_client or not self.pi_client.is_running:
            logger.error(f"[{self.descriptor.agent_id}] Cannot process: PiRpcClient is not running.")
            return ProcessResult(
                outcome=LastTaskOutcome.TASK_FAILED,
                category=FailureCategory.INFRASTRUCTURE_FAILURE,
                text="Pi RPC client subprocess is not running."
            )

        # 1. Parse prompt text and attachments from envelope payload
        user_text = ""
        images = None

        if isinstance(message.payload, dict):
            user_text = message.payload.get("text") or message.payload.get("prompt") or str(message.payload)
            images = message.payload.get("images") or message.metadata.get("images")
        elif isinstance(message.payload, str):
            user_text = message.payload
        elif hasattr(message.payload, "text"):
            user_text = getattr(message.payload, "text", str(message.payload))
        else:
            user_text = str(message.payload)

        # 2. Setup settlement listener
        settled_event = asyncio.Event()

        def on_settle_evt(evt: RpcEvent):
            if evt.type in ("agent_settled", "agent_end"):
                settled_event.set()

        self.pi_client.on_any_event(on_settle_evt)

        logger.info(f"[{self.descriptor.agent_id}] Sending prompt to Pi RPC client: {user_text[:100]}...")

        # 3. Issue prompt to Pi harness
        try:
            prompt_resp = await self.pi_client.send_prompt(user_text, images=images)
            if not prompt_resp.success:
                logger.error(f"[{self.descriptor.agent_id}] Prompt command failed: {prompt_resp.error}")
                return ProcessResult(
                    outcome=LastTaskOutcome.TASK_FAILED,
                    category=FailureCategory.INFRASTRUCTURE_FAILURE,
                    text=prompt_resp.error or "Pi prompt command failed"
                )

            # Wait for execution turn settlement with configurable timeout (default 600s / 10m)
            try:
                await asyncio.wait_for(settled_event.wait(), timeout=self.settlement_timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    f"[{self.descriptor.agent_id}] Agent execution timed out after {self.settlement_timeout}s. "
                    f"Aborting execution in Pi RPC harness..."
                )

                # 1. Stop current agent execution in Pi harness
                try:
                    await self.pi_client.abort()
                except Exception as abort_err:
                    logger.error(f"[{self.descriptor.agent_id}] Error sending abort command on timeout: {abort_err}")

                # 2. Collect last assistant response text generated prior to timeout
                assistant_text = ""
                try:
                    text_resp = await self.pi_client.get_last_assistant_text()
                    if text_resp.success:
                        assistant_text = text_resp.data.get("text") or ""
                except Exception as fetch_err:
                    logger.error(f"[{self.descriptor.agent_id}] Error fetching last text after timeout: {fetch_err}")

                # 3. Return TASK_FAILED with FailureCategory.AGENTIC_FAILURE
                return ProcessResult(
                    outcome=LastTaskOutcome.TASK_FAILED,
                    category=FailureCategory.AGENTIC_FAILURE,
                    text=f"Agent execution timed out after {self.settlement_timeout} seconds. Last response: {assistant_text}"
                )

            # 4. Fetch last assistant response for successful settlement
            text_resp = await self.pi_client.get_last_assistant_text()
            assistant_text = text_resp.data.get("text") if text_resp.success else ""

            return ProcessResult(
                outcome=LastTaskOutcome.TASK_COMPLETED,
                category=FailureCategory.NONE,
                text=assistant_text or ""
            )

        except Exception as e:
            logger.error(f"[{self.descriptor.agent_id}] Exception during process execution: {e}", exc_info=True)
            return ProcessResult(
                outcome=LastTaskOutcome.TASK_FAILED,
                category=FailureCategory.INFRASTRUCTURE_FAILURE,
                text=f"Execution error: {str(e)}"
            )

    async def get_raw_log_path(self) -> Optional[str]:
        """Queries the underlying Pi RPC harness for the active JSONL session log file."""
        if not self.pi_client or not self.pi_client.is_running:
            return None
        try:
            state_resp = await self.pi_client.get_state()
            if state_resp.success and state_resp.data:
                return state_resp.data.get("sessionFile")
        except Exception as e:
            logger.warning(f"[{self.descriptor.agent_id}] Could not retrieve raw session log path: {e}")
        return None

    async def _on_shutdown(self) -> None:
        """URP Shutdown Hook: Closes PiRpcClient subprocess."""
        if self.pi_client:
            logger.info(f"[{self.descriptor.agent_id}] Shutting down PiRpcClient...")
            await self.pi_client.close()
