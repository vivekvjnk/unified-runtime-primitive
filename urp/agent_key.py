"""
Agent Registry Data Model
=========================

Defines the composite identity, readiness, entry, and handle types
that form the data layer of the Agent Registry.

These types are intentionally decoupled from any orchestration logic (AOSM)
and depend only on the URP primitives (AbstractURPAgent, MessageEnvelope).

Design constraints (from agent_registry_design.md):
  - Registry is passive (no control flow)
  - Agent state is read-only externally
  - Communication is strictly via mailbox
  - System remains fully observable
"""

import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Optional

from .abstract_urp import AbstractURPAgent, AgentStatus
from .data_types import MessageEnvelope

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Composite Identity  (Section 3 of design doc)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentKey:
    """
    Semantic identity for registry lookup.

    Stable, human-meaningful, used for lookup and orchestration.
    A project may have one agent per (agent_type, module_name) pair.

    Examples:
        AgentKey("archy", "bms-monitor-module")
        AgentKey("librarian", "power-supply-module")
        AgentKey("archy", "power-supply-module")
    """
    agent_type: str       # e.g., "archy", "librarian", "ana"
    module_name: str      # e.g., "bms-monitor-module", "power-supply-module"

    def __str__(self) -> str:
        return f"{self.agent_type}:{self.module_name}"


# ---------------------------------------------------------------------------
# 2. Readiness Abstraction  (Section 5 of design doc)
# ---------------------------------------------------------------------------

class AgentReadiness(Enum):
    """
    System-level readiness, not agent-internal.

    Purpose: Allow AOSM to decide *when an agent can be invoked*.
    Derived from agent lifecycle state + (future) external dependencies.
    """
    READY = "READY"               # Agent is WAITING and all dependencies satisfied
    NOT_READY = "NOT_READY"       # Agent exists but cannot accept work yet
    DEGRADED = "DEGRADED"         # Agent can work but with reduced capability
    TERMINATED = "TERMINATED"     # Agent has been shut down


# ---------------------------------------------------------------------------
# 3. Registry Entry  (internal bookkeeping)
# ---------------------------------------------------------------------------

@dataclass
class AgentEntry:
    """
    Internal registry record wrapping a URP agent with metadata.

    This is the unit of storage in the registry.  It is never exposed
    directly to AOSM — the AgentHandle provides the external interface.
    """
    key: AgentKey
    agent: AbstractURPAgent
    runtime_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 4. Agent Handle  (Section 4 & 6 of design doc — the AOSM-facing interface)
# ---------------------------------------------------------------------------

class AgentHandle:
    """
    Communication and inspection wrapper returned to AOSM.

    This is the *only* object AOSM interacts with.  It enforces:
      - Communication strictly via mailbox (send)
      - Read-only state inspection (state, readiness)
      - No direct mutation of agent internals

    The handle holds a reference to the AgentEntry but exposes
    a restricted surface.
    """

    def __init__(self, entry: AgentEntry, readiness_fn: Callable[['AgentEntry'], 'AgentReadiness']):
        self._entry = entry
        self._readiness_fn = readiness_fn

    # -- Communication (mailbox only) --

    async def send(self, message: MessageEnvelope) -> None:
        """
        Asynchronous mailbox delivery.

        Delegates directly to the URP agent's send() method,
        preserving Invariant 3: Messages enter only through mailbox.
        """
        await self._entry.agent.send(message)

    # -- Inspection (read-only) --

    @property
    def key(self) -> AgentKey:
        """The semantic identity of the agent."""
        return self._entry.key

    @property
    def runtime_id(self) -> str:
        """Opaque runtime identity (UUID) for tracing and observability."""
        return self._entry.runtime_id

    @property
    def state(self) -> Dict[str, Any]:
        """
        Returns a safe, read-only view of the agent's runtime state.

        Matches the registry interface from the design doc (Section 4):
          {
              "agent_id": str,
              "status": AgentStatus,
              "session_id": str,
              "mailbox_size": int
          }
        """
        return self._entry.agent.state

    @property
    def readiness(self) -> AgentReadiness:
        """
        System-level readiness, computed by the registry.

        This is NOT agent-internal state — it's derived from
        lifecycle state + (future) external dependencies.
        """
        return self._readiness_fn(self._entry)

    @property
    def status(self) -> str:
        """Shortcut to the agent's current lifecycle status string."""
        return self._entry.agent.state.get("status", AgentStatus.UNINITIALIZED.value)

    @property
    def mailbox_size(self) -> int:
        """Current number of pending messages in the agent's mailbox."""
        return self._entry.agent.mailbox.qsize()

    def to_dict(self) -> Dict[str, Any]:
        """
        Serializable snapshot matching the design doc's registry.get() response:

          {
              "handle": AgentHandle,   (not serialized — this IS the handle)
              "runtime": { agent_id, status, session_id, mailbox_size },
              "readiness": Enum,
              "reason": Optional[str]
          }
        """
        readiness = self.readiness
        reason = None
        if readiness == AgentReadiness.NOT_READY:
            reason = f"Agent is in {self.status} state"
        elif readiness == AgentReadiness.TERMINATED:
            reason = "Agent has been terminated"

        return {
            "key": str(self._entry.key),
            "runtime": self.state,
            "readiness": readiness.value,
            "reason": reason,
        }

    def __repr__(self) -> str:
        return f"AgentHandle(key={self._entry.key}, status={self.status}, readiness={self.readiness.value})"
