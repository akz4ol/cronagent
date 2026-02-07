"""
Agent context management for multi-turn conversations.

Tracks conversation history, working state, and provides context
summarization for long conversations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ConversationTurn:
    """Single turn in a conversation."""

    role: str  # "user" | "assistant" | "system"
    content: str | list[dict[str, Any]]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationTurn:
        """Create from dictionary."""
        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            metadata=data.get("metadata", {}),
        )


@dataclass
class AgentContext:
    """
    Manages context for agent conversations.

    Tracks:
    - Conversation history with token estimation
    - Working state variables
    - Project/session context

    Provides:
    - History truncation for context window limits
    - Serialization for persistence
    - Context formatting for Claude API
    """

    session_id: str
    project_id: str
    project_path: str
    conversation_history: list[ConversationTurn] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    max_history_turns: int = 50
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_active: datetime = field(default_factory=datetime.utcnow)

    def add_turn(
        self,
        role: str,
        content: str | list[dict[str, Any]],
        **metadata: Any,
    ) -> ConversationTurn:
        """
        Add a conversation turn.

        Args:
            role: Message role (user, assistant, system)
            content: Message content
            **metadata: Additional metadata

        Returns:
            The created turn
        """
        turn = ConversationTurn(role=role, content=content, metadata=metadata)
        self.conversation_history.append(turn)
        self.last_active = datetime.utcnow()

        # Trim history if needed
        if len(self.conversation_history) > self.max_history_turns:
            self.conversation_history = self.conversation_history[-self.max_history_turns :]

        return turn

    def add_user_message(self, content: str, **metadata: Any) -> ConversationTurn:
        """Add a user message."""
        return self.add_turn("user", content, **metadata)

    def add_assistant_message(
        self,
        content: str | list[dict[str, Any]],
        **metadata: Any,
    ) -> ConversationTurn:
        """Add an assistant message."""
        return self.add_turn("assistant", content, **metadata)

    def add_system_message(self, content: str, **metadata: Any) -> ConversationTurn:
        """Add a system message."""
        return self.add_turn("system", content, **metadata)

    def get_recent_context(self, turns: int = 5) -> str:
        """Get recent conversation as formatted string."""
        recent = self.conversation_history[-turns:]
        lines = []
        for turn in recent:
            content = turn.content
            if isinstance(content, list):
                # Extract text from content blocks
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                content = " ".join(text_parts)
            lines.append(f"[{turn.role}]: {content[:200]}...")
        return "\n".join(lines)

    def get_messages_for_api(
        self,
        max_tokens: int | None = None,
        include_system: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Get conversation history formatted for Claude API.

        Args:
            max_tokens: Maximum estimated tokens (truncates from beginning)
            include_system: Whether to include system messages

        Returns:
            List of message dicts in Claude API format
        """
        messages = self.conversation_history
        if not include_system:
            messages = [m for m in messages if m.role != "system"]

        # Apply token limit with smart truncation
        if max_tokens:
            messages = self._truncate_for_tokens(messages, max_tokens)

        return [{"role": m.role, "content": m.content} for m in messages]

    def _truncate_for_tokens(
        self,
        messages: list[ConversationTurn],
        max_tokens: int,
    ) -> list[ConversationTurn]:
        """
        Truncate messages to fit within token limit.

        Strategy:
        1. Always keep first 2 and last 10 messages
        2. Insert summary marker for middle section
        3. Prioritize recent context
        """
        total = sum(self._estimate_tokens(m.content) for m in messages)
        if total <= max_tokens:
            return messages

        # Keep first 2 and last 10 messages minimum
        keep_first = min(2, len(messages))
        keep_last = min(10, len(messages) // 2)

        if len(messages) <= keep_first + keep_last:
            return messages

        result = messages[:keep_first]
        omitted_count = len(messages) - keep_first - keep_last
        result.append(
            ConversationTurn(
                role="system",
                content=f"[{omitted_count} messages omitted for context window]",
            )
        )
        result.extend(messages[-keep_last:])

        return result

    @staticmethod
    def _estimate_tokens(content: str | list[Any]) -> int:
        """Rough token estimation (4 chars ~= 1 token)."""
        if isinstance(content, str):
            return len(content) // 4
        return sum(len(json.dumps(block)) // 4 for block in content)

    @property
    def total_tokens(self) -> int:
        """Estimate total tokens in conversation."""
        return sum(self._estimate_tokens(m.content) for m in self.conversation_history)

    def set_variable(self, key: str, value: Any) -> None:
        """Set a context variable."""
        self.variables[key] = value

    def get_variable(self, key: str, default: Any = None) -> Any:
        """Get a context variable."""
        return self.variables.get(key, default)

    def clear_variables(self) -> None:
        """Clear all context variables."""
        self.variables.clear()

    def to_dict(self) -> dict[str, Any]:
        """Serialize context for persistence."""
        return {
            "session_id": self.session_id,
            "project_id": self.project_id,
            "project_path": self.project_path,
            "conversation_history": [t.to_dict() for t in self.conversation_history],
            "variables": self.variables,
            "max_history_turns": self.max_history_turns,
            "created_at": self.created_at.isoformat(),
            "last_active": self.last_active.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentContext:
        """Deserialize context from persistence."""
        context = cls(
            session_id=data["session_id"],
            project_id=data["project_id"],
            project_path=data["project_path"],
            conversation_history=[
                ConversationTurn.from_dict(t) for t in data.get("conversation_history", [])
            ],
            variables=data.get("variables", {}),
            max_history_turns=data.get("max_history_turns", 50),
        )
        if "created_at" in data:
            context.created_at = datetime.fromisoformat(data["created_at"])
        if "last_active" in data:
            context.last_active = datetime.fromisoformat(data["last_active"])
        return context

    def fork(self, new_session_id: str) -> AgentContext:
        """
        Create a fork of this context with a new session ID.

        Useful for exploring alternative conversation paths.
        """
        forked = AgentContext(
            session_id=new_session_id,
            project_id=self.project_id,
            project_path=self.project_path,
            conversation_history=self.conversation_history.copy(),
            variables=self.variables.copy(),
            max_history_turns=self.max_history_turns,
        )
        forked.set_variable("forked_from", self.session_id)
        return forked
