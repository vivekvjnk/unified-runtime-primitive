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

## 2. Web Server & Console Architecture (`urp.web`)

`urp.web` provides a modular FastAPI and WebSocket service for testing, inspecting, and operating URP agents interactively.

### Module Structure
```
urp/web/
├── __init__.py           # Package exports (app, create_app, AgentHostingService)
├── app.py                # FastAPI factory and lifespan context manager
├── routes.py             # HTTP and WebSocket route handlers
├── schemas.py            # Pydantic request models
├── agent_service.py      # Host lifecycle and registry coordination service
├── workspace_service.py  # Session persistence and directory browser helpers
└── templates/
    └── index.html        # Interactive dark-theme dashboard with marked.js
```

### Endpoints

| Route | Method | Purpose |
|---|---|---|
| `/` | `GET` | Interactive browser-based testing console with markdown & event timeline rendering. |
| `/agent/types` | `GET` | Lists all registered agent types discovered via `AgentRegistry`. |
| `/agent/init` | `POST` | Initializes and starts an agent instance dynamically resolved via `AgentRegistry`. |
| `/agent/message` | `POST` | Ingests a new message into the active agent mailbox with optional `context_id` and `task_id`. |
| `/agent/state` | `GET` | Returns current serialized state (`status`, `session_id`, `mailbox_size`, `last_process_result`, `agent_name`). |
| `/agent/conversations` | `GET` | Lists persistent conversation sessions saved in `.conversation/conversation_map.json`. |
| `/agent/conversations/history` | `GET` | Reconstructs historical user/agent conversation events from workspace. |
| `/agent/conversations/save` | `POST` | Persists the active conversation ID under a human-readable name. |
| `/agent/browse` | `GET` | Directory browser endpoint for selecting workspace paths from the web UI. |
| `/ws` | `WebSocket` | Real-time event stream broadcasting agent lifecycle and output envelopes to UI. |

---

## 3. Running the Host Server

Launch the web console using the repository entrypoint:

```bash
python run_host.py
```

Console URL: `http://localhost:8000`
