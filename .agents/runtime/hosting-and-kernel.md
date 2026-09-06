# Runtime: Hosting & Kernel (`URPHost` & Web Server)

This document describes the host runtime kernel (`urp.host.URPHost`), the independent hosting framework, and the FastAPI/WebSocket server (`urp.web_server`).

---

## 1. The `URPHost` Runtime Kernel

`URPHost` is the reference execution container managing an individual agent instance:

```
┌─────────────────────────────────────────────────────────────────┐
│                            URPHost                              │
│                                                                 │
│  ┌──────────────────────┐            ┌──────────────────────┐   │
│  │     Agent Class      │            │   AgentDescriptor    │   │
│  └──────────┬───────────┘            └──────────┬───────────┘   │
│             │                                   │               │
│             ▼                                   ▼               │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │             Instantiated AbstractURPAgent                 │  │
│  │                                                           │  │
│  │  Mailbox: asyncio.Queue <─── send_message()               │  │
│  │  Emissions              ───► event_queue & emit_callback  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Core Responsibilities

1. **Instantiation & Binding:** Instantiates the agent class and binds its output callback to the host's internal `event_queue`.
2. **Lifecycle Management:** Coordinates `initialize()` with injected `AgentContext`, invokes `start()`, and drives graceful `shutdown()`.
3. **Mailbox Dispatching:** Formats incoming data into valid `MessageEnvelope` objects and queues them asynchronously via `send_message()`.
4. **Event Streaming:** Buffers all emitted events in an `asyncio.Queue` accessible via `get_next_event(timeout)`.

---

## 2. Web Server & Console Architecture (`urp.web` & `urp.a2a`)

`urp.web` provides a modular FastAPI service with native Agent2Agent (A2A) protocol endpoints and an interactive web console.

### Module Structure
```
urp/web/
├── __init__.py           # Package exports (app, create_app, AgentHostingService)
├── app.py                # FastAPI factory, lifespan context manager, static files mount
├── routes.py             # Console and filesystem picker route handlers
├── schemas.py            # Pydantic request models
├── agent_service.py      # Host lifecycle and registry coordination service
├── workspace_service.py  # Session persistence and directory browser helpers
├── static/
│   ├── css/style.css     # Modernized dark theme, collapsible cards, responsive layout
│   └── js/app.js         # Modular client logic, A2A SSE stream consumer, sidebar toggle
└── templates/
    └── index.html        # Clean semantic HTML5 dashboard with foldable sidebar
```

### Protocol & Web Endpoints

| Route | Method | Protocol | Purpose |
|---|---|---|---|
| `/.well-known/agent.json` | `GET` | **A2A** | Discovers active agent card (name, description, capabilities, skills, endpoints). |
| `/a2a/v1/agents` | `GET` | **A2A** | Lists catalog of all available agent cards on this host. |
| `/message:send` | `POST` | **A2A** | Synchronous message dispatch returning completed `Task` snapshot. |
| `/message:stream` | `POST` | **A2A** | Real-time Server-Sent Events (SSE) stream delivering in-flight tokens, tool executions, and completion. |
| `/tasks/{task_id}` | `GET` | **A2A** | Queries current task status, history, and output artifacts. |
| `/tasks` | `GET` | **A2A** | Lists tasks with optional context and status filtering. |
| `/tasks/{task_id}:cancel`| `POST` | **A2A** | Cancels a running task. |
| `/tasks/{task_id}:subscribe` | `GET` | **A2A** | Re-attaches an SSE stream to an ongoing task. |
| `/` | `GET` | UI | Serves the reference A2A WebHMI dashboard. |
| `/agent/types` | `GET` | Console | Lists registered agent types. |
| `/agent/init` | `POST` | Console | Deploys an agent instance. |
| `/agent/state` | `GET` | Console | Telemetry snapshot (`status`, `active_conversation_id`, `mailbox_size`). |
| `/agent/browse` | `GET` | Console | Directory browser modal for selecting workspace directories. |

---

## 3. Running the Host Server

Launch the web console using the repository entrypoint:

```bash
python run_host.py
```

Console URL: `http://localhost:8000`
