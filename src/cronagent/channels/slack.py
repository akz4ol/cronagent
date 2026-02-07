"""
Slack channel implementation using slack-bolt.

Provides:
- Message receiving and sending
- Slack Block Kit formatting
- Thread support
- App mentions and DMs
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


class SlackChannel(BaseChannel):
    """
    Slack channel using slack-bolt.

    Config options:
        bot_token: Bot OAuth token (xoxb-...)
        app_token: App-level token for Socket Mode (xapp-...)
        signing_secret: Signing secret for verification
        allowed_users: List of allowed user IDs
        default_channel: Default channel for broadcasts

    Usage:
        channel = SlackChannel({
            "bot_token": "xoxb-...",
            "app_token": "xapp-...",
        })
        await channel.connect()
    """

    def __init__(
        self,
        config: dict[str, Any],
        auth_manager: AuthorizationManager | None = None,
    ) -> None:
        super().__init__(ChannelType.SLACK, config, auth_manager)

        self._bot_token = config.get("bot_token", "")
        self._app_token = config.get("app_token", "")
        self._signing_secret = config.get("signing_secret", "")

        # Will be initialized on connect
        self._app: Any = None
        self._handler: Any = None
        self._message_queue: asyncio.Queue[UnifiedMessage] = asyncio.Queue()

    async def connect(self) -> None:
        """Connect to Slack."""
        if self._connected:
            return

        try:
            from slack_bolt.async_app import AsyncApp
            from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
        except ImportError:
            raise ImportError(
                "slack-bolt not installed. "
                "Install with: pip install slack-bolt"
            )

        if not self._bot_token:
            raise ValueError("Slack bot token not configured")

        # Create Bolt app
        self._app = AsyncApp(
            token=self._bot_token,
            signing_secret=self._signing_secret or None,
        )

        # Register event handlers
        @self._app.event("message")
        async def handle_message(event: dict, say: Any) -> None:
            await self._handle_message(event)

        @self._app.event("app_mention")
        async def handle_mention(event: dict, say: Any) -> None:
            await self._handle_message(event, is_mention=True)

        # Start Socket Mode if app token provided
        if self._app_token:
            self._handler = AsyncSocketModeHandler(self._app, self._app_token)
            await self._handler.connect_async()
        else:
            logger.warning(
                "No app_token provided. Slack channel will use HTTP mode. "
                "Socket Mode is recommended for easier setup."
            )

        self._connected = True
        logger.info("Slack channel connected")

    async def disconnect(self) -> None:
        """Disconnect from Slack."""
        if not self._connected:
            return

        if self._handler:
            await self._handler.close_async()

        self._connected = False
        logger.info("Slack channel disconnected")

    async def send(self, message: OutgoingMessage) -> str | None:
        """Send a message via Slack."""
        if not self._app or not self._connected:
            return None

        try:
            channel = message.channel_id

            # Format text and blocks
            text = self.format_for_platform(message.content)
            blocks = self._build_blocks(message.content)

            # Send message
            kwargs: dict[str, Any] = {
                "channel": channel,
                "text": text,
            }

            if blocks:
                kwargs["blocks"] = blocks

            # Thread reply
            if message.metadata.thread_id:
                kwargs["thread_ts"] = message.metadata.thread_id

            # Reply to specific message
            if message.metadata.reply_to_id:
                kwargs["thread_ts"] = message.metadata.reply_to_id

            result = await self._app.client.chat_postMessage(**kwargs)

            if result["ok"]:
                return result["ts"]

            logger.error(f"Slack API error: {result.get('error')}")
            return None

        except Exception as e:
            logger.error(f"Failed to send Slack message: {e}")
            return None

    async def receive(self) -> AsyncIterator[UnifiedMessage]:
        """Receive messages from Slack."""
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

    async def _handle_message(
        self,
        event: dict,
        is_mention: bool = False,
    ) -> None:
        """Handle incoming Slack messages."""
        # Ignore bot messages
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return

        user_id = event.get("user", "")
        channel_id = event.get("channel", "")
        message_id = event.get("ts", "")
        thread_ts = event.get("thread_ts")
        text = event.get("text", "")

        # Get user info for username
        username = None
        try:
            user_info = await self._app.client.users_info(user=user_id)
            if user_info["ok"]:
                username = user_info["user"].get("name")
        except Exception:
            pass

        # Determine message type
        msg_type = MessageType.TEXT
        if text.startswith("/"):
            msg_type = MessageType.COMMAND

        # Create unified message
        unified = UnifiedMessage(
            id=message_id,
            channel_type=ChannelType.SLACK,
            channel_id=channel_id,
            user_id=user_id,
            username=username,
            content=MessageContent(
                text=text,
                type=msg_type,
            ),
            metadata=MessageMetadata(
                thread_id=thread_ts,
                platform_data={
                    "is_mention": is_mention,
                    "channel_type": event.get("channel_type"),
                },
            ),
        )

        await self._message_queue.put(unified)

    def _build_blocks(self, content: MessageContent) -> list[dict] | None:
        """Build Slack Block Kit blocks from content."""
        blocks = []

        # Main text as section
        if content.text:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": content.text,
                },
            })

        # Code blocks
        for block in content.code_blocks:
            code = block.get("code", "")
            lang = block.get("language", "")

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"```{code}```",
                },
            })

        # Buttons as actions
        if content.buttons:
            elements = []
            for btn in content.buttons:
                elements.append({
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": btn.get("text", ""),
                    },
                    "action_id": btn.get("callback_data", ""),
                })

            blocks.append({
                "type": "actions",
                "elements": elements,
            })

        return blocks if blocks else None

    def format_for_platform(self, content: MessageContent) -> str:
        """Format content for Slack mrkdwn."""
        text = content.text

        # Slack uses different markdown
        # Bold: *text* -> *text* (same)
        # Italic: _text_ -> _text_ (same)
        # Code: `code` -> `code` (same)
        # Links: [text](url) -> <url|text>

        # Add code blocks
        for block in content.code_blocks:
            code = block.get("code", "")
            text += f"\n```\n{code}\n```"

        return text

    async def post_to_channel(
        self,
        channel: str,
        text: str,
        blocks: list[dict] | None = None,
    ) -> str | None:
        """Convenience method to post to a channel by name or ID."""
        message = OutgoingMessage(
            channel_type=ChannelType.SLACK,
            channel_id=channel,
            content=MessageContent(text=text),
        )

        return await self.send(message)

    async def send_dm(
        self,
        user_id: str,
        text: str,
    ) -> str | None:
        """Send a direct message to a user."""
        try:
            # Open DM channel
            result = await self._app.client.conversations_open(users=[user_id])
            if not result["ok"]:
                return None

            channel_id = result["channel"]["id"]

            return await self.send_text(channel_id, text)

        except Exception as e:
            logger.error(f"Failed to send Slack DM: {e}")
            return None
