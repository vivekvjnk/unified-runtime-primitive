"""
Agent Registry
==============

Factory-based registry for persistent URP agents, designed after openhands-agent-sdk.

This registry enables:
  * registration of custom agent factory functions and metadata
  * global thread-safe registry lookup
  * instance-level registry objects for scoped lifetime/creation
  * global and scoped pre-create and post-create execution hooks

State management and lifecycle loops of active agent instances are decoupled
and handled externally (e.g., by the orchestrator or runner), ensuring:
  - "Systems decide; agents propose"
  - No authority leakage
  - No hidden/implicit state in the registry
  - See: docs/source/mas/agent_registry/agent_registry_design.md
"""

import logging
from threading import RLock
from typing import Any, Callable, Dict, List, NamedTuple, Optional

from .abstract_urp import AbstractURPAgent
from .data_types import AgentDescriptor

logger = logging.getLogger(__name__)


class AgentFactory(NamedTuple):
    """Container for an agent factory function and its metadata/descriptor."""
    factory_func: Callable[..., AbstractURPAgent]
    descriptor: AgentDescriptor


# -----------------------------------------------------------------
# Global Registry Layer
# -----------------------------------------------------------------

_agent_factories: Dict[str, AgentFactory] = {}
_pre_create_hooks: List[Callable[[str, Any, Any], None]] = []
_post_create_hooks: List[Callable[[str, AbstractURPAgent, Any, Any], None]] = []
_registry_lock = RLock()


def register_agent(
    name: str,
    factory_func: Callable[..., AbstractURPAgent],
    descriptor: AgentDescriptor,
) -> None:
    """
    Register a custom agent factory globally.

    Args:
        name: Unique name for the agent type (used as the registry key).
        factory_func: Function that takes configuration/context and returns a fully-configured AbstractURPAgent.
        descriptor: An AgentDescriptor carrying tools, capabilities, and other metadata.

    Raises:
        ValueError: If an agent factory with the same name already exists.
    """
    with _registry_lock:
        if name in _agent_factories:
            raise ValueError(f"Agent factory '{name}' already registered")

        _agent_factories[name] = AgentFactory(
            factory_func=factory_func, descriptor=descriptor
        )
        logger.info(f"[AgentRegistry] Globally registered agent factory: {name}")


def register_agent_if_absent(
    name: str,
    factory_func: Callable[..., AbstractURPAgent],
    descriptor: AgentDescriptor,
) -> bool:
    """
    Register a custom agent factory globally if not already registered.

    Returns:
        True if the agent was registered, False if it was already registered.
    """
    with _registry_lock:
        if name in _agent_factories:
            return False

        _agent_factories[name] = AgentFactory(
            factory_func=factory_func, descriptor=descriptor
        )
        logger.info(f"[AgentRegistry] Globally registered agent factory (if absent): {name}")
        return True


def get_agent_factory(name: str) -> AgentFactory:
    """
    Get a registered agent factory by name.

    Args:
        name: Name of the agent factory to retrieve.

    Returns:
        AgentFactory: The factory function and descriptor

    Raises:
        ValueError: If no agent factory with the given name is found
    """
    with _registry_lock:
        factory = _agent_factories.get(name)
        available = sorted(_agent_factories.keys())

    if factory is None:
        available_list = ", ".join(available) if available else "none registered"
        raise ValueError(
            f"Unknown agent type '{name}'. Available types: {available_list}. "
            "Use register_agent() to add custom agent types."
        )

    return factory


def get_registered_agent_descriptors() -> List[AgentDescriptor]:
    """Return the descriptors of all globally registered agents."""
    with _registry_lock:
        return [f.descriptor for f in _agent_factories.values()]


def add_pre_create_hook(hook: Callable[[str, Any, Any], None]) -> None:
    """Register a global pre-create hook to execute before any agent is globally instantiated."""
    with _registry_lock:
        _pre_create_hooks.append(hook)
        logger.info(f"[AgentRegistry] Registered global pre-create hook: {hook.__name__ if hasattr(hook, '__name__') else str(hook)}")


def add_post_create_hook(hook: Callable[[str, AbstractURPAgent, Any, Any], None]) -> None:
    """Register a global post-create hook to execute after any agent is globally instantiated."""
    with _registry_lock:
        _post_create_hooks.append(hook)
        logger.info(f"[AgentRegistry] Registered global post-create hook: {hook.__name__ if hasattr(hook, '__name__') else str(hook)}")


def create_agent(name: str, *args, **kwargs) -> AbstractURPAgent:
    """
    Globally create an agent instance by name, executing all global pre-create and post-create hooks.

    Args:
        name: The agent type to instantiate.
        *args, **kwargs: Dynamic arguments to pass to the factory function.

    Returns:
        A fully constructed and hooked AbstractURPAgent.
    """
    # 1. Execute global pre-create hooks
    with _registry_lock:
        pre_hooks = list(_pre_create_hooks)
    for hook in pre_hooks:
        try:
            hook(name, *args, **kwargs)
        except Exception as e:
            logger.error(f"[AgentRegistry] Error running global pre-create hook: {e}", exc_info=True)

    # 2. Retrieve factory and instantiate agent
    factory = get_agent_factory(name)
    logger.info(f"[AgentRegistry] Globally instantiating agent '{name}' via factory")
    agent = factory.factory_func(*args, **kwargs)

    # 3. Execute global post-create hooks
    with _registry_lock:
        post_hooks = list(_post_create_hooks)
    for hook in post_hooks:
        try:
            hook(name, agent, *args, **kwargs)
        except Exception as e:
            logger.error(f"[AgentRegistry] Error running global post-create hook: {e}", exc_info=True)

    return agent


