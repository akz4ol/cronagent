"""
Channel manager for routing messages across platforms.

Provides:
- Unified message routing
- Channel lifecycle management
- Cross-platform broadcasting
- Agent integration
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Awaitable

from cronagent.bus.events import EventBus, Events
from cronagent.channels.base import (
    AuthorizationManager,
    BaseChannel,
    ChannelType,
    MessageHandler,
    OutgoingMessage,
    RateLimiter,
    UnifiedMessage,
)
from cronagent.config import ChannelsConfig

logger = logging.getLogger(__name__)

# Type for agent execution callback
AgentCallback = Callable[[str, str | None], Awaitable[str]]


class ChannelManager:
    """
    Central manager for all communication channels.

    Responsibilities:
    - Register and manage channel instances
    - Route incoming messages to handlers
    - Broadcast outgoing messages
    - Integrate with agent for responses

    Usage:
        manager = ChannelManager(config.channels, event_bus)

        # Register channels
        manager.register_channel(telegram_channel)
        manager.register_channel(slack_channel)

        # Set agent callback for responses
        manager.set_agent_callback(agent.execute_prompt)

        # Start all channels
        await manager.start()

        # Send to specific channel
        await manager.send(OutgoingMessage(...))

        # Broadcast to all channels
        await manager.broadcast("System maintenance in 5 minutes")

        # Graceful shutdown
        await manager.stop()
    """

    def __init__(
        self,
        config: ChannelsConfig,
        event_bus: EventBus | None = None,
    ) -> None:
        self.config = config
        self.event_bus = event_bus

        # Channel registry
        self._channels: dict[ChannelType, BaseChannel] = {}

        # Shared authorization
        self._auth = self._build_auth_manager()

        # Agent callback
        self._agent_callback: AgentCallback | None = None

        # Message handlers
        self._global_handlers: list[MessageHandler] = []

        # Running state
        self._running = False
        self._tasks: list[asyncio.Task] = []

    def _build_auth_manager(self) -> AuthorizationManager:
        """Build authorization manager from config."""
        allowed_users: dict[ChannelType, set[str]] = {}
        admin_users: set[str] = set()

        # Extract allowed users from channel configs
        for channel_type in ChannelType:
            channel_config = getattr(self.config, channel_type.value, None)
            if channel_config and hasattr(channel_config, "allowed_users"):
                users = channel_config.allowed_users or []
                if users:
                    allowed_users[channel_type] = set(users)

            # Collect admin users
            if channel_config and hasattr(channel_config, "admin_users"):
                admins = channel_config.admin_users or []
                admin_users.update(admins)

        return AuthorizationManager(
            allowed_users=allowed_users,
            admin_users=admin_users,
            rate_limiter=RateLimiter(rate=1.0, burst=10),
        )

    def register_channel(self, channel: BaseChannel) -> None:
        """
        Register a channel with the manager.

        Args:
            channel: Channel instance to register
        """
        self._channels[channel.channel_type] = channel

        # Add default message handler
        channel.add_handler(self._default_handler)

        # Add global handlers
        for handler in self._global_handlers:
            channel.add_handler(handler)

        logger.info(f"Registered channel: {channel.channel_type.value}")

    def unregister_channel(self, channel_type: ChannelType) -> None:
        """Unregister a channel."""
        if channel_type in self._channels:
            del self._channels[channel_type]
            logger.info(f"Unregistered channel: {channel_type.value}")

    def get_channel(self, channel_type: ChannelType) -> BaseChannel | None:
        """Get a registered channel by type."""
        return self._channels.get(channel_type)

    def add_global_handler(self, handler: MessageHandler) -> None:
        """Add a handler to all channels."""
        self._global_handlers.append(handler)

        # Add to existing channels
        for channel in self._channels.values():
            channel.add_handler(handler)

    def set_agent_callback(self, callback: AgentCallback) -> None:
        """
        Set the agent callback for message responses.

        The callback receives (prompt, project_id) and returns response text.
        """
        self._agent_callback = callback

    async def start(self) -> None:
        """Start all registered channels."""
        if self._running:
            return

        logger.info("Starting channel manager...")
        self._running = True

        # Connect all channels
        for channel_type, channel in self._channels.items():
            try:
                await channel.connect()
                logger.info(f"Connected: {channel_type.value}")

                # Start receive loop
                task = asyncio.create_task(
                    self._receive_loop(channel),
                    name=f"channel_{channel_type.value}",
                )
                self._tasks.append(task)

            except Exception as e:
                logger.error(f"Failed to connect {channel_type.value}: {e}")

        if self.event_bus:
            await self.event_bus.emit(
                Events.CHANNEL_CONNECTED,
                {"channels": [c.value for c in self._channels.keys()]},
            )

        logger.info(f"Channel manager started with {len(self._channels)} channels")

    async def stop(self) -> None:
        """Stop all channels."""
        if not self._running:
            return

        logger.info("Stopping channel manager...")
        self._running = False

        # Cancel receive tasks
        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        # Disconnect all channels
        for channel_type, channel in self._channels.items():
            try:
                await channel.disconnect()
                logger.info(f"Disconnected: {channel_type.value}")
            except Exception as e:
                logger.error(f"Error disconnecting {channel_type.value}: {e}")

        if self.event_bus:
            await self.event_bus.emit(Events.CHANNEL_DISCONNECTED, {})

        logger.info("Channel manager stopped")

    async def send(self, message: OutgoingMessage) -> str | None:
        """
        Send a message to a specific channel.

        Args:
            message: Message to send

        Returns:
            Message ID if successful
        """
        channel = self._channels.get(message.channel_type)
        if not channel:
            logger.warning(f"Channel not registered: {message.channel_type}")
            return None

        if not channel.is_connected:
            logger.warning(f"Channel not connected: {message.channel_type}")
            return None

        try:
            msg_id = await channel.send(message)

            if self.event_bus:
                await self.event_bus.emit(
                    Events.CHANNEL_MESSAGE_SENT,
                    {
                        "channel": message.channel_type.value,
                        "channel_id": message.channel_id,
                        "message_id": msg_id,
                    },
                )

            return msg_id

        except Exception as e:
            logger.error(f"Failed to send message: {e}")

            if self.event_bus:
                await self.event_bus.emit(
                    Events.CHANNEL_ERROR,
                    {
                        "channel": message.channel_type.value,
                        "error": str(e),
                    },
                )

            return None

    async def broadcast(
        self,
        text: str,
        channel_ids: dict[ChannelType, str] | None = None,
        exclude: list[ChannelType] | None = None,
    ) -> dict[ChannelType, str | None]:
        """
        Broadcast a message to multiple channels.

        Args:
            text: Message text
            channel_ids: Optional mapping of channel type to channel ID
            exclude: Channel types to exclude

        Returns:
            Dict of channel type to message ID
        """
        exclude = exclude or []
        results: dict[ChannelType, str | None] = {}

        for channel_type, channel in self._channels.items():
            if channel_type in exclude:
                continue

            if not channel.is_connected:
                continue

            # Get channel ID
            channel_id = None
            if channel_ids:
                channel_id = channel_ids.get(channel_type)

            if not channel_id:
                # Use default broadcast channel from config
                channel_config = getattr(self.config, channel_type.value, None)
                if channel_config:
                    channel_id = getattr(channel_config, "default_channel", None)

            if not channel_id:
                continue

            message = OutgoingMessage.text(
                channel_type=channel_type,
                channel_id=channel_id,
                text=text,
            )

            results[channel_type] = await self.send(message)

        return results

    async def _receive_loop(self, channel: BaseChannel) -> None:
        """Receive loop for a channel."""
        try:
            async for message in channel.receive():
                await self._handle_message(channel, message)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Receive loop error for {channel.channel_type}: {e}")

    async def _handle_message(
        self,
        channel: BaseChannel,
        message: UnifiedMessage,
    ) -> None:
        """Handle an incoming message."""
        if self.event_bus:
            await self.event_bus.emit(
                Events.CHANNEL_MESSAGE_RECEIVED,
                {
                    "channel": message.channel_type.value,
                    "user_id": message.user_id,
                    "text": message.content.text[:100],  # Truncate for logging
                },
            )

        # Process through channel handlers
        await channel.process_message(message)

    async def _default_handler(
        self,
        message: UnifiedMessage,
    ) -> OutgoingMessage | None:
        """
        Default message handler.

        Processes commands and forwards to agent.
        """
        text = message.content.text.strip()

        # Handle commands
        if message.is_command():
            return await self._handle_command(message)

        # Forward to agent if callback set
        if self._agent_callback and text:
            try:
                response = await self._agent_callback(
                    text,
                    message.project_id,
                )

                if response:
                    return OutgoingMessage.reply_to(message, response)

            except Exception as e:
                logger.error(f"Agent callback error: {e}")
                return OutgoingMessage.reply_to(
                    message,
                    f"Error processing request: {e}",
                )

        return None

    async def _handle_command(
        self,
        message: UnifiedMessage,
    ) -> OutgoingMessage | None:
        """Handle command messages."""
        cmd = message.get_command()
        if not cmd:
            return None

        command, args = cmd

        # Built-in commands
        if command == "help":
            return OutgoingMessage.reply_to(
                message,
                self._get_help_text(),
            )

        elif command == "status":
            status = await self._get_status()
            return OutgoingMessage.reply_to(message, status)

        elif command == "ping":
            return OutgoingMessage.reply_to(message, "Pong!")

        # Unknown command - pass to agent
        if self._agent_callback:
            response = await self._agent_callback(
                message.content.text,
                message.project_id,
            )
            if response:
                return OutgoingMessage.reply_to(message, response)

        return OutgoingMessage.reply_to(
            message,
            f"Unknown command: /{command}. Use /help for available commands.",
        )

    def _get_help_text(self) -> str:
        """Get help text for available commands."""
        return """**Available Commands:**

