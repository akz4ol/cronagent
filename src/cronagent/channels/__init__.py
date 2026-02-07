"""Multi-channel communication system."""

from cronagent.channels.base import (
    AuthorizationManager,
    BaseChannel,
    ChannelType,
    MessageContent,
    MessageHandler,
    MessageMetadata,
    MessageType,
    OutgoingMessage,
    RateLimiter,
    UnifiedMessage,
)
from cronagent.channels.cli_channel import CLIChannel, run_cli_session
from cronagent.channels.manager import ChannelManager, create_channel_manager
from cronagent.channels.webhook import WebhookChannel, send_webhook

__all__ = [
    # Base classes and types
    "AuthorizationManager",
    "BaseChannel",
    "ChannelType",
    "MessageContent",
    "MessageHandler",
    "MessageMetadata",
    "MessageType",
    "OutgoingMessage",
    "RateLimiter",
    "UnifiedMessage",
    # Manager
    "ChannelManager",
    "create_channel_manager",
    # CLI
    "CLIChannel",
    "run_cli_session",
    # Webhook
    "WebhookChannel",
    "send_webhook",
]

# Optional imports for platform-specific channels
# These may fail if dependencies aren't installed

try:
    from cronagent.channels.telegram import TelegramChannel

    __all__.append("TelegramChannel")
except ImportError:
    pass

try:
    from cronagent.channels.slack import SlackChannel

    __all__.append("SlackChannel")
except ImportError:
    pass

try:
    from cronagent.channels.discord import DiscordChannel

    __all__.append("DiscordChannel")
except ImportError:
    pass
