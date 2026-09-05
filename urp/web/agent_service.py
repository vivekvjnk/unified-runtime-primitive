import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from urp.core import (
    create_agent,
    get_agent_factory,
    get_registered_agent_descriptors,
    get_registered_agent_types,
    register_agent_if_absent,
    AgentContext,
    AgentDescriptor,
    MessageEnvelope,
    URPHost,
)
from ..config_loader import load_all_agent_configs
from urp.agents import EchoAgent, PiGeminiAgent
from urp.harnesses import SDKURPAgent, PiURPAgent

logger = logging.getLogger("urp.web.agent_service")

class AgentHostingService:
    """
    Manages active URPHost runtime instances and coordinates with AgentRegistry.
    """

    def __init__(self):
        self.host: Optional[URPHost] = None
        self.event_log: List[dict] = []
        self._ensure_builtins_registered()

    def _ensure_builtins_registered(self) -> None:
        """Loads JSON configurations from configs/agents with safe fallbacks."""
        loaded_from_json = load_all_agent_configs()

        if "echo" not in loaded_from_json:
            register_agent_if_absent(
                name="echo",
                factory_func=lambda descriptor=None: EchoAgent(
                    descriptor=descriptor
                    or AgentDescriptor(
                        agent_id="vhl.echo.v1",
                        name="Echo Agent",
                        version="1.0.0",
                        description="Built-in diagnostic echo agent for testing runtime message loops.",
                        capabilities=["ECHO"],
                        accepted_message_types=["PING", "MESSAGE"],
                    )
                ),
                descriptor=AgentDescriptor(
                    agent_id="vhl.echo.v1",
                    name="Echo Agent",
                    version="1.0.0",
                    description="Built-in diagnostic echo agent for testing runtime message loops.",
                    capabilities=["ECHO"],
                    accepted_message_types=["PING", "MESSAGE"],
                ),
            )

        if "sdk" not in loaded_from_json:
            register_agent_if_absent(
                name="sdk",
                factory_func=lambda descriptor=None: SDKURPAgent(
                    descriptor=descriptor
                    or AgentDescriptor(
                        agent_id="vhl.sdk.v1",
                        name="OpenHands SDK Agent",
                        version="1.0.0",
                        description="Autonomous coding agent powered by OpenHands SDK with terminal and file tools.",
                        capabilities=["TERMINAL", "FILE_EDITOR"],
                        accepted_message_types=["MESSAGE", "TASK"],
                    )
                ),
                descriptor=AgentDescriptor(
                    agent_id="vhl.sdk.v1",
                    name="OpenHands SDK Agent",
                    version="1.0.0",
                    description="Autonomous coding agent powered by OpenHands SDK with terminal and file tools.",
                    capabilities=["TERMINAL", "FILE_EDITOR"],
                    accepted_message_types=["MESSAGE", "TASK"],
                ),
            )

        if "pi_agent" not in loaded_from_json:
            register_agent_if_absent(
                name="pi_agent",
                factory_func=lambda descriptor=None: PiGeminiAgent(
                    descriptor=descriptor
                    or AgentDescriptor(
                        agent_id="vhl.pi.gemini.v1",
                        name="Pi Gemini Coding Agent",
                        version="1.0.0",
                        description="Autonomous agent using Google Vertex Gemini 3.8 Flash with medium thinking effort.",
                        capabilities=["READ", "BASH", "EDIT", "WRITE", "SKILLS"],
                        accepted_message_types=["MESSAGE", "TASK"],
                    )
                ),
                descriptor=AgentDescriptor(
                    agent_id="vhl.pi.gemini.v1",
                    name="Pi Gemini Coding Agent",
                    version="1.0.0",
                    description="Autonomous agent using Google Vertex Gemini 3.8 Flash with medium thinking effort.",
                    capabilities=["READ", "BASH", "EDIT", "WRITE", "SKILLS"],
                    accepted_message_types=["MESSAGE", "TASK"],
                ),
            )

    def get_registered_types(self) -> List[Dict[str, Any]]:
        """Returns catalog of all registered agent types."""
        registered = get_registered_agent_types()
        return [
            {
                "id": name,
                "name": desc.name,
                "description": desc.description,
                "version": desc.version,
                "capabilities": desc.capabilities,
                "accepted_message_types": desc.accepted_message_types,
            }
            for name, desc in registered.items()
        ]

    async def initialize_agent(
        self,
        agent_type: str,
        workspace_path: str,
        conversation_id: Optional[str] = None,
        configuration: Optional[Dict[str, Any]] = None,
    ) -> URPHost:
        """Initializes and runs the requested agent type."""
        if self.host:
            await self.host.shutdown()

        factory = get_agent_factory(agent_type)
        descriptor = factory.descriptor

        class RegistryBoundAgentFactory:
            def __call__(self, descriptor):
                return create_agent(agent_type, descriptor=descriptor)

        self.host = URPHost(agent_class=RegistryBoundAgentFactory(), descriptor=descriptor)

        abs_workspace = os.path.abspath(workspace_path)
        os.makedirs(abs_workspace, exist_ok=True)

        default_cfg = descriptor.metadata.get("default_configuration") or {}
        agent_config = dict(default_cfg)
        if configuration:
            agent_config.update(configuration)

        agent_config["workspace_path"] = abs_workspace
        agent_config["workspace_dir"] = abs_workspace
        if conversation_id:
            agent_config["conversation_id"] = conversation_id

        context = AgentContext(
            workspace_path=abs_workspace,
            configuration=agent_config,
        )

        async def log_event(event: MessageEnvelope):
            self.event_log.append(event.model_dump(mode="json"))

        self.host.set_emit_callback(log_event)
        await self.host.initialize_and_start(context)
        return self.host

    def get_state(self) -> Dict[str, Any]:
        """Returns read-only telemetry and state for the active agent."""
        if not self.host or not self.host.agent:
            return {"status": "OFFLINE"}

        state = self.host.agent.state
        if hasattr(state["status"], "value"):
            state["status"] = state["status"].value

        if hasattr(self.host.agent, "get_conversation_id"):
            state["active_conversation_id"] = self.host.agent.get_conversation_id()

        if self.host.descriptor:
            state["agent_name"] = self.host.descriptor.name
            state["agent_id"] = self.host.descriptor.agent_id

        if state.get("last_process_result") and hasattr(state["last_process_result"], "model_dump"):
            state["last_process_result"] = state["last_process_result"].model_dump(mode="json")

        return state

    async def send_message(
        self,
        message_type: str,
        payload: Any,
        context_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> str:
        """Sends a message to the active agent."""
        if not self.host:
            raise RuntimeError("Host not running")
        return await self.host.send_message(
            message_type=message_type,
            payload=payload,
            context_id=context_id,
            task_id=task_id,
        )

    async def shutdown(self) -> None:
        """Gracefully shuts down the active host."""
        if self.host:
            await self.host.shutdown()
            self.host = None
