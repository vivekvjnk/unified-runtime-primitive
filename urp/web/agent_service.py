import asyncio
import json
import logging
import os
import re
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
from ..config_loader import (
    load_all_agent_configs,
    register_agent_from_file,
    build_agent_from_config,
)
from urp.agents import EchoAgent, PiGeminiAgent
from urp.harnesses import SDKURPAgent, PiURPAgent
from urp.a2a.translator import A2ATranslator
from urp.a2a.models import AgentCard

logger = logging.getLogger("urp.web.agent_service")


def normalize_agent_name(name: str) -> str:
    """
    Normalizes an agent name/id into an underscore-separated lowercase identifier.
    Per A2A standard, agent identity is represented as an underscore-separated, unique string.
    Example: 'Pi Gemini Agent' -> 'pi_gemini_agent', 'tiny-infra-agent' -> 'tiny_infra_agent'
    """
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "agent"


class AgentHostingService:
    """
    Manages concurrent active URPHost runtime instances and coordinates with AgentRegistry,
    supporting multi-agent hosting, target agent resolution, and workspace .well_known persistence.
    """

    def __init__(self):
        self.hosts: Dict[str, URPHost] = {}
        self.active_agent_name: Optional[str] = None
        self.workspace_path: Optional[str] = None
        self.event_log: List[dict] = []
        self._ensure_builtins_registered()

    @property
    def host(self) -> Optional[URPHost]:
        """Backward-compatible accessor for active URPHost."""
        if self.active_agent_name and self.active_agent_name in self.hosts:
            return self.hosts[self.active_agent_name]
        if self.hosts:
            # Fallback to first available host
            return next(iter(self.hosts.values()))
        return None

    def _ensure_builtins_registered(self) -> None:
        """Loads JSON configurations from configs/agents with safe fallbacks."""
        loaded_from_json = load_all_agent_configs()

        if "echo_agent" not in loaded_from_json and "echo" not in loaded_from_json:
            desc = AgentDescriptor(
                agent_id="echo_agent",
                name="echo_agent",
                version="1.0.0",
                description="Built-in diagnostic echo agent for testing runtime message loops.",
                capabilities=["ECHO"],
                accepted_message_types=["PING", "MESSAGE"],
            )
            register_agent_if_absent(
                name="echo_agent",
                factory_func=lambda descriptor=None, **kwargs: EchoAgent(descriptor=descriptor or desc),
                descriptor=desc,
            )

        if "sdk_agent" not in loaded_from_json and "sdk" not in loaded_from_json:
            desc = AgentDescriptor(
                agent_id="sdk_agent",
                name="sdk_agent",
                version="1.0.0",
                description="Autonomous coding agent powered by OpenHands SDK with terminal and file tools.",
                capabilities=["TERMINAL", "FILE_EDITOR"],
                accepted_message_types=["MESSAGE", "TASK"],
            )
            register_agent_if_absent(
                name="sdk_agent",
                factory_func=lambda descriptor=None, **kwargs: SDKURPAgent(descriptor=descriptor or desc),
                descriptor=desc,
            )

        if "pi_gemini_agent" not in loaded_from_json and "pi_agent" not in loaded_from_json:
            desc = AgentDescriptor(
                agent_id="pi_gemini_agent",
                name="pi_gemini_agent",
                version="1.0.0",
                description="Autonomous agent using Google Vertex Gemini 3.8 Flash with medium thinking effort.",
                capabilities=["READ", "BASH", "EDIT", "WRITE", "SKILLS"],
                accepted_message_types=["MESSAGE", "TASK"],
            )
            register_agent_if_absent(
                name="pi_gemini_agent",
                factory_func=lambda descriptor=None, **kwargs: PiGeminiAgent(descriptor=descriptor or desc),
                descriptor=desc,
            )

    def scan_workspace_well_known_agents(self, workspace_path: str | Path) -> List[Dict[str, Any]]:
        """
        Scans <workspace_path>/.well_known/<agent_name>.json for A2A Agent Cards
        or agent config manifests, and registers them in AgentRegistry.
        """
        base_dir = Path(workspace_path).resolve()
        well_known_dir = base_dir / ".well_known"
        discovered: List[Dict[str, Any]] = []

        if not well_known_dir.is_dir():
            return discovered

        for json_file in well_known_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    card_data = json.load(f)

                # Check if this is an A2A AgentCard or URP agent config
                raw_name = card_data.get("name") or json_file.stem
                agent_name = normalize_agent_name(raw_name)

                # If this is a URP agent JSON config with harness, build and register
                if "harness" in card_data:
                    card_data["name"] = agent_name
                    if "descriptor" in card_data and isinstance(card_data["descriptor"], dict):
                        card_data["descriptor"]["agent_id"] = agent_name
                        card_data["descriptor"]["name"] = agent_name
                    name, factory_func, descriptor, default_config = build_agent_from_config(card_data)
                    descriptor.metadata["default_configuration"] = default_config
                    descriptor.metadata["harness"] = card_data.get("harness", "echo")
                    descriptor.metadata["workspace_origin"] = str(json_file)
                    register_agent_if_absent(name=agent_name, factory_func=factory_func, descriptor=descriptor)
                else:
                    # Treat as A2A Agent Card specification
                    version = card_data.get("version", "1.0.0")
                    description = card_data.get("description", "")
                    raw_skills = card_data.get("skills", [])
                    capabilities = []
                    for s in raw_skills:
                        if isinstance(s, dict) and "name" in s:
                            capabilities.append(s["name"])
                        elif isinstance(s, str):
                            capabilities.append(s)

                    descriptor = AgentDescriptor(
                        agent_id=agent_name,
                        name=agent_name,
                        version=version,
                        description=description,
                        capabilities=capabilities,
                        accepted_message_types=["MESSAGE", "TASK"],
                        metadata={"workspace_origin": str(json_file), "raw_card": card_data},
                    )

                    # Default fallback harness for discovered A2A cards is PiGeminiAgent if not specified
                    register_agent_if_absent(
                        name=agent_name,
                        factory_func=lambda descriptor=None, bound_desc=descriptor, **kwargs: PiGeminiAgent(descriptor=descriptor or bound_desc),
                        descriptor=descriptor,
                    )

                discovered.append({
                    "agent_name": agent_name,
                    "path": str(json_file),
                    "description": card_data.get("description", ""),
                })
                logger.info(f"[WorkspaceScan] Discovered workspace agent '{agent_name}' at {json_file}")
            except Exception as e:
                logger.warning(f"[WorkspaceScan] Failed parsing {json_file}: {e}")

        return discovered

    def save_agent_card_to_workspace(self, agent_name: str, workspace_path: str, base_url: str = "http://localhost:8000") -> Path:
        """
        Saves the agent's canonical A2A Agent Card to <workspace_path>/.well_known/<agent_name>.json
        establishing that the agent is an integral part of the project workspace.
        """
        host = self.get_host(agent_name)
        if not host or not host.descriptor:
            # Fallback to registered descriptor
            registered = get_registered_agent_types()
            desc = registered.get(agent_name)
            if not desc:
                raise ValueError(f"Agent '{agent_name}' not found in running hosts or registry.")
        else:
            desc = host.descriptor

        card: AgentCard = A2ATranslator.descriptor_to_agent_card(desc, base_url=base_url)
        well_known_dir = Path(workspace_path).resolve() / ".well_known"
        well_known_dir.mkdir(parents=True, exist_ok=True)

        card_path = well_known_dir / f"{agent_name}.json"
        with open(card_path, "w", encoding="utf-8") as f:
            json.dump(card.model_dump(by_alias=True, exclude_none=True), f, indent=2)

        logger.info(f"[AgentService] Saved A2A Agent Card for '{agent_name}' to {card_path}")
        return card_path

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

    def get_host(self, agent_name: Optional[str] = None) -> Optional[URPHost]:
        """
        Retrieves the URPHost for the requested agent_name or the active agent.
        """
        if agent_name:
            norm_name = normalize_agent_name(agent_name)
            if norm_name in self.hosts:
                return self.hosts[norm_name]
            # Try raw match
            if agent_name in self.hosts:
                return self.hosts[agent_name]

        if self.active_agent_name and self.active_agent_name in self.hosts:
            return self.hosts[self.active_agent_name]

        if self.hosts:
            return next(iter(self.hosts.values()))

        return None

    def set_active_agent(self, agent_name: str) -> None:
        """Sets the active agent context for subsequent interactions."""
        norm_name = normalize_agent_name(agent_name)
        if norm_name not in self.hosts and agent_name in self.hosts:
            norm_name = agent_name
        if norm_name not in self.hosts:
            raise KeyError(f"No running agent host found for '{agent_name}'. Running: {list(self.hosts.keys())}")
        self.active_agent_name = norm_name

    def get_peer_roster_description(self, current_agent_name: str) -> str:
        """Generates a text block describing all available peer agents in the container."""
        lines = []
        for name, host in self.hosts.items():
            if name == current_agent_name:
                continue
            desc = host.descriptor.description if host.descriptor else ""
            caps = ", ".join(host.descriptor.capabilities) if host.descriptor else ""
            lines.append(f"- {name}: {desc} (Capabilities: {caps})")

        # Also add registered agent types not yet running
        for name, desc in get_registered_agent_types().items():
            if name != current_agent_name and name not in self.hosts:
                lines.append(f"- {name}: {desc.description} (Capabilities: {', '.join(desc.capabilities)})")

        if not lines:
            return ""

        return (
            "\n\n## Collaborative Agent2Agent (A2A) Network\n"
            "You are operating within a multi-agent A2A network. The following peer agents are available:\n"
            + "\n".join(lines) +
            "\n\nYou can delegate tasks to any peer agent by executing the `a2a_peer_call` tool via bash:\n"
            "  a2a_peer_call --peer <peer_agent_name> --message \"<clear request>\"\n"
        )

    def list_running_agents(self) -> List[Dict[str, Any]]:
        """Returns metadata and status for all currently running agent hosts."""
        result = []
        for name, host in self.hosts.items():
            status_val = "OFFLINE"
            if host.agent and hasattr(host.agent, "state"):
                st = host.agent.state.get("status")
                status_val = st.value if hasattr(st, "value") else str(st)

            result.append({
                "agent_name": name,
                "agent_id": host.descriptor.agent_id if host.descriptor else name,
                "status": status_val,
                "is_active": (name == self.active_agent_name),
                "description": host.descriptor.description if host.descriptor else "",
                "capabilities": host.descriptor.capabilities if host.descriptor else [],
            })
        return result
        result = []
        for name, host in self.hosts.items():
            status_val = "OFFLINE"
            if host.agent and hasattr(host.agent, "state"):
                st = host.agent.state.get("status")
                status_val = st.value if hasattr(st, "value") else str(st)

            result.append({
                "agent_name": name,
                "agent_id": host.descriptor.agent_id if host.descriptor else name,
                "status": status_val,
                "is_active": (name == self.active_agent_name),
                "description": host.descriptor.description if host.descriptor else "",
                "capabilities": host.descriptor.capabilities if host.descriptor else [],
            })
        return result

    async def initialize_agent(
        self,
        agent_type: str,
        workspace_path: str,
        conversation_id: Optional[str] = None,
        configuration: Optional[Dict[str, Any]] = None,
        agent_name: Optional[str] = None,
    ) -> URPHost:
        """
        Initializes and runs the requested agent type as a distinct URPHost.
        Agent identity is agent_name (agent_id == agent_name, underscore-separated).
        Also persists/exports its A2A Agent Card to <workspace_path>/.well_known/<agent_name>.json.
        """
        norm_agent_name = normalize_agent_name(agent_name or agent_type)
        self.workspace_path = os.path.abspath(workspace_path)
        os.makedirs(self.workspace_path, exist_ok=True)

        # First scan workspace for any existing .well_known agent definitions
        self.scan_workspace_well_known_agents(self.workspace_path)

        # If a host for this agent_name is already running, gracefully restart it
        if norm_agent_name in self.hosts:
            logger.info(f"[AgentService] Restarting existing host for '{norm_agent_name}'...")
            await self.hosts[norm_agent_name].shutdown()
            del self.hosts[norm_agent_name]

        # Retrieve factory or fallback
        factory = None
        try:
            factory = get_agent_factory(agent_type)
        except KeyError:
            # Check by norm_agent_name
            try:
                factory = get_agent_factory(norm_agent_name)
                agent_type = norm_agent_name
            except KeyError:
                raise KeyError(f"Agent type '{agent_type}' is not registered in AgentRegistry.")

        # Create descriptor with agent_id == agent_name
        orig_descriptor = factory.descriptor
        descriptor = AgentDescriptor(
            agent_id=norm_agent_name,
            name=norm_agent_name,
            version=orig_descriptor.version,
            description=orig_descriptor.description or f"URP A2A Agent {norm_agent_name}",
            capabilities=list(orig_descriptor.capabilities),
            accepted_message_types=list(orig_descriptor.accepted_message_types),
            metadata=dict(orig_descriptor.metadata),
        )

        class RegistryBoundAgentFactory:
            def __call__(self, descriptor=None, **kwargs):
                return create_agent(agent_type, descriptor=descriptor)

        new_host = URPHost(agent_class=RegistryBoundAgentFactory(), descriptor=descriptor)

        default_cfg = descriptor.metadata.get("default_configuration") or {}
        agent_config = dict(default_cfg)
        if configuration:
            agent_config.update(configuration)

        # Inject A2A peer roster description into system prompt so the agent knows its peers
        peer_roster = self.get_peer_roster_description(norm_agent_name)
        if peer_roster:
            existing_prompt = agent_config.get("system_prompt", "")
            if "## Collaborative Agent2Agent" not in existing_prompt:
                agent_config["system_prompt"] = (existing_prompt + "\n" + peer_roster).strip()

        agent_config["workspace_path"] = self.workspace_path
        agent_config["workspace_dir"] = self.workspace_path
        if conversation_id:
            agent_config["conversation_id"] = conversation_id

        context = AgentContext(
            workspace_path=self.workspace_path,
            configuration=agent_config,
        )

        async def log_event(event: MessageEnvelope):
            event_dict = event.model_dump(mode="json")
            event_dict["agent_name"] = norm_agent_name
            self.event_log.append(event_dict)

        new_host.set_emit_callback(log_event)
        await new_host.initialize_and_start(context)

        # Register in active hosts map
        self.hosts[norm_agent_name] = new_host
        self.active_agent_name = norm_agent_name

        # Persist Agent Card to <project-root>/.well_known/<agent_name>.json
        try:
            self.save_agent_card_to_workspace(norm_agent_name, self.workspace_path)
        except Exception as e:
            logger.warning(f"[AgentService] Could not write .well_known card for '{norm_agent_name}': {e}")

        logger.info(f"[AgentService] Agent '{norm_agent_name}' initialized and active.")
        return new_host

    def get_state(self, agent_name: Optional[str] = None) -> Dict[str, Any]:
        """Returns read-only telemetry and state for the requested or active agent."""
        host = self.get_host(agent_name)
        running = self.list_running_agents()

        if not host or not host.agent:
            return {
                "status": "OFFLINE",
                "active_agent_name": self.active_agent_name,
                "running_agents": running,
            }

        state = dict(host.agent.state)
        if hasattr(state.get("status"), "value"):
            state["status"] = state["status"].value

        if hasattr(host.agent, "get_conversation_id"):
            state["active_conversation_id"] = host.agent.get_conversation_id()

        if host.descriptor:
            state["agent_name"] = host.descriptor.name
            state["agent_id"] = host.descriptor.agent_id

        if state.get("last_process_result") and hasattr(state["last_process_result"], "model_dump"):
            state["last_process_result"] = state["last_process_result"].model_dump(mode="json")

        state["active_agent_name"] = self.active_agent_name
        state["running_agents"] = running
        return state

    async def send_message(
        self,
        message_type: str,
        payload: Any,
        context_id: Optional[str] = None,
        task_id: Optional[str] = None,
        streaming: bool = False,
        agent_name: Optional[str] = None,
    ) -> str:
        """Sends a message to the target agent (or active agent if omitted)."""
        host = self.get_host(agent_name)
        if not host:
            raise RuntimeError(f"No running host found for agent '{agent_name or self.active_agent_name}'")
        return await host.send_message(
            message_type=message_type,
            payload=payload,
            context_id=context_id,
            task_id=task_id,
            streaming=streaming,
        )

    async def create_and_register_agent(
        self,
        agent_name: str,
        workspace_path: str,
        description: Optional[str] = None,
        system_prompt: Optional[str] = None,
        harness: str = "pi",
        model: str = "gemini-3.8-flash",
        provider: str = "google-vertex",
        thinking_level: str = "medium",
        capabilities: Optional[List[str]] = None,
        configuration: Optional[Dict[str, Any]] = None,
        configs_dir: Optional[str | Path] = None,
        persist_config: bool = True,
    ) -> URPHost:
        """
        Dynamically configures, registers, persists, and launches a new URP agent.
        1. Normalizes agent_name to underscore-separated identifier.
        2. Generates declarative config JSON and saves to configs/agents/<agent_name>.json.
        3. Registers in global AgentRegistry.
        4. Initializes URPHost, runs the agent, and exports A2A Card to <workspace>/.well_known/<agent_name>.json.
        """
        norm_name = normalize_agent_name(agent_name)
        abs_workspace = os.path.abspath(workspace_path)
        os.makedirs(abs_workspace, exist_ok=True)

        caps = list(capabilities or ["READ", "BASH", "EDIT", "WRITE", "SKILLS"])

        agent_config: Dict[str, Any] = {
            "provider": provider,
            "model": model,
            "thinking_level": thinking_level,
            "settlement_timeout": 600,
            "auto_compaction": True,
            "compaction": {
                "enabled": True,
                "reserveTokens": 16384,
                "keepRecentTokens": 20000,
            },
            "retry": {
                "enabled": True,
                "maxRetries": 3,
                "baseDelayMs": 2000,
            },
            "tools": ["read", "bash", "edit", "write"],
        }
        if system_prompt:
            agent_config["system_prompt"] = system_prompt
        if configuration:
            agent_config.update(configuration)

        manifest = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "name": norm_name,
            "descriptor": {
                "agent_id": norm_name,
                "name": norm_name,
                "version": "1.0.0",
                "description": description or f"Autonomous dynamic agent {norm_name}",
                "capabilities": caps,
                "accepted_message_types": ["MESSAGE", "TASK"],
            },
            "harness": harness,
            "configuration": agent_config,
        }

        # 1. Save declarative config in configs/agents/<agent_name>.json if requested
        if persist_config:
            target_configs_dir = Path(configs_dir) if configs_dir else Path(__file__).resolve().parent.parent.parent / "configs" / "agents"
            target_configs_dir.mkdir(parents=True, exist_ok=True)
            config_file = target_configs_dir / f"{norm_name}.json"
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
            logger.info(f"[AgentService] Saved dynamic agent manifest to {config_file}")

        # 2. Register into AgentRegistry
        name, factory_func, descriptor, default_config = build_agent_from_config(manifest)
        descriptor.metadata["default_configuration"] = default_config
        descriptor.metadata["harness"] = harness
        register_agent_if_absent(name=norm_name, factory_func=factory_func, descriptor=descriptor)

        # 3. Initialize and start host
        host = await self.initialize_agent(
            agent_type=norm_name,
            workspace_path=abs_workspace,
            configuration=agent_config,
            agent_name=norm_name,
        )
        return host

    async def shutdown(self, agent_name: Optional[str] = None) -> None:
        """
        Shuts down a specific agent host or all running hosts if agent_name is None.
        """
        if agent_name:
            norm_name = normalize_agent_name(agent_name)
            host = self.hosts.pop(norm_name, None) or self.hosts.pop(agent_name, None)
            if host:
                await host.shutdown()
                if self.active_agent_name == norm_name:
                    self.active_agent_name = next(iter(self.hosts.keys())) if self.hosts else None
        else:
            for name, host in list(self.hosts.items()):
                await host.shutdown()
            self.hosts.clear()
            self.active_agent_name = None
