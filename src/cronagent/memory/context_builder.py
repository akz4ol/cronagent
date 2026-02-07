"""
Context builder for assembling prompt context from memory.

Combines:
- Project context (CLAUDE.md)
- Session history
- Knowledge base search results
- Insights and preferences
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from cronagent.config import MemoryConfig
from cronagent.memory.knowledge_base import KnowledgeBase, SearchResult, SourceType
from cronagent.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


@dataclass
class ContextSection:
    """A section of context with metadata."""

    title: str
    content: str
    source: str
    priority: int = 0  # Higher = more important
    token_estimate: int = 0

    def __post_init__(self) -> None:
        if not self.token_estimate:
            self.token_estimate = len(self.content) // 4


@dataclass
class AssembledContext:
    """Complete assembled context for a prompt."""

    sections: list[ContextSection] = field(default_factory=list)
    total_tokens: int = 0
    truncated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_string(self, include_headers: bool = True) -> str:
        """Convert assembled context to string for prompt injection."""
        parts = []
        for section in sorted(self.sections, key=lambda s: -s.priority):
            if include_headers:
                parts.append(f"## {section.title}\n{section.content}")
            else:
                parts.append(section.content)
        return "\n\n".join(parts)

    def add_section(self, section: ContextSection) -> None:
        """Add a section and update total tokens."""
        self.sections.append(section)
        self.total_tokens += section.token_estimate


class ContextBuilder:
    """
    Builds context for agent prompts by combining multiple sources.

    Sources:
    - CLAUDE.md project context (highest priority)
    - Session history (recent messages)
    - Knowledge base search (semantic search)
    - Insights (learned patterns and preferences)

    Usage:
        builder = ContextBuilder(memory_manager, knowledge_base, config)

        # For a new prompt, build relevant context
        context = await builder.build_context(
            project_id="my-project",
            query="implement authentication",
            session_id=session_id,
            max_tokens=4000,
        )

        # Inject into prompt
        full_prompt = f"{context.to_string()}\n\nUser: {user_message}"
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        knowledge_base: KnowledgeBase | None = None,
        config: MemoryConfig | None = None,
    ) -> None:
        self.memory = memory_manager
        self.knowledge = knowledge_base
        self.config = config or MemoryConfig()

        # Token budget allocation (percentages)
        self._budgets = {
            "project_context": 0.25,  # CLAUDE.md, project guidelines
            "session_history": 0.35,  # Recent conversation
            "knowledge": 0.25,  # Relevant code/docs
            "insights": 0.15,  # Learned patterns
        }

    async def build_context(
        self,
        project_id: str,
        query: str | None = None,
        session_id: str | None = None,
        max_tokens: int = 4000,
        include_history: bool = True,
        include_knowledge: bool = True,
        include_insights: bool = True,
    ) -> AssembledContext:
        """
        Build assembled context for a prompt.

        Args:
            project_id: Project identifier
            query: Current query for semantic search
            session_id: Session for history retrieval
            max_tokens: Maximum context tokens
            include_history: Include session history
            include_knowledge: Include knowledge base results
            include_insights: Include learned insights

        Returns:
            AssembledContext ready for prompt injection
        """
        context = AssembledContext()

        # Calculate token budgets
        budgets = {
            k: int(v * max_tokens) for k, v in self._budgets.items()
        }

        # 1. Project context (CLAUDE.md) - highest priority
        project_context = await self._get_project_context(
            project_id,
            budgets["project_context"],
        )
        if project_context:
            context.add_section(project_context)

        # 2. Session history
        if include_history and session_id:
            history = await self._get_session_history(
                session_id,
                budgets["session_history"],
            )
            if history:
                context.add_section(history)

        # 3. Knowledge base search
        if include_knowledge and query and self.knowledge:
            knowledge = await self._get_relevant_knowledge(
                project_id,
                query,
                budgets["knowledge"],
            )
            if knowledge:
                context.add_section(knowledge)

        # 4. Insights
        if include_insights:
            insights = await self._get_insights(
                project_id,
                budgets["insights"],
            )
            if insights:
                context.add_section(insights)

        # Check if truncated
        context.truncated = context.total_tokens > max_tokens

        # Add metadata
        context.metadata = {
            "project_id": project_id,
            "session_id": session_id,
            "query": query,
            "max_tokens": max_tokens,
            "sections_count": len(context.sections),
        }

        logger.debug(
            f"Built context: {len(context.sections)} sections, "
            f"~{context.total_tokens} tokens"
        )

        return context

    async def _get_project_context(
        self,
        project_id: str,
        max_tokens: int,
    ) -> ContextSection | None:
        """Get CLAUDE.md and project-level context."""
        if not self.knowledge:
            return None

        # Search for CLAUDE.md content
        results = await self.knowledge.search(
            query="project configuration guidelines conventions",
            project_id=project_id,
            limit=2,
            source_types=[SourceType.CLAUDE_MD],
            min_similarity=0.3,
        )

        if not results:
            return None

        content = self._format_search_results(results, max_tokens)
        if not content:
            return None

        return ContextSection(
            title="Project Guidelines",
            content=content,
            source="CLAUDE.md",
            priority=100,  # Highest priority
        )

    async def _get_session_history(
        self,
        session_id: str,
        max_tokens: int,
    ) -> ContextSection | None:
        """Get recent session history."""
        messages = await self.memory.get_messages(
            session_id,
            limit=20,  # Last 20 messages
            include_system=False,
        )

        if not messages:
            return None

        # Format messages for context
        formatted = []
        current_tokens = 0

        # Work backwards from most recent
        for msg in reversed(messages):
            role = msg["role"].capitalize()
            content = msg["content"]
            if isinstance(content, list):
                # Handle content blocks
                content = " ".join(
                    block.get("text", "") for block in content
                    if isinstance(block, dict) and "text" in block
                )

            # Truncate long messages
            if len(content) > 1000:
                content = content[:1000] + "..."

            line = f"{role}: {content}"
            line_tokens = len(line) // 4

            if current_tokens + line_tokens > max_tokens:
                break

            formatted.insert(0, line)
            current_tokens += line_tokens

        if not formatted:
            return None

        return ContextSection(
            title="Recent Conversation",
            content="\n\n".join(formatted),
            source="session_history",
            priority=80,
        )

    async def _get_relevant_knowledge(
        self,
        project_id: str,
        query: str,
        max_tokens: int,
    ) -> ContextSection | None:
        """Search knowledge base for relevant content."""
        if not self.knowledge:
            return None

        results = await self.knowledge.search(
            query=query,
            project_id=project_id,
            limit=5,
            source_types=[SourceType.CODE, SourceType.DOCUMENTATION],
            min_similarity=0.5,
        )

        if not results:
            return None

        content = self._format_search_results(results, max_tokens)
        if not content:
            return None

        return ContextSection(
            title="Relevant Code & Documentation",
            content=content,
            source="knowledge_base",
            priority=60,
        )

    async def _get_insights(
        self,
        project_id: str,
        max_tokens: int,
    ) -> ContextSection | None:
        """Get learned insights for the project."""
        insights = await self.memory.get_insights(
            project_id=project_id,
            limit=10,
        )

        if not insights:
            return None

        # Format insights
        formatted = []
        current_tokens = 0

        for insight in insights:
            line = f"- **{insight.insight_type}**: {insight.insight_value}"
            line_tokens = len(line) // 4

            if current_tokens + line_tokens > max_tokens:
                break

            formatted.append(line)
            current_tokens += line_tokens

        if not formatted:
            return None

        return ContextSection(
            title="Learned Patterns & Preferences",
            content="\n".join(formatted),
            source="insights",
            priority=40,
        )

    def _format_search_results(
        self,
        results: list[SearchResult],
        max_tokens: int,
    ) -> str:
        """Format search results into context string."""
        formatted = []
        current_tokens = 0

        for result in results:
            # Build result section
            header = result.chunk.file_path or "Knowledge"
            content = result.chunk.content

            # Truncate if needed
            available = max_tokens - current_tokens - 50  # Buffer for header
            if len(content) // 4 > available:
                max_chars = available * 4
                content = content[:max_chars] + "..."

            section = f"### {header}\n```\n{content}\n```"
            section_tokens = len(section) // 4

            if current_tokens + section_tokens > max_tokens:
                break

            formatted.append(section)
            current_tokens += section_tokens

        return "\n\n".join(formatted)

    async def build_system_prompt(
        self,
        project_id: str,
        base_prompt: str | None = None,
    ) -> str:
        """
        Build a complete system prompt with project context.

        Args:
            project_id: Project identifier
            base_prompt: Base system prompt to enhance

        Returns:
            Complete system prompt string
        """
        parts = []

        # Add base prompt if provided
        if base_prompt:
            parts.append(base_prompt)

        # Get project context
        context = await self.build_context(
            project_id=project_id,
            max_tokens=2000,
            include_history=False,
            include_knowledge=False,
            include_insights=True,
        )

        if context.sections:
            parts.append("\n--- Project Context ---\n")
            parts.append(context.to_string())

        return "\n\n".join(parts)


class ContextCache:
    """
    Cache for expensive context operations.

    Caches:
    - Project context (CLAUDE.md)
    - Frequently accessed knowledge
    """

    def __init__(self, ttl_seconds: int = 300) -> None:
        self.ttl = ttl_seconds
        self._cache: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Any | None:
        """Get cached value if not expired."""
        import time

        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self.ttl:
                return value
            del self._cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        """Set cached value."""
        import time

        self._cache[key] = (value, time.time())

    def invalidate(self, key: str) -> None:
        """Invalidate a cached value."""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cached values."""
        self._cache.clear()
