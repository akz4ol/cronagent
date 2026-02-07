"""Agent core module - Claude SDK integration."""

from cronagent.agent.context import AgentContext, ConversationTurn
from cronagent.agent.loop import (
    AgentEvent,
    AgentLoop,
    AgentLoopConfig,
    create_agent_with_memory,
    run_agent_task,
)

__all__ = [
    # Context
    "AgentContext",
    "ConversationTurn",
    # Loop
    "AgentEvent",
    "AgentLoop",
    "AgentLoopConfig",
    # Convenience functions
    "create_agent_with_memory",
    "run_agent_task",
]
