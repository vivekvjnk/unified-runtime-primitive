import json
import pytest
from pathlib import Path

from urp.config_loader import (
    load_agent_config_from_file,
    build_agent_from_config,
    register_agent_from_file,
    load_all_agent_configs,
)
from urp.agent_registry import get_agent_factory, create_agent
from urp.pi_harness import PiURPAgent
from urp.data_types import AgentContext

def test_load_pi_agent_config():
    config_path = Path("configs/agents/pi_agent.json")
    assert config_path.exists()

    config = load_agent_config_from_file(config_path)
    assert config["name"] == "pi_agent"
    assert config["harness"] == "pi"
    assert config["configuration"]["model"] == "claude-sonnet"
    assert config["configuration"]["thinking_level"] == "medium"
    assert config["configuration"]["compaction"]["enabled"] is True

def test_build_agent_from_config():
    sample_config = {
        "name": "custom_pi",
        "harness": "pi",
        "descriptor": {
            "agent_id": "custom.pi.v1",
            "name": "Custom Pi Agent",
            "capabilities": ["BASH", "READ"]
        },
        "configuration": {
            "model": "gpt-5-preview",
            "thinking_level": "high",
            "settlement_timeout": 300
        }
    }
    name, factory_func, descriptor, default_cfg = build_agent_from_config(sample_config)
    assert name == "custom_pi"
    assert descriptor.agent_id == "custom.pi.v1"
    assert default_cfg["model"] == "gpt-5-preview"
    assert default_cfg["thinking_level"] == "high"

    # Instantiate
    agent = factory_func()
    assert isinstance(agent, PiURPAgent)
    assert agent.descriptor.name == "Custom Pi Agent"

def test_load_all_agent_configs():
    registered = load_all_agent_configs("configs/agents")
    assert "pi_agent" in registered
    assert "echo" in registered
    assert "sdk" in registered

    # Verify factory in registry
    factory = get_agent_factory("pi_agent")
    assert factory.descriptor.agent_id == "vhl.pi.v1"
    assert factory.descriptor.metadata["default_configuration"]["thinking_level"] == "medium"
    assert factory.descriptor.metadata["default_configuration"]["model"] == "claude-sonnet"
