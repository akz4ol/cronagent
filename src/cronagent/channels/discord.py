"""
Discord channel implementation using discord.py.

Provides:
- Message receiving and sending
- Discord markdown formatting
- Embed support
- Slash commands
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from cronagent.channels.base import (
    AuthorizationManager,
    BaseChannel,
    ChannelType,
    MessageContent,
    MessageMetadata,
    MessageType,
    OutgoingMessage,
    UnifiedMessage,
)

logger = logging.getLogger(__name__)


class DiscordChannel(BaseChannel):
    """
    Discord bot channel using discord.py.

    Config options:
        token: Bot token from Discord Developer Portal
        allowed_users: List of allowed user IDs
        allowed_guilds: List of allowed guild (server) IDs
        command_prefix: Prefix for text commands (default: !)

    Usage:
        channel = DiscordChannel({
            "token": "BOT_TOKEN",
            "allowed_guilds": ["123456789"],
        })
        await channel.connect()
    """

    def __init__(
        self,
        config: dict[str, Any],
        auth_manager: AuthorizationManager | None = None,
    ) -> None:
        super().__init__(ChannelType.DISCORD, config, auth_manager)

        self._token = config.get("token", "")
        self._allowed_guilds = set(config.get("allowed_guilds", []))
        self._command_prefix = config.get("command_prefix", "!")

        # Will be initialized on connect
        self._client: Any = None
        self._message_queue: asyncio.Queue[UnifiedMessage] = asyncio.Queue()
        self._ready_event = asyncio.Event()

    async def connect(self) -> None:
        """Connect to Discord."""
        if self._connected:
            return

        try:
            import discord
            from discord import Intents
        except ImportError:
            raise ImportError(
                "discord.py not installed. "
                "Install with: pip install discord.py"
            )

        if not self._token:
            raise ValueError("Discord bot token not configured")

        # Set up intents
        intents = Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.dm_messages = True

        # Create client
        self._client = discord.Client(intents=intents)

        # Register event handlers
        @self._client.event
        async def on_ready() -> None:
            logger.info(f"Discord bot connected as {self._client.user}")
            self._ready_event.set()

        @self._client.event
        async def on_message(message: Any) -> None:
            await self._handle_message(message)

        # Start client in background
        asyncio.create_task(self._client.start(self._token))

        # Wait for ready
        await asyncio.wait_for(self._ready_event.wait(), timeout=30)

        self._connected = True
        logger.info("Discord channel connected")

    async def disconnect(self) -> None:
        """Disconnect from Discord."""
        if not self._connected:
            return

        if self._client:
            await self._client.close()

        self._connected = False
        self._ready_event.clear()
        logger.info("Discord channel disconnected")

    async def send(self, message: OutgoingMessage) -> str | None:
        """Send a message via Discord."""
        if not self._client or not self._connected:
            return None

        try:
            import discord

            # Get channel
            channel_id = int(message.channel_id)
            channel = self._client.get_channel(channel_id)

            if not channel:
                # Try fetching
                channel = await self._client.fetch_channel(channel_id)

            if not channel:
                logger.error(f"Discord channel not found: {channel_id}")
                return None

            # Format text
            text = self.format_for_platform(message.content)

            # Build embed if needed
            embed = self._build_embed(message.content)

            # Send message
            kwargs: dict[str, Any] = {}

            if text:
                kwargs["content"] = text

            if embed:
                kwargs["embed"] = embed

            # Reply to message
            if message.metadata.reply_to_id:
                try:
                    ref_msg = await channel.fetch_message(
                        int(message.metadata.reply_to_id)
                    )
                    kwargs["reference"] = ref_msg
                except Exception:
                    pass

            sent = await channel.send(**kwargs)
            return str(sent.id)

        except Exception as e:
            logger.error(f"Failed to send Discord message: {e}")
            return None

    async def receive(self) -> AsyncIterator[UnifiedMessage]:
        """Receive messages from Discord."""
        while self._connected:
            try:
                message = await asyncio.wait_for(
                    self._message_queue.get(),
                    timeout=1.0,
                )
                yield message
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _handle_message(self, message: Any) -> None:
        """Handle incoming Discord messages."""
        # Ignore bot's own messages
        if message.author == self._client.user:
            return

        # Ignore bots
        if message.author.bot:
            return

        # Check guild whitelist
        if message.guild and self._allowed_guilds:
            if str(message.guild.id) not in self._allowed_guilds:
                return

        user_id = str(message.author.id)
        channel_id = str(message.channel.id)
        message_id = str(message.id)
        text = message.content

        # Determine message type
        msg_type = MessageType.TEXT
        if text.startswith(self._command_prefix):
            msg_type = MessageType.COMMAND
            # Convert to slash-style for unified handling
            text = "/" + text[len(self._command_prefix):]
        elif text.startswith("/"):
            msg_type = MessageType.COMMAND

        # Get thread info
        thread_id = None
        if hasattr(message.channel, "parent_id"):
            thread_id = str(message.channel.id)

        # Create unified message
        unified = UnifiedMessage(
            id=message_id,
            channel_type=ChannelType.DISCORD,
            channel_id=channel_id,
            user_id=user_id,
            username=message.author.name,
            content=MessageContent(
                text=text,
                type=msg_type,
            ),
            metadata=MessageMetadata(
                thread_id=thread_id,
                platform_data={
                    "guild_id": str(message.guild.id) if message.guild else None,
                    "guild_name": message.guild.name if message.guild else None,
                    "is_dm": message.guild is None,
                },
            ),
        )

        await self._message_queue.put(unified)

    def _build_embed(self, content: MessageContent) -> Any | None:
        """Build Discord embed from content."""
        try:
            import discord
        except ImportError:
            return None

        # Only create embed for code blocks or special content
        if not content.code_blocks:
            return None

        embed = discord.Embed(
            color=discord.Color.blue(),
        )

        # Add code blocks as fields
        for i, block in enumerate(content.code_blocks):
            lang = block.get("language", "")
            code = block.get("code", "")

            # Discord has a 1024 char limit for field values
            if len(code) > 1000:
                code = code[:1000] + "..."

            embed.add_field(
                name=f"Code ({lang})" if lang else "Code",
                value=f"```{lang}\n{code}\n```",
                inline=False,
            )

        return embed

    def format_for_platform(self, content: MessageContent) -> str:
        """Format content for Discord markdown."""
        text = content.text

        # Discord markdown is similar to standard markdown
        # Bold: **text**
        # Italic: *text* or _text_
        # Code: `code` or ```code```
        # Strikethrough: ~~text~~
        # Spoiler: ||text||

        # Don't add code blocks here if we're using embeds
        if not content.code_blocks:
            return text

        # Add code blocks inline if no embed
        for block in content.code_blocks:
            lang = block.get("language", "")
            code = block.get("code", "")
            text += f"\n```{lang}\n{code}\n```"

        return text

    async def send_dm(
        self,
        user_id: str,
        text: str,
    ) -> str | None:
        """Send a direct message to a user."""
        try:
            user = await self._client.fetch_user(int(user_id))
            if not user:
                return None

            dm_channel = await user.create_dm()

            message = OutgoingMessage(
                channel_type=ChannelType.DISCORD,
                channel_id=str(dm_channel.id),
                content=MessageContent(text=text),
            )

            return await self.send(message)

        except Exception as e:
            logger.error(f"Failed to send Discord DM: {e}")
            return None