/help - Show this help message
/status - Show system status
/ping - Check if bot is responsive

**Usage:**
Simply send a message to interact with the AI agent.
The agent can help with code analysis, tasks, and more.
"""

    async def _get_status(self) -> str:
        """Get system status."""
        connected = [
            c.value for c, ch in self._channels.items()
            if ch.is_connected
        ]

        return f"""**System Status:**

Connected Channels: {', '.join(connected) or 'None'}
Total Channels: {len(self._channels)}
Running: {'Yes' if self._running else 'No'}
"""


async def create_channel_manager(
    config: ChannelsConfig,
    event_bus: EventBus | None = None,
) -> ChannelManager:
    """
    Create and configure a channel manager with enabled channels.

    Args:
        config: Channels configuration
        event_bus: Optional event bus

    Returns:
        Configured ChannelManager
    """
    manager = ChannelManager(config, event_bus)

    # Import and register enabled channels
    if config.telegram and config.telegram.enabled:
        try:
            from cronagent.channels.telegram import TelegramChannel

            channel = TelegramChannel(
                config.telegram.model_dump(),
                manager._auth,
            )
            manager.register_channel(channel)
        except ImportError:
            logger.warning("Telegram dependencies not installed")

    if config.slack and config.slack.enabled:
        try:
            from cronagent.channels.slack import SlackChannel

            channel = SlackChannel(
                config.slack.model_dump(),
                manager._auth,
            )
            manager.register_channel(channel)
        except ImportError:
            logger.warning("Slack dependencies not installed")

    if config.discord and config.discord.enabled:
        try:
            from cronagent.channels.discord import DiscordChannel

            channel = DiscordChannel(
                config.discord.model_dump(),
                manager._auth,
            )
            manager.register_channel(channel)
        except ImportError:
            logger.warning("Discord dependencies not installed")

    if config.webhook and config.webhook.enabled:
        from cronagent.channels.webhook import WebhookChannel

        channel = WebhookChannel(
            config.webhook.model_dump(),
            manager._auth,
        )
        manager.register_channel(channel)

    return manager
