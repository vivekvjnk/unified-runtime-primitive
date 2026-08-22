import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from urp.pi_harness.pi_urp_agent import PiURPAgent
from urp.data_types import AgentContext, AgentDescriptor
import logging

from .utils import (
    LayoutEngineerConfig,
    get_default_skills_dir,
    load_system_prompt_template,
)

logger = logging.getLogger("urp.layout_engineer_agent")


class LayoutEngineerURPAgent(PiURPAgent):
    """
    PCB Layout Engineer Agent powered by the Pi URP Harness.

    Orchestrates and executes component placement, netlist analysis,
    and PCB layout optimization.
    """

    def __init__(self, descriptor: Optional[AgentDescriptor] = None):
        if descriptor is None:
            descriptor = AgentDescriptor(
                agent_id="vhl.layout_engineer.v1",
                name="Layout Engineer Agent",
                version="1.0.0",
                capabilities=["pcb_placement", "layout_optimization", "netlist_analysis"],
                accepted_message_types=["LAYOUT_PLACEMENT_TASK", "TASK"],
            )
        super().__init__(descriptor)

    def _on_initialize(self, context: AgentContext) -> None:
        """URP Initialization Hook: Sets up system prompt and .agents skill paths."""
        logger.info(f"[{self.descriptor.agent_id}] Initializing LayoutEngineerURPAgent...")

        raw_config = getattr(context, "configuration", {}) or {}

        # 1. Resolve workspace path
        workspace_dir = (
            raw_config.get("workspace_dir")
            or getattr(context, "workspace_path", None)
            or os.getcwd()
        )
        workspace_path = Path(workspace_dir).resolve()

        # 2. Discover .agents skills directories
        skill_paths: List[Path] = []

        # Local agent skills directory (layout_engineer/.agents)
        default_agent_skills = get_default_skills_dir()
        if default_agent_skills.exists():
            skill_paths.append(default_agent_skills)

        # Workspace skills directory (workspace/.agents)
        workspace_skills = workspace_path / ".agents"
        if workspace_skills.exists():
            skill_paths.append(workspace_skills)

        # Custom skill dirs from config
        custom_skill_dirs = raw_config.get("skill_dirs", [])
        for cdir in custom_skill_dirs:
            p = Path(cdir).resolve()
            if p.exists() and p not in skill_paths:
                skill_paths.append(p)

        # 3. Build extra_args for Pi CLI skill discovery
        extra_args = list(raw_config.get("extra_args") or [])
        for spath in skill_paths:
            extra_args.extend(["--skill", str(spath)])

        # 4. Load system prompt template
        system_prompt = load_system_prompt_template()

        # Merge updated configuration for PiURPAgent
        merged_config = dict(raw_config)
        merged_config.update({
            "workspace_dir": str(workspace_path),
            "system_prompt": system_prompt,
            "extra_args": extra_args,
            "settlement_timeout": raw_config.get("settlement_timeout", 600.0),
        })

        # Inject updated configuration into context
        context.configuration = merged_config

        # Delegate initialization to PiURPAgent base class
        super()._on_initialize(context)
        logger.info(f"[{self.descriptor.agent_id}] LayoutEngineerURPAgent context initialized with {len(skill_paths)} skill path(s).")
