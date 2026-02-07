"""
CronAgent - Autonomous agent system with Claude SDK for scheduled task execution.

This package provides:
- Scheduled task execution with cron expressions
- Multi-channel communication (Telegram, Slack, Discord, CLI, Webhooks)
- Session persistence with cross-session learning
- Long-term knowledge base with vector search
- Extensible skills system via MCP
"""

__version__ = "0.1.0"
__author__ = "CronAgent Team"

# Core configuration
from cronagent.config import (
    AgentConfig,
    ChannelsConfig,
    CronAgentConfig,
    MemoryConfig,
    NotificationConfig,
    SchedulerConfig,
)

# Agent components
from cronagent.agent import (
    AgentContext,
    AgentEvent,
    AgentLoop,
    AgentLoopConfig,
    create_agent_with_memory,
    run_agent_task,
)

# Event bus
from cronagent.bus import Event, EventBus

__all__ = [
    # Version
    "__version__",
    # Configuration
    "AgentConfig",
    "ChannelsConfig",
    "CronAgentConfig",
    "MemoryConfig",
    "NotificationConfig",
    "SchedulerConfig",
    # Agent
    "AgentContext",
    "AgentEvent",
    "AgentLoop",
    "AgentLoopConfig",
    "create_agent_with_memory",
    "run_agent_task",
    # Events
    "Event",
    "EventBus",
]
