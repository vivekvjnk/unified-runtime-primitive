
import os
import sys
from pathlib import Path

from pydantic import SecretStr

from openhands.sdk import LLM, Agent, AgentContext, Conversation
from openhands.sdk.skills import (
    discover_skill_resources,
    load_skills_from_dir,
)
from openhands.sdk.context.condenser import LLMSummarizingCondenser
from openhands.sdk.tool import Tool
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.terminal import TerminalTool

agent_workspace = Path("/home/vivekv/Documents/three-wise-monkeys/crazy_orca/Use-case/bms/module-integration-dry-run/bms-project_e0505ca9/bms-project_e0505ca9_root")

skills_dir = agent_workspace / ".agents/skills"
resources = discover_skill_resources(skills_dir / "circuit-integration-architect")
print("\nDiscovered resources in rot13-encryption/:")
print(f"  - scripts: {resources.scripts}")
print(f"  - references: {resources.references}")
print(f"  - assets: {resources.assets}")

repo_skills, knowledge_skills, agent_skills = load_skills_from_dir(skills_dir)




# Check for API key
api_key = os.getenv("LLM_API_KEY")
if not api_key:
    print("Skipping agent demo (LLM_API_KEY not set)")
    print("\nTo run the full demo, set the LLM_API_KEY environment variable:")
    print("  export LLM_API_KEY=your-api-key")
    sys.exit(0)

# Configure LLM
model = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4-5-20250929")
llm = LLM(
    usage_id="skills-demo",
    model=model,
    api_key=SecretStr(api_key),
    base_url=os.getenv("LLM_BASE_URL"),
)

condenser = LLMSummarizingCondenser(
    llm=llm.model_copy(update={"usage_id": "condenser"}), max_size=100, keep_first=6
)

# Create agent context with loaded skills
agent_context = AgentContext(
    skills=list(agent_skills.values()),
    # Disable public skills for this demo to keep output focused
    load_public_skills=False,
    condenser=condenser
)

# Create agent with tools so it can read skill resources
tools = [
    Tool(name=TerminalTool.name),
    Tool(name=FileEditorTool.name),
]
agent = Agent(llm=llm, tools=tools, agent_context=agent_context)

persistence_dir = "./.conversations"
# Create conversation
conversation = Conversation(agent=agent, workspace=agent_workspace, persistence_dir=persistence_dir)


# conversation.send_message("Read system-boundary.md, microcontroller-module/Workspace/resources/microcontroller-module-boundary.md, microcontroller-module/Workspace/microcontroller-module.scud, microcontroller-module/Workspace/microcontroller-module.tsx, low-voltage-power-supply/Workspace/resources/low-voltage-power-supply-boundary.md, low-voltage-power-supply/Workspace/low-voltage-power-supply.scud, low-voltage-power-supply/Workspace/low-voltage-power-supply.tsx. Control circuit consists of these two modules." \
# "Your task is to construct scud document for the control-circuit. control-circuit should integrate micrcocontroller-module and low-voltage-power-supply module by connecting each other through the right set of ports. SCUD document should focus on module integration rather than ASIC level synthesis." \
# "Please prepare scud document for the control-circuit, name it control-circuit.scud and save it under current workspace")

conversation.send_message("Read system-boundary.md, bms-monitor-module/Workspace/resources/bms-monitor-module-boundary.md, bms-monitor-module/Workspace/bms-monitor-module.scud, bms-monitor-module/Workspace/bms-monitor-module.tsx, high-voltage-power-supply/Workspace/resources/high-voltage-power-supply-boundary.md, high-voltage-power-supply/Workspace/high-voltage-power-supply.scud, high-voltage-power-supply/Workspace/high-voltage-power-supply.tsx. communication-bridge/Workspace/resources/communication-bridge-boundary.md, communication-bridge/Workspace/communication-bridge.scud, communication-bridge/Workspace/communication-bridge.tsx, current-sensing/Workspace/resources/current-sensing-boundary.md, current-sensing/Workspace/current-sensing.scud, current-sensing/Workspace/current-sensing.tsx," \
"Power circuit consists of these 4 modules." \
"Your task is to construct scud document for the power-circuit. power-circuit should integrate bms-monitor-module, communication-bridge, current-sensing and high-voltage-power-supply module by connecting each other through the right set of ports. SCUD document should focus on module integration rather than ASIC level synthesis." \
"Please prepare scud document for the power-circuit, name it power-circuit.scud and save it under current workspace")
conversation.run()

