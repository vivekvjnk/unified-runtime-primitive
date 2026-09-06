# 07: Phase 7 — Dynamic URP Agent Authoring, Multi-Agent A2A Collaboration & `tiny-agent` Milestone

> **Status:** Active Engineering Plan  
> **Target Subsystems:** `urp.web`, `urp.a2a`, `urp.core`, `configs/agents/`  
> **Protocol Reference:** Agent2Agent (A2A) Open Protocol Specification & URP Lifecycle Contract  
> **Target Real-World Project:** `/home/vivekv/Documents/tiny-agent`

---

## 1. Executive Summary & Architectural Positioning

In Phase 7, we evolve URP-HF (Unified Runtime Primitive Independent Hosting Framework) from a single-agent host into a **multi-agent A2A runtime container and authoring environment**.

### Core Objectives
1. **Dynamic URP Agent Authoring via URP-HF WebHMI:**
   - Transport-agnostic agent creation interface in the WebUI.
   - Allows users to specify agent identity, system prompt, toolsets, and inject **ECP (Engineering Capability Package)** packages (directories or zip archives containing `SKILL.md`, tools, and references).
   - Generates persistent, declarative agent definitions (`configs/agents/<agent_name>.json` + workspace skills) without modifying Python code.
2. **Multi-Agent Runtime & Dynamic Conversation Switching:**
   - Host concurrently runs and addresses multiple agents, each with its own state machine, workspace, and self-describing A2A Agent Card.
   - WebHMI provides seamless runtime switching between agents and conversational threads (`context_id`).
3. **Inter-Agent A2A Communication (Peer Dialing):**
   - Both agents know each other through standard A2A discovery (`/a2a/v1/agents` or remote URL).
   - Agents possess an outbound A2A communication capability (`a2a_send_message` / `a2a_delegate`) enabling collaborative peer-to-peer delegation.
4. **Execution of Real-World Milestone (`tiny-agent`):**
   - **Agent 1 (Infrastructure Agent):** Equipped with Yocto/Docker build tooling, container execution, and environment validation.
   - **Agent 2 (Development Agent):** Specialized in C systems programming, PTY orchestration, and BashAct interaction runtime (`tiny-agent/src/pty.c`).
   - Collaboratively achieve a concrete milestone in `/home/vivekv/Documents/tiny-agent`.

---

## 2. Technical Architecture & System Flow

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             URP-HF WebHMI (Frontend)                            │
│  ┌───────────────────────┐  ┌──────────────────────┐  ┌───────────────────────┐  │
│  │ Agent Authoring Modal │  │ Agent Switcher Tab   │  │ Real-time Chat/Stream │  │
│  │ (Name, Prompt, ECP)   │  │ [Infra] [Dev] [+]    │  │ (Context / Task IDs)  │  │
│  └───────────┬───────────┘  └──────────┬───────────┘  └───────────┬───────────┘  │
└──────────────┼─────────────────────────┼──────────────────────────┼──────────────┘
               │ POST /agent/create      │ Switch Active Agent      │ POST /message:stream
               ▼                         ▼                          ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            A2A Protocol & Router Layer                           │
│  - GET /.well-known/agent.json (current context agent)                           │
│  - GET /a2a/v1/agents          (all live agent cards)                            │
│  - POST /message:send & stream (addressed via target agent ID or context)        │
│  - POST /agent/create          (URP creation extension endpoint)                 │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                   URP Multi-Agent Hosting Engine (agent_service)                 │
│                                                                                  │
│   ┌────────────────────────────────┐     ┌────────────────────────────────┐      │
│   │   URPHost: "infra_agent"       │     │    URPHost: "dev_agent"        │      │
│   │   - Card: InfraOps Specialist  │     │    - Card: Systems C Developer │      │
│   │   - ECP: yocto-docker-ecp      │     │    - ECP: pty-systems-ecp      │      │
│   │   - Outbound A2A Peer Dialing  │◄───►│    - Outbound A2A Peer Dialing │      │
│   └────────────────────────────────┘     └────────────────────────────────┘      │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
                                         ▼
                 Target Workspace: `/home/vivekv/Documents/tiny-agent`
