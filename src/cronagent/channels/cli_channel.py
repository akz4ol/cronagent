"""
CLI channel for local interactive sessions.

Provides:
- Terminal-based input/output
- Rich formatting support
- Streaming response display
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any, AsyncIterator
from uuid import uuid4

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


class CLIChannel(BaseChannel):
    """
    Command-line interface channel.

    Provides interactive terminal-based communication with the agent.
    Uses Rich for formatted output when available.

    Config options:
        user_id: User identifier (default: "cli_user")
        prompt: Input prompt string (default: "> ")
        use_rich: Use Rich for formatting (default: True)

    Usage:
        channel = CLIChannel({
            "prompt": "You: ",
        })
        await channel.connect()

        # Or use convenience function
        await run_cli_session(agent_callback)
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        auth_manager: AuthorizationManager | None = None,
    ) -> None:
        super().__init__(
            ChannelType.CLI,
            config or {},
            auth_manager,
        )

        self._user_id = self.config.get("user_id", "cli_user")
        self._prompt = self.config.get("prompt", "> ")
        self._use_rich = self.config.get("use_rich", True)
        self._session_id = str(uuid4())[:8]

        # Rich console if available
        self._console: Any = None
        self._message_queue: asyncio.Queue[UnifiedMessage] = asyncio.Queue()
        self._input_task: asyncio.Task | None = None

    async def connect(self) -> None:
        """Connect (initialize) the CLI channel."""
        if self._connected:
            return

        # Try to use Rich
        if self._use_rich:
            try:
                from rich.console import Console

                self._console = Console()
            except ImportError:
                self._console = None

        self._connected = True

        # Start input loop
        self._input_task = asyncio.create_task(self._input_loop())

        logger.info("CLI channel connected")

    async def disconnect(self) -> None:
        """Disconnect the CLI channel."""
        if not self._connected:
            return

        if self._input_task:
            self._input_task.cancel()
            try:
                await self._input_task
            except asyncio.CancelledError:
                pass

        self._connected = False
        logger.info("CLI channel disconnected")

    async def send(self, message: OutgoingMessage) -> str | None:
        """Display a message in the terminal."""
        if not self._connected:
            return None

        text = self.format_for_platform(message.content)
        msg_id = str(uuid4())[:8]

        if self._console:
            from rich.markdown import Markdown
            from rich.panel import Panel

            # Use Rich formatting
            if message.content.markdown:
                md = Markdown(text)
                self._console.print(md)
            else:
                self._console.print(text)
        else:
            # Plain text output
            print(f"\n{text}\n")

        return msg_id

    async def receive(self) -> AsyncIterator[UnifiedMessage]:
        """Receive messages from CLI input."""
        while self._connected:
            try:
                message = await asyncio.wait_for(
                    self._message_queue.get(),
                    timeout=0.5,
                )
                yield message
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _input_loop(self) -> None:
        """Read input from terminal."""
        try:
            while self._connected:
                # Read input asynchronously
                line = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._read_input(),
                )

                if line is None:
                    # EOF
                    break

                line = line.strip()
                if not line:
                    continue

                # Check for quit commands
                if line.lower() in ("/quit", "/exit", "/q"):
                    self._connected = False
                    break

                # Determine message type
                msg_type = MessageType.TEXT
                if line.startswith("/"):
                    msg_type = MessageType.COMMAND

                # Create unified message
                message = UnifiedMessage(
                    id=str(uuid4())[:8],
                    channel_type=ChannelType.CLI,
                    channel_id=self._session_id,
                    user_id=self._user_id,
                    username="user",
                    content=MessageContent(
                        text=line,
                        type=msg_type,
                    ),
                    metadata=MessageMetadata(
                        platform_data={"session_id": self._session_id},
                    ),
                )

                await self._message_queue.put(message)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"CLI input error: {e}")

    def _read_input(self) -> str | None:
        """Read a line of input."""
        try:
            if self._console:
                return self._console.input(self._prompt)
            else:
                return input(self._prompt)
        except EOFError:
            return None
        except KeyboardInterrupt:
            return None

    def format_for_platform(self, content: MessageContent) -> str:
        """Format content for terminal display."""
        text = content.text

        # Add code blocks with syntax highlighting markers
        for block in content.code_blocks:
            lang = block.get("language", "")
            code = block.get("code", "")
            text += f"\n```{lang}\n{code}\n```"

        return text

    def print(self, text: str, **kwargs: Any) -> None:
        """Print text to the console."""
        if self._console:
            self._console.print(text, **kwargs)
        else:
            print(text)

    def print_error(self, text: str) -> None:
        """Print an error message."""
        if self._console:
            self._console.print(f"[red]Error:[/red] {text}")
        else:
            print(f"Error: {text}", file=sys.stderr)

    def print_success(self, text: str) -> None:
        """Print a success message."""
        if self._console:
            self._console.print(f"[green]{text}[/green]")
        else:
            print(text)

    async def stream_response(self, text_iterator: AsyncIterator[str]) -> None:
        """Stream a response character by character."""
        if self._console:
            with self._console.status("Thinking..."):
                full_text = ""
                async for chunk in text_iterator:
                    full_text += chunk

            from rich.markdown import Markdown

            self._console.print(Markdown(full_text))
        else:
            async for chunk in text_iterator:
                print(chunk, end="", flush=True)
            print()


async def run_cli_session(
    agent_callback: Any,
    config: dict[str, Any] | None = None,
) -> None:
    """
    Run an interactive CLI session.

    Args:
        agent_callback: Async function (prompt, project_id) -> response
        config: Optional CLI configuration

    Usage:
        async def my_agent(prompt, project_id):
            return f"You said: {prompt}"

        await run_cli_session(my_agent)
    """
    channel = CLIChannel(config)
    await channel.connect()

    channel.print("\nCronAgent CLI\n")
    channel.print("Type /help for commands, /quit to exit\n")

    try:
        async for message in channel.receive():
            # Handle commands
            if message.content.type == MessageType.COMMAND:
                cmd = message.get_command()
                if cmd:
                    command, args = cmd
                    if command == "help":
                        channel.print(
                            "\n**Commands:**\n"
                            "- /help - Show this help\n"
                            "- /quit - Exit the session\n"
                            "- /clear - Clear the screen\n"
                        )
                        continue
                    elif command == "clear":
                        if channel._console:
                            channel._console.clear()
                        continue

            # Call agent
            try:
                channel.print("")  # Newline before response
                response = await agent_callback(
                    message.content.text,
                    None,  # project_id
                )

                if response:
                    await channel.send(
                        OutgoingMessage.reply_to(message, response)
                    )

            except Exception as e:
                channel.print_error(str(e))

    finally:
        await channel.disconnect()
