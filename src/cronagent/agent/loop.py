"""
Main agent loop wrapping Claude SDK or CLI.

This is the core integration point with Claude Code,
managing the conversation lifecycle, tool execution, and event emission.
Integrates with the memory system for session persistence and context retrieval.

Supports two modes:
- SDK mode: Uses ANTHROPIC_API_KEY (costs money per API call)
- CLI mode: Uses Claude Code CLI with OAuth (uses your subscription)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator

from cronagent.agent.context import AgentContext
from cronagent.bus.events import EventBus, Events

if TYPE_CHECKING:
    from cronagent.memory import ContextBuilder, KnowledgeBase, MemoryManager

logger = logging.getLogger(__name__)


@dataclass
class AgentLoopConfig:
    """Configuration for the agent loop."""

    system_prompt: str = ""
    max_turns: int = 50
    permission_mode: str = "acceptEdits"
    working_directory: str = "."
    allowed_tools: list[str] = field(
        default_factory=lambda: [
            "Read",
            "Write",
            "Edit",
            "Bash",
            "Glob",
            "Grep",
            "WebFetch",
            "WebSearch",
            "Task",
        ]
    )
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 8192
    temperature: float | None = None
    env: dict[str, str] = field(default_factory=dict)
    # Use CLI mode (OAuth) instead of SDK (API key)
    # If True, runs `claude` CLI directly using your subscription
    # If False or API key is set, uses SDK with API billing
    use_cli: bool = True  # Default to CLI/OAuth mode


@dataclass
class AgentEvent:
    """Event emitted during agent execution."""

    type: str  # thinking, text, tool_use, tool_result, result, error
    content: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentLoop:
    """
    Main agent loop wrapping ClaudeSDKClient.

    Manages the conversation lifecycle, tool execution,
    and integrates with:
    - Skill system via MCP servers
    - Memory system for session persistence
    - Knowledge base for context retrieval

    Usage:
        config = AgentLoopConfig(working_directory="/path/to/project")
        loop = AgentLoop(config, event_bus=bus)

        async for event in loop.execute("Explain the codebase structure"):
            if event.type == "text":
                print(event.content)
            elif event.type == "result":
                print(f"Done! Cost: ${event.metadata.get('cost_usd', 0):.4f}")

    With memory system:
        loop = AgentLoop(
            config,
            memory_manager=memory,
            knowledge_base=kb,
            context_builder=builder,
        )

        # Start persistent session
        session = await loop.start_session(project_id="my-project")

        async for event in loop.execute("Explain the codebase"):
            ...

        # Resume later
        await loop.resume_session(session_id)
    """

    def __init__(
        self,
        config: AgentLoopConfig,
        event_bus: EventBus | None = None,
        skill_registry: Any | None = None,  # SkillRegistry, imported when needed
        memory_manager: MemoryManager | None = None,
        knowledge_base: KnowledgeBase | None = None,
        context_builder: ContextBuilder | None = None,
    ) -> None:
        self.config = config
        self.event_bus = event_bus
        self.skill_registry = skill_registry

        # Memory system components
        self.memory = memory_manager
        self.knowledge = knowledge_base
        self.context_builder = context_builder

        # Session state
        self._session_id: str | None = None
        self._project_id: str | None = None
        self._db_session_id: str | None = None  # Database session ID
        self._context: AgentContext | None = None

    def _build_system_prompt(self) -> str:
        """Construct system prompt with skill documentation."""
        parts = []

        if self.config.system_prompt:
            parts.append(self.config.system_prompt)

        # Add skill documentation if available
        if self.skill_registry:
            skill_docs = self.skill_registry.get_documentation()
            if skill_docs:
                parts.append(skill_docs)

        return "\n\n".join(parts) if parts else ""

    def _collect_allowed_tools(self) -> list[str]:
        """Collect built-in tools + skill tools."""
        tools = list(self.config.allowed_tools)

        # Add skill tools if available
        if self.skill_registry:
            tools.extend(self.skill_registry.get_tool_names())

        return tools

    def _merge_environment(self) -> dict[str, str]:
        """
        Merge config env with system env for auth passthrough.

        This allows CLI authorizations (GITHUB_TOKEN, AWS_*, etc.)
        to be available to Claude for tool execution.
        """
        # Start with relevant system env vars for auth
        auth_prefixes = (
            "GITHUB_",
            "GH_",
            "AWS_",
            "DOCKER_",
            "ANTHROPIC_",
            "OPENAI_",
            "DEPLOY_",
            "NPM_",
            "PYPI_",
        )
        env = {k: v for k, v in os.environ.items() if k.startswith(auth_prefixes)}

        # Override with config-specific env
        env.update(self.config.env)

        return env

    def _get_mcp_servers(self) -> dict[str, Any]:
        """Get MCP server configurations from skill registry."""
        if self.skill_registry:
            return self.skill_registry.as_mcp_servers()
        return {}

    async def execute(
        self,
        prompt: str,
        use_memory_context: bool = True,
    ) -> AsyncIterator[AgentEvent]:
        """
        Execute a prompt and yield events.

        Yields structured events for progress tracking:
        - AgentEvent(type="thinking", content="...")
        - AgentEvent(type="text", content="...")
        - AgentEvent(type="tool_use", content={"tool": "...", "input": {...}})
        - AgentEvent(type="tool_result", content="...")
        - AgentEvent(type="result", metadata={"success": bool, "cost_usd": float, ...})
        - AgentEvent(type="error", content="...")

        Args:
            prompt: The user's prompt
            use_memory_context: Whether to inject context from memory/knowledge base

        Yields:
            AgentEvent objects
        """
        # Persist user message if session active
        await self._persist_message("user", prompt)

        # Emit start event
        if self.event_bus:
            await self.event_bus.emit(Events.AGENT_STARTED, {"prompt": prompt})

        # Build enhanced system prompt with project context
        system_prompt = await self._enhance_system_prompt()

        # Optionally enhance the prompt with context
        effective_prompt = prompt
        if use_memory_context and self.context_builder and self._project_id:
            effective_prompt = await self._build_enhanced_prompt(prompt)

        # Determine execution mode: CLI (OAuth) vs SDK (API key)
        # Prefer CLI mode when available (uses subscription, no API costs)
        cli_available = shutil.which("claude") is not None
        use_cli = self.config.use_cli and cli_available

        # Execute query
        result_text = ""
        cost_usd = 0.0
        session_id = None
        is_error = False

        try:
            logger.info(f"Executing query with prompt: {prompt[:100]}... (CLI mode: {use_cli})")

            if use_cli:
                # CLI mode - use OAuth via `claude` command
                async for event in self._execute_via_cli(effective_prompt, system_prompt):
                    yield event

                    if event.type == "text":
                        result_text += event.content
                    elif event.type == "result":
                        session_id = event.metadata.get("session_id")
                        is_error = event.metadata.get("is_error", False)

                    if self.event_bus:
                        await self._emit_event(event)
            else:
                # SDK mode - use API key
                async for event in self._execute_via_sdk(effective_prompt, system_prompt):
                    yield event

                    if event.type == "text":
                        result_text += event.content
                    elif event.type == "result":
                        cost_usd = event.metadata.get("cost_usd", 0)
                        session_id = event.metadata.get("session_id")
                        is_error = event.metadata.get("is_error", False)

                    if self.event_bus:
                        await self._emit_event(event)

        except Exception as e:
            logger.error(f"Agent execution error: {e}", exc_info=True)
            yield AgentEvent(type="error", content=str(e))
            is_error = True

            if self.event_bus:
                await self.event_bus.emit(Events.AGENT_ERROR, {"error": str(e)})

        # Store session ID for resume
        self._session_id = session_id

        # Persist assistant response
        if result_text:
            await self._persist_message(
                "assistant",
                result_text,
                metadata={"cost_usd": cost_usd, "sdk_session_id": session_id},
            )

        # Emit completion
        if self.event_bus:
            await self.event_bus.emit(
                Events.AGENT_COMPLETED,
                {
                    "success": not is_error,
                    "cost_usd": cost_usd,
                    "session_id": session_id,
                    "db_session_id": self._db_session_id,
                    "result_length": len(result_text),
                },
            )

    async def _execute_via_cli(
        self,
        prompt: str,
        system_prompt: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """
        Execute via Claude Code CLI (uses OAuth - your subscription).

        Runs `claude -p "prompt" --output-format stream-json` and parses output.
        """
        # Check if claude CLI is available
        claude_path = shutil.which("claude")
        if not claude_path:
            yield AgentEvent(
                type="error",
                content="Claude Code CLI not found. Install from: https://claude.ai/code",
            )
            return

        # Build command
        cmd = [
            claude_path,
            "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",
        ]

        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        # Note: --dangerously-skip-permissions may not work in all contexts
        # For scheduled jobs, we rely on the user having pre-approved permissions

        if self.config.max_turns:
            cmd.extend(["--max-turns", str(self.config.max_turns)])

        logger.info(f"Running CLI command: {cmd}")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout
                cwd=self.config.working_directory,
            )

            session_id = None
            result_text = ""

            # Read stdout line by line
            async for line_bytes in process.stdout:
                line = line_bytes.decode().strip()
                if not line:
                    continue

                logger.debug(f"CLI output: {line[:200]}")

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(f"Non-JSON line from CLI: {line[:100]}")
                    continue

                msg_type = data.get("type")

                if msg_type == "system" and data.get("subtype") == "init":
                    session_id = data.get("session_id")
                    logger.info(f"CLI session started: {session_id}")

                elif msg_type == "assistant":
                    # Text content from assistant
                    content = data.get("message", {}).get("content", [])
                    for block in content:
                        if block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                result_text += text
                                yield AgentEvent(type="text", content=text)
                        elif block.get("type") == "tool_use":
                            yield AgentEvent(
                                type="tool_use",
                                content={"tool": block.get("name"), "input": block.get("input")},
                                metadata={"tool": block.get("name"), "input": block.get("input")},
                            )

                elif msg_type == "result":
                    # Get result text from the result message if we didn't capture it
                    if not result_text:
                        result_text = data.get("result", "")
                        if result_text:
                            yield AgentEvent(type="text", content=result_text)

                    yield AgentEvent(
                        type="result",
                        metadata={
                            "success": not data.get("is_error", False),
                            "is_error": data.get("is_error", False),
                            "session_id": session_id,
                            "duration_ms": data.get("duration_ms", 0),
                            "cost_usd": data.get("total_cost_usd", 0),
                        },
                    )

            await process.wait()
            logger.info(f"CLI process completed with return code: {process.returncode}")

        except Exception as e:
            logger.error(f"CLI execution error: {e}", exc_info=True)
            yield AgentEvent(type="error", content=str(e))

    async def _execute_via_sdk(
        self,
        prompt: str,
        system_prompt: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """
        Execute via Claude Code SDK (uses API key - pay per call).
        """
        try:
            from claude_code_sdk import ClaudeCodeOptions, query
        except ImportError:
            yield AgentEvent(
                type="error",
                content="claude-code-sdk not installed. Install with: pip install claude-code-sdk",
            )
            return

        options = ClaudeCodeOptions(
            system_prompt=system_prompt or None,
            allowed_tools=self._collect_allowed_tools(),
            permission_mode=self.config.permission_mode,
            cwd=self.config.working_directory,
            max_turns=self.config.max_turns,
            model=self.config.model,
        )

        async for message in query(prompt=prompt, options=options):
            events = self._process_sdk_message(message)
            for event in events:
                yield event

    def _process_sdk_message(self, message: Any) -> list[AgentEvent]:
        """Process a message from the SDK and convert to AgentEvents."""
        events = []

        # Get message class name to determine type
        msg_class = message.__class__.__name__
        logger.debug(f"Processing SDK message: class={msg_class}, message={message}")

        if msg_class == "AssistantMessage":
            # Assistant message with content blocks
            content = getattr(message, "content", [])
            for block in content:
                block_class = block.__class__.__name__
                if block_class == "TextBlock":
                    text_content = getattr(block, "text", "")
                    if text_content:
                        events.append(AgentEvent(type="text", content=text_content))
                elif block_class == "ToolUseBlock":
                    events.append(
                        AgentEvent(
                            type="tool_use",
                            content={
                                "tool": getattr(block, "name", ""),
                                "input": getattr(block, "input", {}),
                            },
                            metadata={
                                "tool": getattr(block, "name", ""),
                                "input": getattr(block, "input", {}),
                            },
                        )
                    )

        elif msg_class == "ResultMessage":
            # Final result message
            events.append(
                AgentEvent(
                    type="result",
                    metadata={
                        "success": not getattr(message, "is_error", False),
                        "is_error": getattr(message, "is_error", False),
                        "cost_usd": getattr(message, "total_cost_usd", 0),
                        "duration_ms": getattr(message, "duration_ms", 0),
                        "session_id": getattr(message, "session_id", None),
                    },
                )
            )

        elif msg_class == "SystemMessage":
            # System message (init, progress, etc.)
            subtype = getattr(message, "subtype", None)
            if subtype == "init":
                # Capture session ID from init
                self._session_id = getattr(message, "session_id", None)

        return events

    async def _emit_event(self, event: AgentEvent) -> None:
        """Emit agent event to event bus."""
        if not self.event_bus:
            return

        event_map = {
            "text": Events.AGENT_MESSAGE,
            "tool_use": Events.AGENT_TOOL_USE,
            "tool_result": Events.AGENT_TOOL_RESULT,
            "error": Events.AGENT_ERROR,
        }

        bus_event = event_map.get(event.type)
        if bus_event:
            await self.event_bus.emit(bus_event, {"event": event})

    async def execute_with_context(
        self,
        prompt: str,
        context: AgentContext,
    ) -> AsyncIterator[AgentEvent]:
        """
        Execute with an existing context.

        This allows resuming conversations with full history.
        """
        self._context = context

        # Add user message to context
        context.add_user_message(prompt)

        # Execute and track assistant response
        result_parts = []

        async for event in self.execute(prompt):
            yield event

            if event.type == "text":
                result_parts.append(event.content)

        # Add assistant response to context
        if result_parts:
            context.add_assistant_message("".join(result_parts))

    @property
    def session_id(self) -> str | None:
        """Get the current session ID (set after execution)."""
        return self._session_id

    @property
    def db_session_id(self) -> str | None:
        """Get the database session ID for persistence."""
        return self._db_session_id

    async def start_session(
        self,
        project_id: str,
        project_path: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """
        Start a persistent session.

        Args:
            project_id: Project identifier
            project_path: Path to project root (defaults to working_directory)
            session_id: Optional predefined session ID

        Returns:
            Session ID
        """
        if not self.memory:
            raise RuntimeError("Memory manager required for session persistence")

        project_path = project_path or self.config.working_directory
        session = await self.memory.create_session(
            project_id=project_id,
            project_path=project_path,
            session_id=session_id,
        )

        self._db_session_id = session.session_id
        self._project_id = project_id

        logger.info(f"Started session {session.session_id} for project {project_id}")

        if self.event_bus:
            await self.event_bus.emit(
                Events.SESSION_CREATED,
                {
                    "session_id": session.session_id,
                    "project_id": project_id,
                },
            )

        return session.session_id

    async def resume_session(
        self,
        session_id: str,
        fork: bool = False,
    ) -> str | None:
        """
        Resume an existing session.

        Args:
            session_id: Session to resume
            fork: If True, create a new branch from this session

        Returns:
            Session ID (new ID if forked), or None if not found
        """
        if not self.memory:
            raise RuntimeError("Memory manager required for session persistence")

        session = await self.memory.resume_session(session_id, fork=fork)
        if not session:
            return None

        self._db_session_id = session.session_id
        self._project_id = session.project_id

        logger.info(f"Resumed session {session.session_id}")

        return session.session_id

    async def complete_session(self) -> None:
        """Mark the current session as completed."""
        if not self.memory or not self._db_session_id:
            return

        await self.memory.complete_session(self._db_session_id)
        logger.info(f"Completed session {self._db_session_id}")

        self._db_session_id = None
        self._project_id = None

    async def _persist_message(
        self,
        role: str,
        content: str,
        content_type: str = "text",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist a message to the session."""
        if not self.memory or not self._db_session_id:
            return

        await self.memory.add_message(
            session_id=self._db_session_id,
            role=role,
            content=content,
            content_type=content_type,
            metadata=metadata,
        )

    async def _build_enhanced_prompt(self, prompt: str) -> str:
        """
        Enhance prompt with context from memory/knowledge base.

        Returns the prompt with injected context if available.
        """
        if not self.context_builder or not self._project_id:
            return prompt

        # Build context
        context = await self.context_builder.build_context(
            project_id=self._project_id,
            query=prompt,
            session_id=self._db_session_id,
            max_tokens=4000,
        )

        if context.sections:
            context_str = context.to_string()
            return f"{context_str}\n\n---\n\nUser Request: {prompt}"

        return prompt

    async def _enhance_system_prompt(self) -> str:
        """Build system prompt with project context."""
        base_prompt = self._build_system_prompt()

        if self.context_builder and self._project_id:
            return await self.context_builder.build_system_prompt(
                project_id=self._project_id,
                base_prompt=base_prompt,
            )

        return base_prompt

    async def save_insight(
        self,
        insight_type: str,
        insight_key: str,
        insight_value: str,
        confidence: float = 1.0,
    ) -> None:
        """
        Save an insight from the current session.

        Args:
            insight_type: Type (code_pattern, user_preference, etc.)
            insight_key: Unique key within type
            insight_value: Insight content
            confidence: Confidence score (0-1)
        """
        if not self.memory or not self._db_session_id:
            return

        await self.memory.save_insight(
            session_id=self._db_session_id,
            insight_type=insight_type,
            insight_key=insight_key,
            insight_value=insight_value,
            confidence=confidence,
        )

    async def index_current_project(self) -> dict[str, int]:
        """
        Index the current project into the knowledge base.

        Returns:
            Statistics dict with indexed, skipped, errors counts
        """
        if not self.knowledge or not self._project_id:
            return {"indexed": 0, "skipped": 0, "errors": 0}

        return await self.knowledge.index_directory(
            directory=self.config.working_directory,
            project_id=self._project_id,
        )