def _reset_registry_for_tests() -> None:
    """Clear the global registry and hooks for tests to avoid cross-test contamination."""
    with _registry_lock:
        _agent_factories.clear()
        _pre_create_hooks.clear()
        _post_create_hooks.clear()
        logger.info("[AgentRegistry] Global registry and hooks reset")


# -----------------------------------------------------------------
# Instance-based Registry Class
# -----------------------------------------------------------------

class AgentRegistry:
    """
    Instance-based registry for persistent URP agent factories.

    Provides a scoped, object-oriented interface for registering and instantiating
    agent types with localized pre-create and post-create hooks.
    """

    def __init__(self):
        self._factories: Dict[str, AgentFactory] = {}
        self._pre_create_hooks: List[Callable[[str, Any, Any], None]] = []
        self._post_create_hooks: List[Callable[[str, AbstractURPAgent, Any, Any], None]] = []
        self._lock = RLock()
        logger.info("[AgentRegistry] Initialized (empty factory registry)")

    def register(
        self,
        name: str,
        factory_func: Callable[..., AbstractURPAgent],
        descriptor: AgentDescriptor,
    ) -> None:
        """Registers an agent factory under the given name."""
        with self._lock:
            if name in self._factories:
                raise ValueError(f"Agent factory '{name}' already registered in this registry instance")

            self._factories[name] = AgentFactory(
                factory_func=factory_func, descriptor=descriptor
            )
            logger.info(f"[AgentRegistry] Scoped registry registered factory: {name}")

    def register_if_absent(
        self,
        name: str,
        factory_func: Callable[..., AbstractURPAgent],
        descriptor: AgentDescriptor,
    ) -> bool:
        """Registers an agent factory if no factory with that name exists yet."""
        with self._lock:
            if name in self._factories:
                return False

            self._factories[name] = AgentFactory(
                factory_func=factory_func, descriptor=descriptor
            )
            logger.info(f"[AgentRegistry] Scoped registry registered factory (if absent): {name}")
            return True

    def get_factory(self, name: str) -> AgentFactory:
        """Retrieves a registered agent factory by name."""
        with self._lock:
            factory = self._factories.get(name)
            available = sorted(self._factories.keys())

        if factory is None:
            available_list = ", ".join(available) if available else "none registered"
            raise ValueError(
                f"Unknown agent type '{name}' in this registry instance. Available types: {available_list}."
            )

        return factory

    def get_registered_descriptors(self) -> List[AgentDescriptor]:
        """Returns descriptors of all registered agents in this instance."""
        with self._lock:
            return [f.descriptor for f in self._factories.values()]

    def add_pre_create_hook(self, hook: Callable[[str, Any, Any], None]) -> None:
        """Register a scoped pre-create hook to execute before any agent is instantiated via this registry."""
        with self._lock:
            self._pre_create_hooks.append(hook)
            logger.info(f"[AgentRegistry] Registered scoped pre-create hook: {hook.__name__ if hasattr(hook, '__name__') else str(hook)}")

    def add_post_create_hook(self, hook: Callable[[str, AbstractURPAgent, Any, Any], None]) -> None:
        """Register a scoped post-create hook to execute after any agent is instantiated via this registry."""
        with self._lock:
            self._post_create_hooks.append(hook)
            logger.info(f"[AgentRegistry] Registered scoped post-create hook: {hook.__name__ if hasattr(hook, '__name__') else str(hook)}")

    def create_agent(self, name: str, *args, **kwargs) -> AbstractURPAgent:
        """
        Creates a new, fully initialized agent instance using the registered factory,
        executing all scoped pre-create and post-create hooks.

        Args:
            name: The agent type to instantiate.
            *args, **kwargs: Dynamic arguments to pass to the factory function.

        Returns:
            A fully constructed and hooked AbstractURPAgent.
        """
        # 1. Execute scoped pre-create hooks
        with self._lock:
            pre_hooks = list(self._pre_create_hooks)
        for hook in pre_hooks:
            try:
                hook(name, *args, **kwargs)
            except Exception as e:
                logger.error(f"[AgentRegistry] Error running scoped pre-create hook: {e}", exc_info=True)

        # 2. Retrieve factory and instantiate agent
        factory = self.get_factory(name)
        logger.info(f"[AgentRegistry] Scoped registry instantiating agent '{name}' via factory")
        agent = factory.factory_func(*args, **kwargs)

        # 3. Execute scoped post-create hooks
        with self._lock:
            post_hooks = list(self._post_create_hooks)
        for hook in post_hooks:
            try:
                hook(name, agent, *args, **kwargs)
            except Exception as e:
                logger.error(f"[AgentRegistry] Error running scoped post-create hook: {e}", exc_info=True)

        return agent

    def contains(self, name: str) -> bool:
        """Checks if a factory is registered under this name."""
        with self._lock:
            return name in self._factories

    @property
    def size(self) -> int:
        """Number of factories currently registered."""
        with self._lock:
            return len(self._factories)

    def clear(self) -> None:
        """Clears all registered factories and hooks in this instance."""
        with self._lock:
            self._factories.clear()
            self._pre_create_hooks.clear()
            self._post_create_hooks.clear()
            logger.info("[AgentRegistry] Scoped registry cleared")

    def __repr__(self) -> str:
        with self._lock:
            types_str = ", ".join(self._factories.keys())
        return f"AgentRegistry(size={self.size}, registered_types=[{types_str}])"
