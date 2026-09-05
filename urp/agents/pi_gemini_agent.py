import os
from pathlib import Path
from typing import Optional

from urp.core import AgentDescriptor, AgentContext
from urp.harnesses.pi import PiURPAgent

class PiGeminiAgent(PiURPAgent):
    """
    Dedicated URP Agent implementation powered by the Pi coding agent harness
    using Google Vertex Gemini 3.8 Flash with medium thinking effort.
    """

    def __init__(self, descriptor: Optional[AgentDescriptor] = None):
        if descriptor is None:
            descriptor = AgentDescriptor(
                agent_id="vhl.pi.gemini.v1",
                name="Pi Gemini Coding Agent",
                version="1.0.0",
                description="Autonomous coding agent using Google Vertex Gemini 3.8 Flash with medium thinking effort.",
                capabilities=["READ", "BASH", "EDIT", "WRITE", "SKILLS"],
                accepted_message_types=["MESSAGE", "TASK"],
            )
        super().__init__(descriptor)

    def _on_initialize(self, context: AgentContext) -> None:
        """Sets default model to gemini-3.8-flash, provider to google-vertex, and thinking to medium."""
        config = getattr(context, "configuration", {}) or {}

        # Set defaults if not explicitly overridden in context
        config.setdefault("provider", os.getenv("LLM_PROVIDER", "google-vertex"))
        config.setdefault("model", os.getenv("LLM_MODEL", "gemini-3.8-flash"))
        config.setdefault("thinking_level", "medium")
        config.setdefault("settlement_timeout", 600.0)

        super()._on_initialize(context)