async def run_agent_task(
    prompt: str,
    working_directory: str = ".",
    model: str = "claude-sonnet-4-20250514",
    event_bus: EventBus | None = None,
    memory_manager: MemoryManager | None = None,
    knowledge_base: KnowledgeBase | None = None,
    project_id: str | None = None,
) -> str:
    """
    Convenience function to run a single agent task.

    Args:
        prompt: The task prompt
        working_directory: Directory to work in
        model: Claude model to use
        event_bus: Optional event bus
        memory_manager: Optional memory manager for persistence
        knowledge_base: Optional knowledge base for context
        project_id: Optional project ID for context retrieval

    Returns:
        The agent's text response
    """
    from cronagent.memory import ContextBuilder

    config = AgentLoopConfig(
        working_directory=working_directory,
        model=model,
    )

    # Build context builder if memory components provided
    context_builder = None
    if memory_manager and knowledge_base:
        context_builder = ContextBuilder(memory_manager, knowledge_base)

    loop = AgentLoop(
        config,
        event_bus=event_bus,
        memory_manager=memory_manager,
        knowledge_base=knowledge_base,
        context_builder=context_builder,
    )

    # Start session if memory enabled
    if memory_manager and project_id:
        await loop.start_session(project_id, working_directory)

    result_parts = []
    async for event in loop.execute(prompt):
        if event.type == "text":
            result_parts.append(event.content)
        elif event.type == "error":
            raise RuntimeError(event.content)

    # Complete session
    if memory_manager:
        await loop.complete_session()

    return "".join(result_parts)


async def create_agent_with_memory(
    config: AgentLoopConfig,
    memory_config: Any | None = None,  # MemoryConfig
    event_bus: EventBus | None = None,
) -> AgentLoop:
    """
    Create an AgentLoop with full memory system initialized.

    Args:
        config: Agent loop configuration
        memory_config: Memory configuration (from CronAgentConfig)
        event_bus: Optional event bus

    Returns:
        Fully initialized AgentLoop with memory
    """
    from cronagent.config import MemoryConfig
    from cronagent.memory import ContextBuilder, KnowledgeBase, MemoryManager
    from cronagent.storage import Database

    memory_config = memory_config or MemoryConfig()

    # Initialize database
    db = Database.from_config(memory_config)
    await db.initialize()

    # Create memory components
    memory_manager = MemoryManager(db, memory_config, event_bus)
    knowledge_base = KnowledgeBase(memory_config, event_bus)
    await knowledge_base.initialize()

    context_builder = ContextBuilder(memory_manager, knowledge_base, memory_config)

    return AgentLoop(
        config=config,
        event_bus=event_bus,
        memory_manager=memory_manager,
        knowledge_base=knowledge_base,
        context_builder=context_builder,
    )
