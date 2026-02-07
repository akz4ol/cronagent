"""
Base channel interface for multi-platform communication.

Provides:
- Unified message format
- Authorization and rate limiting
- Abstract interface for channel implementations
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Callable, Awaitable

logger = logging.getLogger(__name__)


class ChannelType(str, Enum):
    """Supported channel types."""

    TELEGRAM = "telegram"
    SLACK = "slack"
    DISCORD = "discord"
    CLI = "cli"
    WEBHOOK = "webhook"


class MessageType(str, Enum):
    """Types of messages."""

    TEXT = "text"
    COMMAND = "command"
    FILE = "file"
    IMAGE = "image"
    REACTION = "reaction"
    CALLBACK = "callback"  # Button callbacks


@dataclass
class MessageContent:
    """Content of a message."""

    text: str
    type: MessageType = MessageType.TEXT

    # Optional attachments
    files: list[dict[str, Any]] = field(default_factory=list)
    images: list[str] = field(default_factory=list)

    # Formatting
    markdown: bool = True
    code_blocks: list[dict[str, str]] = field(default_factory=list)

    # Interactive elements
    buttons: list[dict[str, str]] = field(default_factory=list)
    callback_data: str | None = None


@dataclass
class MessageMetadata:
    """Metadata about a message."""

    # Threading
    thread_id: str | None = None
    reply_to_id: str | None = None

    # Platform-specific
    platform_data: dict[str, Any] = field(default_factory=dict)

    # Processing hints
    priority: int = 0  # Higher = more important
    ephemeral: bool = False  # Disappearing message


@dataclass
class UnifiedMessage:
    """
    Platform-agnostic message format.

    This is the standard format used internally, converted to/from
    platform-specific formats by each channel implementation.
    """

    id: str
    channel_type: ChannelType
    channel_id: str  # Platform-specific channel/chat ID
    user_id: str  # Platform-specific user ID
    username: str | None = None
    content: MessageContent = field(default_factory=lambda: MessageContent(text=""))
    metadata: MessageMetadata = field(default_factory=MessageMetadata)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Conversation context
    session_id: str | None = None
    project_id: str | None = None

    def is_command(self) -> bool:
        """Check if this is a command message."""
        return (
            self.content.type == MessageType.COMMAND
            or self.content.text.startswith("/")
        )

    def get_command(self) -> tuple[str, str] | None:
        """Extract command and arguments from message."""
        text = self.content.text.strip()
        if not text.startswith("/"):
            return None

        parts = text[1:].split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        return command, args


@dataclass
class OutgoingMessage:
    """Message to be sent to a channel."""

    channel_type: ChannelType
    channel_id: str
    content: MessageContent
    metadata: MessageMetadata = field(default_factory=MessageMetadata)

    # Target user (for DMs)
    user_id: str | None = None

    @classmethod
    def reply_to(cls, message: UnifiedMessage, text: str) -> OutgoingMessage:
        """Create a reply to an incoming message."""
        return cls(
            channel_type=message.channel_type,
            channel_id=message.channel_id,
            content=MessageContent(text=text),
            metadata=MessageMetadata(reply_to_id=message.id),
        )

    @classmethod
    def text(
        cls,
        channel_type: ChannelType,
        channel_id: str,
        text: str,
        **kwargs: Any,
    ) -> OutgoingMessage:
        """Create a simple text message."""
        return cls(
            channel_type=channel_type,
            channel_id=channel_id,
            content=MessageContent(text=text),
            **kwargs,
        )


# Type for message handlers
MessageHandler = Callable[[UnifiedMessage], Awaitable[OutgoingMessage | None]]


class RateLimiter:
    """
    Token bucket rate limiter.

    Limits the rate of operations per user/channel.
    """

    def __init__(
        self,
        rate: float = 1.0,  # tokens per second
        burst: int = 5,  # max burst size
    ) -> None:
        self.rate = rate
        self.burst = burst
        self._tokens: dict[str, float] = defaultdict(lambda: float(burst))
        self._last_update: dict[str, float] = defaultdict(time.time)

    async def acquire(self, key: str) -> bool:
        """
        Try to acquire a token for the given key.

        Returns True if allowed, False if rate limited.
        """
        now = time.time()
        elapsed = now - self._last_update[key]
        self._last_update[key] = now

        # Add tokens based on elapsed time
        self._tokens[key] = min(
            self.burst,
            self._tokens[key] + elapsed * self.rate,
        )

        if self._tokens[key] >= 1:
            self._tokens[key] -= 1
            return True
        return False

    async def wait(self, key: str) -> None:
        """Wait until a token is available."""
        while not await self.acquire(key):
            await asyncio.sleep(0.1)


class AuthorizationManager:
    """
    Manages user authorization for channels.

    Supports:
    - User whitelists per channel
    - Admin users
    - Rate limiting
    """

    def __init__(
        self,
        allowed_users: dict[ChannelType, set[str]] | None = None,
        admin_users: set[str] | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._allowed_users = allowed_users or {}
        self._admin_users = admin_users or set()
        self._rate_limiter = rate_limiter or RateLimiter()

    def is_authorized(
        self,
        channel_type: ChannelType,
        user_id: str,
    ) -> bool:
        """Check if a user is authorized for a channel."""
        # Admins are always authorized
        if user_id in self._admin_users:
            return True

        # Check channel-specific whitelist
        allowed = self._allowed_users.get(channel_type)
        if allowed is None:
            # No whitelist = allow all
            return True

        return user_id in allowed

    def is_admin(self, user_id: str) -> bool:
        """Check if a user is an admin."""
        return user_id in self._admin_users

    async def check_rate_limit(self, user_id: str) -> bool:
        """Check if user is within rate limits."""
        return await self._rate_limiter.acquire(user_id)

    def add_allowed_user(
        self,
        channel_type: ChannelType,
        user_id: str,
    ) -> None:
        """Add a user to the whitelist."""
        if channel_type not in self._allowed_users:
            self._allowed_users[channel_type] = set()
        self._allowed_users[channel_type].add(user_id)

    def remove_allowed_user(
        self,
        channel_type: ChannelType,
        user_id: str,
    ) -> None:
        """Remove a user from the whitelist."""
        if channel_type in self._allowed_users:
            self._allowed_users[channel_type].discard(user_id)


class BaseChannel(ABC):
    """
    Abstract base class for communication channels.

    Each channel implementation must:
    - Convert platform messages to UnifiedMessage
    - Convert OutgoingMessage to platform format
    - Handle connection lifecycle
    - Implement platform-specific features

    Usage:
        class TelegramChannel(BaseChannel):
            async def connect(self):
                # Initialize bot
                pass

            async def send(self, message: OutgoingMessage):
                # Send via Telegram API
                pass

            async def receive(self) -> AsyncIterator[UnifiedMessage]:
                # Yield incoming messages
                pass
    """

    def __init__(
        self,
        channel_type: ChannelType,
        config: dict[str, Any],
        auth_manager: AuthorizationManager | None = None,
    ) -> None:
        self.channel_type = channel_type
        self.config = config
        self.auth = auth_manager or AuthorizationManager()

        self._connected = False
        self._handlers: list[MessageHandler] = []

    @property
    def is_connected(self) -> bool:
        """Check if channel is connected."""
        return self._connected

    @abstractmethod
    async def connect(self) -> None:
        """
        Connect to the channel.

        Should initialize any necessary clients and start receiving messages.
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Disconnect from the channel.

        Should cleanly shutdown and release resources.
        """
        pass

    @abstractmethod
    async def send(self, message: OutgoingMessage) -> str | None:
        """
        Send a message to the channel.

        Args:
            message: Message to send

        Returns:
            Message ID if successful, None otherwise
        """
        pass

    @abstractmethod
    async def receive(self) -> AsyncIterator[UnifiedMessage]:
        """
        Receive messages from the channel.

        Yields:
            UnifiedMessage objects as they arrive
        """
        yield  # type: ignore
        pass

    def add_handler(self, handler: MessageHandler) -> None:
        """Add a message handler."""
        self._handlers.append(handler)

    def remove_handler(self, handler: MessageHandler) -> None:
        """Remove a message handler."""
        if handler in self._handlers:
            self._handlers.remove(handler)

    async def process_message(self, message: UnifiedMessage) -> None:
        """
        Process an incoming message through handlers.

        Handles authorization and rate limiting before calling handlers.
        """
        # Check authorization
        if not self.auth.is_authorized(self.channel_type, message.user_id):
            logger.warning(
                f"Unauthorized message from {message.user_id} on {self.channel_type}"
            )
            return

        # Check rate limit
        if not await self.auth.check_rate_limit(message.user_id):
            logger.warning(f"Rate limited user {message.user_id}")
            # Optionally send rate limit message
            return

        # Call handlers
        for handler in self._handlers:
            try:
                response = await handler(message)
                if response:
                    await self.send(response)
            except Exception as e:
                logger.error(f"Handler error: {e}", exc_info=True)

    async def send_text(
        self,
        channel_id: str,
        text: str,
        **kwargs: Any,
    ) -> str | None:
        """Convenience method to send a text message."""
        message = OutgoingMessage.text(
            channel_type=self.channel_type,
            channel_id=channel_id,
            text=text,
            **kwargs,
        )
        return await self.send(message)

    async def reply(
        self,
        to_message: UnifiedMessage,
        text: str,
    ) -> str | None:
        """Convenience method to reply to a message."""
        message = OutgoingMessage.reply_to(to_message, text)
        return await self.send(message)

    def format_for_platform(self, content: MessageContent) -> str:
        """
        Format content for this platform.

        Override in subclasses for platform-specific formatting.
        """
        text = content.text

        # Add code blocks
        for block in content.code_blocks:
            lang = block.get("language", "")
            code = block.get("code", "")
            text += f"\n```{lang}\n{code}\n```"

        return text
