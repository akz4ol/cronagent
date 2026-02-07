"""
Telegram channel implementation using python-telegram-bot.

Provides:
- Message receiving and sending
- Markdown formatting
- File/image support
- Inline keyboards
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


class TelegramChannel(BaseChannel):
    """
    Telegram bot channel using python-telegram-bot.

    Config options:
        token: Bot token from @BotFather
        allowed_users: List of allowed user IDs
        admin_users: List of admin user IDs
        parse_mode: Message parse mode (MarkdownV2, HTML)

    Usage:
        channel = TelegramChannel({
            "token": "BOT_TOKEN",
            "allowed_users": ["123456789"],
        })
        await channel.connect()
    """

    def __init__(
        self,
        config: dict[str, Any],
        auth_manager: AuthorizationManager | None = None,
    ) -> None:
        super().__init__(ChannelType.TELEGRAM, config, auth_manager)

        self._token = config.get("token", "")
        self._parse_mode = config.get("parse_mode", "MarkdownV2")

        # Will be initialized on connect
        self._app: Any = None
        self._message_queue: asyncio.Queue[UnifiedMessage] = asyncio.Queue()

    async def connect(self) -> None:
        """Connect to Telegram."""
        if self._connected:
            return

        try:
            from telegram import Update
            from telegram.ext import (
                Application,
                CommandHandler,
                MessageHandler,
                filters,
            )
        except ImportError:
            raise ImportError(
                "python-telegram-bot not installed. "
                "Install with: pip install python-telegram-bot"
            )

        if not self._token:
            raise ValueError("Telegram bot token not configured")

        # Build application
        self._app = (
            Application.builder()
            .token(self._token)
            .build()
        )

        # Add handlers
        self._app.add_handler(
            CommandHandler("start", self._handle_start)
        )
        self._app.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                self._handle_message,
            )
        )
        self._app.add_handler(
            CommandHandler(
                ["help", "status", "ping"],
                self._handle_command,
            )
        )

        # Start polling in background
        await self._app.initialize()
        await self._app.start()
        asyncio.create_task(self._app.updater.start_polling())

        self._connected = True
        logger.info("Telegram channel connected")

    async def disconnect(self) -> None:
        """Disconnect from Telegram."""
        if not self._connected:
            return

        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

        self._connected = False
        logger.info("Telegram channel disconnected")

    async def send(self, message: OutgoingMessage) -> str | None:
        """Send a message via Telegram."""
        if not self._app or not self._connected:
            return None

        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            from telegram.constants import ParseMode

            chat_id = message.channel_id

            # Format text
            text = self.format_for_platform(message.content)

            # Build keyboard if buttons provided
            reply_markup = None
            if message.content.buttons:
                keyboard = [
                    [
                        InlineKeyboardButton(
                            btn.get("text", ""),
                            callback_data=btn.get("callback_data", ""),
                        )
                        for btn in message.content.buttons
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

            # Determine parse mode
            parse_mode = None
            if message.content.markdown:
                parse_mode = ParseMode.MARKDOWN_V2

            # Send message
            reply_to = None
            if message.metadata.reply_to_id:
                try:
                    reply_to = int(message.metadata.reply_to_id)
                except ValueError:
                    pass

            sent = await self._app.bot.send_message(
                chat_id=chat_id,
                text=self._escape_markdown(text) if parse_mode == ParseMode.MARKDOWN_V2 else text,
                parse_mode=parse_mode,
                reply_to_message_id=reply_to,
                reply_markup=reply_markup,
            )

            return str(sent.message_id)

        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return None

    async def receive(self) -> AsyncIterator[UnifiedMessage]:
        """Receive messages from Telegram."""
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

    async def _handle_start(self, update: Any, context: Any) -> None:
        """Handle /start command."""
        if not update.effective_user:
            return

        user_id = str(update.effective_user.id)

        # Check authorization
        if not self.auth.is_authorized(ChannelType.TELEGRAM, user_id):
            await update.message.reply_text(
                "You are not authorized to use this bot."
            )
            return

        await update.message.reply_text(
            "Welcome to CronAgent!\n\n"
            "I'm an AI assistant that can help with code tasks.\n"
            "Send me a message or use /help for commands."
        )

    async def _handle_message(self, update: Any, context: Any) -> None:
        """Handle incoming text messages."""
        if not update.message or not update.effective_user:
            return

        user_id = str(update.effective_user.id)
        username = update.effective_user.username
        chat_id = str(update.effective_chat.id)
        message_id = str(update.message.message_id)
        text = update.message.text or ""

        # Create unified message
        unified = UnifiedMessage(
            id=message_id,
            channel_type=ChannelType.TELEGRAM,
            channel_id=chat_id,
            user_id=user_id,
            username=username,
            content=MessageContent(text=text),
            metadata=MessageMetadata(
                thread_id=str(update.message.message_thread_id)
                if update.message.message_thread_id
                else None,
                platform_data={
                    "chat_type": update.effective_chat.type,
                    "chat_title": update.effective_chat.title,
                },
            ),
        )

        # Queue for processing
        await self._message_queue.put(unified)

    async def _handle_command(self, update: Any, context: Any) -> None:
        """Handle command messages."""
        if not update.message or not update.effective_user:
            return

        user_id = str(update.effective_user.id)
        chat_id = str(update.effective_chat.id)
        message_id = str(update.message.message_id)
        text = update.message.text or ""

        # Create unified message as command
        unified = UnifiedMessage(
            id=message_id,
            channel_type=ChannelType.TELEGRAM,
            channel_id=chat_id,
            user_id=user_id,
            username=update.effective_user.username,
            content=MessageContent(
                text=text,
                type=MessageType.COMMAND,
            ),
        )

        await self._message_queue.put(unified)

    def _escape_markdown(self, text: str) -> str:
        """Escape special characters for MarkdownV2."""
        # Characters that need escaping in MarkdownV2
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']

        # Don't escape inside code blocks
        result = []
        in_code = False
        i = 0

        while i < len(text):
            if text[i:i+3] == '```':
                in_code = not in_code
                result.append('```')
                i += 3
            elif text[i] == '`' and not in_code:
                # Single backtick - find closing
                result.append('`')
                i += 1
            elif not in_code and text[i] in special_chars:
                result.append('\\')
                result.append(text[i])
                i += 1
            else:
                result.append(text[i])
                i += 1

        return ''.join(result)

    def format_for_platform(self, content: MessageContent) -> str:
        """Format content for Telegram."""
        text = content.text

        # Add code blocks with language hints
        for block in content.code_blocks:
            lang = block.get("language", "")
            code = block.get("code", "")
            text += f"\n```{lang}\n{code}\n```"

        return text
