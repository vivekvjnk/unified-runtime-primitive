import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class LayoutEngineerConfig:
    """Configuration parameters for LayoutEngineerURPAgent."""
    skill_dirs: List[str] = field(default_factory=list)
    system_prompt_template: str = "layout_engineer_prompt.j2"
    settlement_timeout: float = 600.0  # 10 minutes default for layout placement workflows


@dataclass
class LayoutEngineerContext:
    """Context container for LayoutEngineerURPAgent."""
    workspace_dir: str
    config: LayoutEngineerConfig = field(default_factory=LayoutEngineerConfig)


def get_layout_engineer_dir() -> Path:
    """Returns absolute path to the layout_engineer root folder."""
    return Path(__file__).resolve().parent.parent


def get_default_skills_dir() -> Path:
    """Returns path to layout_engineer/.agents skills directory."""
    return get_layout_engineer_dir() / ".agents"


def get_default_prompt_path() -> Path:
    """Returns path to the layout_engineer_prompt.j2 template."""
    return Path(__file__).resolve().parent / "prompts" / "layout_engineer_prompt.j2"


def load_system_prompt_template(prompt_path: Optional[Path] = None) -> str:
    """Loads system prompt template content from disk."""
    path = prompt_path or get_default_prompt_path()
    if path.exists():
        return path.read_text(encoding="utf-8")
    return (
        "You are an expert PCB Layout Engineer agent responsible for component placement, "
        "netlist analysis, and layout optimization."
    )
