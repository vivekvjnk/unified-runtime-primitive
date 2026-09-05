# 04 — VHL Agents Migration Guide: Upgrading to Streamlined URP & A2A

> **Study Series:** A2A Protocol Integration & URP Feasibility Study  
> **Target Scope:** Migration Recipes for `ArchyURPAgent`, `AnaURPAgent`, and `LibrarianURPAgent` in `VHL-System`  
> **Status:** Completed Phase 4 Exploration & Migration Specification

---

## 1. Overview & Architectural Motivation

With the removal of the out-of-band outcome acknowledgment mechanism and the introduction of streamlined A2A-aligned data structures in `urp-core`, this guide documents the exact delta and step-by-step recipe for upgrading existing VHL agents (**Archy**, **ANA**, and **Librarian**) to the new standard.

### Core Enhancements Summary:
1. **Simplified Return Payloads:** Return `ProcessResult(outcome=..., text=response, artifacts=[...])` directly instead of wrapping in `ProcessResultPayload(text=response)`.
2. **First-Class A2A Anchors:** Utilize `message.context_id` and `message.task_id` directly from `MessageEnvelope` instead of parsing them from nested payload dictionaries or generating artificial UUIDs.
3. **Flexible AgentContext:** Pass domain dependencies directly through `AgentContext` or domain subclasses without fighting rigid schema constraints.
4. **AgentCard Export:** Utilize `descriptor.to_agent_card()` for A2A discovery.

---

## 2. Migration Recipe for `ArchyURPAgent`

### 2.1 Delta in `process()` Return Value

#### Before (Legacy `vhl_common.urp`):
```python
# Legacy Archy process() return:
payload = ProcessResultPayload(text=response)
return ProcessResult(outcome=process_outcome, payload=payload)
```

#### After (Streamlined `urp-core`):
```python
# Streamlined Archy process() return:
# Directly include produced SCUD document as an artifact!
scud_file_name = f"{self.module_name}.scud"
artifacts = []
if (self.agent_workspace_path / scud_file_name).exists():
    artifacts.append({
        "name": "SCUD_DOCUMENT",
        "filename": scud_file_name,
        "path": str(self.agent_workspace_path / scud_file_name)
    })

return ProcessResult(
    outcome=process_outcome,
    text=response,
    artifacts=artifacts
)
```

### 2.2 Delta in `MessageEnvelope` Ingestion

#### Before:
```python
# Archy extracting user text from nested dict
user_msg = message.payload["text"]
```

#### After (Native A2A Routing):
```python
# Context ID & Task ID are directly accessible on message:
session_id = message.context_id or str(self.conversation.state.id)
task_id = message.task_id

# User text extraction:
user_msg = message.payload.get("text", "") if isinstance(message.payload, dict) else str(message.payload)
```

---

## 3. Migration Recipe for `AnaURPAgent`

### 3.1 Delta in `process()` Return Value & Artifact Publishing

#### Before:
```python
# Legacy ANA process() return:
payload = ProcessResultPayload(text=response_text)
return ProcessResult(outcome=process_outcome, payload=payload)
```

#### After:
```python
# Streamlined ANA process() return:
artifacts = []
circuit_file = self.agent_workspace_path / "index.circuit.tsx"
if circuit_file.exists():
    artifacts.append({
        "name": "CIRCUIT_TSX",
        "filename": "index.circuit.tsx",
        "path": str(circuit_file)
    })

return ProcessResult(
    outcome=process_outcome,
    text=response_text,
    artifacts=artifacts
)
```

---

## 4. Migration Recipe for `LibrarianURPAgent`

### 4.1 Delta in `process()` Return Value

#### Before:
```python
# Legacy Librarian process() return:
payload = ProcessResultPayload(text=response)
return ProcessResult(outcome=process_outcome, payload=payload)
```

#### After:
```python
# Streamlined Librarian process() return:
return ProcessResult(
    outcome=process_outcome,
    text=response,
    artifacts=[{
        "name": "RESOLVED_SCUD",
        "path": str(self.scud_path)
    }] if self.scud_path else []
)
```

---

## 5. Architectural Directory Reorganization & Import Changes

As part of the clean separation of concerns, `urp-core` has eliminated flat root pollution and removed legacy backward-compatibility bridges. All imports have moved to dedicated sub-packages:

### Import Mapping Matrix:

| Legacy Import Path | New Standard Import Path in `urp-core` |
|---|---|
| `from urp.data_types import ...` | `from urp.core import ...` (or `from urp.core.data_types import ...`) |
| `from urp.abstract_urp import ...` | `from urp.core import AbstractURPAgent, ...` (or `from urp.core.abstract_urp import ...`) |
| `from urp.agent_key import ...` | `from urp.core import AgentKey, AgentReadiness, AgentHandle` |
| `from urp.agent_registry import ...` | `from urp.core import AgentRegistry, register_agent, create_agent` |
| `from urp.host import URPHost` | `from urp.core import URPHost` |
| `from urp.sdk_agent import SDKURPAgent` | `from urp.harnesses.openhands import SDKURPAgent` |
| `from urp.pi_harness import PiURPAgent` | `from urp.harnesses.pi import PiURPAgent, PiRpcClient` |
| `from urp.sample_agent import EchoAgent` | `from urp.agents import EchoAgent` |
| `from urp.web_server import app` | `from urp.web import app` |

*Note: For convenience, all public symbols are also directly importable from the top-level package:*  
`from urp import AbstractURPAgent, AgentDescriptor, MessageEnvelope, ProcessResult, PiURPAgent, SDKURPAgent, URPHost`

---

## 6. Verification Checklist for VHL Agents Migration

- [ ] Update `vhl_common/urp/` imports to point to `urp.core` instead of legacy flat paths.
- [ ] In `ArchyURPAgent.process()`, update `ProcessResult` to use `text=` and `artifacts=`.
- [ ] In `AnaURPAgent.process()`, update `ProcessResult` to use `text=` and `artifacts=`.
- [ ] In `LibrarianURPAgent.process()`, update `ProcessResult` to use `text=` and `artifacts=`.
- [ ] Update any OpenHands SDK references to import from `urp.harnesses.openhands`.
- [ ] Verify that all agent test suites pass without warnings.
