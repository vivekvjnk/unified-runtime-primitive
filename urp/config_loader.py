"""
Agent Configuration Loader
==========================

Loads and registers URP agents from structured JSON configuration files.
Enables runtime model selection, thinking levels, context compaction parameters,
and custom tool allowlists without hardcoding settings into Python source files.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from .abstract_urp import AbstractURPAgent
from .agent_registry import register_agent, register_agent_if_absent
from .data_types import AgentDescriptor
from .sample_agent import EchoAgent
from .sdk_agent import SDKURPAgent
from .pi_harness import PiURPAgent

logger = logging.getLogger("urp.config_loader")

HARNESS_MAP: Dict[str, Type[AbstractURPAgent]] = {
    "echo": EchoAgent,
    "sdk": SDKURPAgent,
    "pi": PiURPAgent,
    "pi_harness": PiURPAgent,
}


def load_agent_config_from_file(config_path: Path | str) -> Dict[str, Any]:
    """Loads a raw agent JSON configuration file."""
    path = Path(config_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Agent config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_agent_from_config(config: Dict[str, Any]) -> Tuple[str, Callable[..., AbstractURPAgent], AgentDescriptor, Dict[str, Any]]:
    """
    Parses an agent JSON configuration dictionary into:
      - name: Identifier for AgentRegistry
      - factory_func: Factory callable instantiating the agent
      - descriptor: Validated AgentDescriptor
      - default_configuration: Dict containing default model, thinking, compaction, etc.
    """
    name = config.get("name")
    if not name:
        raise ValueError("Agent configuration missing required 'name' field")

    raw_desc = config.get("descriptor") or {}
    descriptor = AgentDescriptor(
        agent_id=raw_desc.get("agent_id") or f"agent.{name}.v1",
        name=raw_desc.get("name") or name.title(),
        version=raw_desc.get("version") or "1.0.0",
        description=raw_desc.get("description") or "",
        capabilities=raw_desc.get("capabilities") or [],
        accepted_message_types=raw_desc.get("accepted_message_types") or ["MESSAGE"],
        metadata=raw_desc.get("metadata") or {},
    )

    harness_type = (config.get("harness") or "echo").lower()
    agent_cls = HARNESS_MAP.get(harness_type)
    if not agent_cls:
        available = ", ".join(HARNESS_MAP.keys())
        raise ValueError(f"Unknown harness type '{harness_type}'. Available: {available}")

    default_config = config.get("configuration") or {}

    def factory_func(desc: Optional[AgentDescriptor] = None, **kwargs) -> AbstractURPAgent:
        active_desc = desc or descriptor
        return agent_cls(descriptor=active_desc)

    return name, factory_func, descriptor, default_config


def register_agent_from_file(config_path: Path | str) -> str:
    """Loads a JSON configuration file and registers it in the global AgentRegistry."""
    config_dict = load_agent_config_from_file(config_path)
    name, factory_func, descriptor, default_config = build_agent_from_config(config_dict)

    # Store default configuration inside descriptor metadata for host inspection
    descriptor.metadata["default_configuration"] = default_config
    descriptor.metadata["harness"] = config_dict.get("harness", "echo")

    register_agent_if_absent(
        name=name,
        factory_func=factory_func,
        descriptor=descriptor,
    )
    logger.info(f"[ConfigLoader] Successfully registered agent '{name}' from {config_path}")
    return name


def load_all_agent_configs(configs_dir: Optional[Path | str] = None) -> List[str]:
    """
    Scans a directory for *.json agent configuration files and registers them.
    Defaults to the project root 'configs/agents' folder.
    """
    if configs_dir is None:
        project_root = Path(__file__).resolve().parent.parent
        configs_dir = project_root / "configs" / "agents"

    target_dir = Path(configs_dir).resolve()
    registered_names = []

    if not target_dir.exists():
        logger.warning(f"[ConfigLoader] Agent configuration directory does not exist: {target_dir}")
        return registered_names

    for file_path in sorted(target_dir.glob("*.json")):
        try:
            name = register_agent_from_file(file_path)
            registered_names.append(name)
        except Exception as e:
            logger.error(f"[ConfigLoader] Failed to load agent config from {file_path}: {e}", exc_info=True)

    return registered_names