```

---

## 3. Detailed Phased Implementation Steps

### Phase 7.1: Multi-Agent Hosting Architecture & Persistence
**Goal:** Extend `AgentHostingService` to support multiple concurrent running `URPHost` instances instead of a single active singleton.

1. **Multi-Host Management in `urp/web/agent_service.py`:**
   - Replace single `self.host: Optional[URPHost]` with:
     ```python
     self.hosts: Dict[str, URPHost] = {}
     self.active_agent_id: Optional[str] = None
     ```
   - Provide `get_host(agent_id: Optional[str] = None) -> URPHost`.
   - Update `send_message`, `get_state`, and `shutdown` to route requests to the targeted agent or active agent.
2. **A2A Multi-Agent Addressing in `urp/a2a/router.py`:**
   - Update `POST /message:send` and `POST /message:stream` to accept target agent identification (via header `X-Target-Agent`, query param `?agent_id=...`, or body field `target_agent_id`).
   - If not specified, default to currently active selected agent.
   - Ensure `GET /a2a/v1/agents` dynamically returns `AgentCard` models for all loaded hosts.

---

### Phase 7.2: Transport-Agnostic Agent Authoring Endpoint & ECP Extraction
**Goal:** Expose an API endpoint and backend handler to configure and spin up a new agent entirely at runtime from parameters and uploaded packages.

1. **Schema & Endpoint (`urp/web/schemas.py` & `urp/web/routes.py`):**
   - Add endpoint `POST /agent/create`:
     - Accepts `multipart/form-data`:
       - `agent_id`: string (e.g. `tiny_infra_agent`)
       - `name`: string (e.g. `TinyAgent Infrastructure Specialist`)
       - `description`: string
       - `system_prompt`: string (custom behavioral instructions)
       - `model_name`: string (e.g. `gemini-3.8-flash` via Vertex)
       - `thinking_level`: string (`medium`, `high`, `off`)
       - `workspace_path`: string (e.g. `/home/vivekv/Documents/tiny-agent`)
       - `ecp_archive`: optional file upload (`.zip`) or `ecp_directory` path.
2. **ECP (Engineering Capability Package) Processor:**
   - If a zip file or ECP directory is provided:
     - Unpack/copy into `<agent_workspace>/.agents/skills/<package_name>/`.
     - Validate that `SKILL.md` exists and contains standard YAML frontmatter (`name`, `description`).
     - Symlink or inject tools into the agent's executable search path or Pi harness extensions.
3. **Declarative Config Persistence:**
   - Automatically save the new agent config as `configs/agents/<agent_id>.json`.
   - Register the factory in `AgentRegistry` and immediately initialize its `URPHost` instance.

---

### Phase 7.3: WebHMI Multi-Agent Workspace & Creation UI
**Goal:** Modernize the frontend to allow dynamic creation and runtime switching.

1. **Agent Creation Modal (`urp/web/templates/index.html` & `static/js/app.js`):**
   - Add a `+ New Agent` button in the sidebar header.
   - Modal form:
     - Basic Info: Agent ID, Name, Version, Description.
     - Model & Engine: Engine selector (`Pi Gemini`, `Echo`, `SDK`), thinking budget.
     - Prompts & Instructions: Rich textarea for System Prompt.
     - Capability / ECP Upload: File drag-and-drop for `.zip` ECP or path browser for local ECP folder.
     - Target Workspace path with directory picker.
2. **Agent Switching Tab Bar:**
   - Top bar / header displays active agents as selectable pills/tabs (e.g., `[ ⚙️ Infra Agent ] [ 💻 Dev Agent ]`).
   - Switching agents instantly updates the active conversation view, active Agent Card metadata, and telemetry without reloading the page.
   - Maintain isolated turn histories and context IDs per agent.

---

### Phase 7.4: Inter-Agent A2A Peer Dialing (Collaborative Calling)
**Goal:** Enable both agents to discover and call each other over A2A.

1. **A2A Client Tool for URP Harnesses (`urp/a2a/client.py` or Pi Skill/Tool):**
   - Create a lightweight A2A peer tool:
     ```python
     async def a2a_call_peer(agent_id_or_url: str, message: str, context_id: Optional[str] = None) -> str:
         """Dispatches a task turn to a peer A2A agent and returns its output."""
     ```
   - When running under URP-HF, `a2a_call_peer` can talk directly to localhost `POST /message:send` (or in-memory via `AgentHostingService`).
   - Register this tool / skill so both agents can delegate sub-tasks to each other.
2. **Mutual Agent Awareness:**
   - During agent initialization, inject the roster of peer agents into the system prompt:
     - *"You are part of an A2A agent network. Available peers: `tiny_infra_agent` (Docker, Yocto, system builds), `tiny_dev_agent` (C systems programming, PTY, BashAct). You can contact them using the A2A call tool."*

---

### Phase 7.5: Practical Milestone Execution on `tiny-agent`
**Goal:** Validate the multi-agent setup on `/home/vivekv/Documents/tiny-agent`.

1. **Formulate the Milestone:**
   - **Target:** Validate the PTY Orchestration & Terminal Interaction loop in `tiny-agent/src/pty.c`.
   - **Milestone Scope:**
     - Step 1: Infra Agent prepares the Docker build container (`poky-dev` or native gcc build environment), verifies compiler tools and dependencies, and validates the build scripts.
     - Step 2: Dev Agent reviews and enhances `tiny-agent/src/pty.c` to test the BashAct runtime primitive (spawning child shell, master/slave fd handling, non-blocking I/O).
     - Step 3: Infra Agent executes the compilation (`make` or docker container compile) and runs the test harness.
     - Step 4: Agents exchange status via A2A, report results, and confirm milestone completion.
2. **Agent Packaging:**
   - Package 1: **Infra ECP** (`yocto-docker-ops`):
     - `SKILL.md`: Operational instructions for `yocto-setup.sh`, Docker builds, bitbake commands, container debugging.
   - Package 2: **Dev ECP** (`pty-systems-dev`):
     - `SKILL.md`: C POSIX terminal programming (`forkpty`, `termios`, ANSI escape sequences, signal handling).

---

## 4. Verification and Validation Checklist

- [ ] **Dynamic Authoring:** Create `tiny_infra_agent` and `tiny_dev_agent` entirely through the WebHMI without manual file edits or restart.
- [ ] **ECP Ingestion:** Upload/link ECPs via WebUI and verify they are correctly mounted in the agents' skill systems.
- [ ] **Multi-Agent Runtime:** Both agents appear in `GET /a2a/v1/agents` with their respective `AgentCard` schemas.
- [ ] **WebHMI Switching:** Toggle between both agents in the UI; message streams remain isolated and responsive.
- [ ] **Peer Collaboration:** Dev Agent asks Infra Agent to run a build/test via A2A, and Infra Agent responds with stdout/stderr.
- [ ] **Milestone Delivery:** Successful compilation and verification of the `tiny-agent` PTY interaction test.
