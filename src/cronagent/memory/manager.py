"""
Memory manager for session persistence and cross-session learning.

Handles:
- Session lifecycle (create, resume, fork, complete)
- Message persistence
- Insight extraction and storage
- Context retrieval for prompts
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession as SQLASession

from cronagent.bus.events import EventBus, Events
from cronagent.config import MemoryConfig
from cronagent.storage.database import Database
from cronagent.storage.models import Session, SessionInsight, SessionMessage

logger = logging.getLogger(__name__)


class SessionStatus(str, Enum):
    """Session status values."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    EXPIRED = "expired"


class MemoryManager:
    """
    Central manager for session memory and cross-session learning.

    Responsibilities:
    - Session lifecycle management (create, resume, fork, complete)
    - Message persistence with token tracking
    - Insight extraction and storage
    - Integration with Claude SDK session management

    Usage:
        db = Database.from_config(config.memory)
        await db.initialize()

        manager = MemoryManager(db, config.memory)

        # Create a new session
        session = await manager.create_session(
            project_id="my-project",
            project_path="/path/to/project",
        )

        # Add messages
        await manager.add_message(
            session_id=session.session_id,
            role="user",
            content="Hello",
        )

        # Resume later
        session = await manager.resume_session(session_id)
    """

    def __init__(
        self,
        database: Database,
        config: MemoryConfig,
        event_bus: EventBus | None = None,
    ) -> None:
        self.db = database
        self.config = config
        self.event_bus = event_bus
        self._active_sessions: dict[str, dict[str, Any]] = {}

    async def create_session(
        self,
        project_id: str,
        project_path: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """
        Create a new session.

        Args:
            project_id: Unique project identifier
            project_path: Absolute path to project root
            session_id: Optional predefined session ID
            metadata: Optional session metadata

        Returns:
            New Session model
        """
        session_id = session_id or str(uuid4())
        now = datetime.utcnow()

        async with self.db.session() as db_session:
            session = Session(
                session_id=session_id,
                project_id=project_id,
                project_path=project_path,
                created_at=now,
                last_active=now,
                status=SessionStatus.ACTIVE.value,
                metadata_=metadata or {},
            )
            db_session.add(session)

            # Load project context (CLAUDE.md, etc.)
            initial_context = await self._load_project_context(project_path)
            if initial_context:
                system_msg = SessionMessage(
                    session_id=session_id,
                    message_index=0,
                    role="system",
                    content=initial_context,
                    content_type="text",
                    token_count=len(initial_context) // 4,
                    metadata_={"source": "CLAUDE.md"},
                )
                db_session.add(system_msg)

        # Track in memory
        self._active_sessions[session_id] = {
            "project_id": project_id,
            "project_path": project_path,
            "message_count": 1 if initial_context else 0,
        }

        logger.info(f"Created session {session_id} for project {project_id}")

        if self.event_bus:
            await self.event_bus.emit(
                Events.SESSION_CREATED,
                {
                    "session_id": session_id,
                    "project_id": project_id,
                },
            )

        return session

    async def resume_session(
        self,
        session_id: str,
        fork: bool = False,
    ) -> Session | None:
        """
        Resume an existing session.

        Args:
            session_id: Session to resume
            fork: If True, create a new branch from this session

        Returns:
            Resumed or forked Session, or None if not found
        """
        async with self.db.session() as db_session:
            # Load session
            result = await db_session.execute(
                select(Session).where(Session.session_id == session_id)
            )
            session = result.scalar_one_or_none()

            if not session:
                logger.warning(f"Session not found: {session_id}")
                return None

            if fork:
                # Create forked session
                new_session_id = str(uuid4())

                # Copy session
                forked = Session(
                    session_id=new_session_id,
                    project_id=session.project_id,
                    project_path=session.project_path,
                    status=SessionStatus.ACTIVE.value,
                    parent_session_id=session_id,
                    fork_depth=session.fork_depth + 1,
                    metadata_={
                        **(session.metadata_ or {}),
                        "forked_from": session_id,
                        "forked_at": datetime.utcnow().isoformat(),
                    },
                )
                db_session.add(forked)

                # Copy messages
                msg_result = await db_session.execute(
                    select(SessionMessage)
                    .where(SessionMessage.session_id == session_id)
                    .order_by(SessionMessage.message_index)
                )
                for msg in msg_result.scalars():
                    forked_msg = SessionMessage(
                        session_id=new_session_id,
                        message_index=msg.message_index,
                        role=msg.role,
                        content=msg.content,
                        content_type=msg.content_type,
                        token_count=msg.token_count,
                        metadata_=msg.metadata_,
                    )
                    db_session.add(forked_msg)

                logger.info(f"Forked session {session_id} -> {new_session_id}")

                if self.event_bus:
                    await self.event_bus.emit(
                        Events.SESSION_CREATED,
                        {
                            "session_id": new_session_id,
                            "forked_from": session_id,
                        },
                    )

                return forked

            # Update last active
            session.last_active = datetime.utcnow()
            session.status = SessionStatus.ACTIVE.value

        self._active_sessions[session_id] = {
            "project_id": session.project_id,
            "project_path": session.project_path,
        }

        logger.info(f"Resumed session {session_id}")

        if self.event_bus:
            await self.event_bus.emit(
                Events.SESSION_RESUMED,
                {"session_id": session_id},
            )

        return session

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str | list[dict[str, Any]],
        content_type: str = "text",
        metadata: dict[str, Any] | None = None,
    ) -> SessionMessage:
        """
        Add a message to a session.

        Args:
            session_id: Session to add message to
            role: Message role (user, assistant, system)
            content: Message content (string or content blocks)
            content_type: Content type (text, tool_use, tool_result)
            metadata: Additional metadata

        Returns:
            Created SessionMessage
        """
        # Serialize content if it's a list
        if isinstance(content, list):
            content_str = json.dumps(content)
        else:
            content_str = content

        # Estimate tokens
        token_count = len(content_str) // 4

        async with self.db.session() as db_session:
            # Get next message index
            result = await db_session.execute(
                select(SessionMessage.message_index)
                .where(SessionMessage.session_id == session_id)
                .order_by(SessionMessage.message_index.desc())
                .limit(1)
            )
            last_index = result.scalar_one_or_none()
            next_index = (last_index or -1) + 1

            # Create message
            message = SessionMessage(
                session_id=session_id,
                message_index=next_index,
                role=role,
                content=content_str,
                content_type=content_type,
                token_count=token_count,
                metadata_=metadata or {},
            )
            db_session.add(message)

            # Update session last_active
            await db_session.execute(
                update(Session)
                .where(Session.session_id == session_id)
                .values(last_active=datetime.utcnow())
            )

        logger.debug(f"Added {role} message to session {session_id}")

        return message

    async def get_messages(
        self,
        session_id: str,
        limit: int | None = None,
        include_system: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Get messages from a session.

        Args:
            session_id: Session to get messages from
            limit: Maximum number of messages (from end)
            include_system: Whether to include system messages

        Returns:
            List of message dicts for Claude API
        """
        async with self.db.session() as db_session:
            query = (
                select(SessionMessage)
                .where(SessionMessage.session_id == session_id)
                .order_by(SessionMessage.message_index)
            )

            if not include_system:
                query = query.where(SessionMessage.role != "system")

            result = await db_session.execute(query)
            messages = list(result.scalars())

        if limit and len(messages) > limit:
            messages = messages[-limit:]

        # Format for Claude API
        formatted = []
        for msg in messages:
            content = msg.content
            # Try to parse JSON content blocks
            if msg.content_type != "text":
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    pass

            formatted.append({
                "role": msg.role,
                "content": content,
            })

        return formatted

    async def complete_session(self, session_id: str) -> None:
        """
        Mark a session as completed.

        Extracts final insights and updates status.
        """
        async with self.db.session() as db_session:
            await db_session.execute(
                update(Session)
                .where(Session.session_id == session_id)
                .values(
                    status=SessionStatus.COMPLETED.value,
                    last_active=datetime.utcnow(),
                )
            )

        self._active_sessions.pop(session_id, None)
        logger.info(f"Completed session {session_id}")

        if self.event_bus:
            await self.event_bus.emit(
                Events.SESSION_COMPLETED,
                {"session_id": session_id},
            )

    async def save_insight(
        self,
        session_id: str,
        insight_type: str,
        insight_key: str,
        insight_value: str,
        confidence: float = 1.0,
        expires_at: datetime | None = None,
    ) -> SessionInsight:
        """
        Save or update an insight.

        Args:
            session_id: Origin session
            insight_type: Type (code_pattern, user_preference, etc.)
            insight_key: Unique key within type
            insight_value: Insight content
            confidence: Confidence score (0-1)
            expires_at: Optional expiration time

        Returns:
            Created or updated SessionInsight
        """
        async with self.db.session() as db_session:
            # Check for existing insight
            result = await db_session.execute(
                select(SessionInsight).where(
                    SessionInsight.insight_type == insight_type,
                    SessionInsight.insight_key == insight_key,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing
                existing.insight_value = insight_value
                existing.confidence = max(existing.confidence, confidence)
                existing.usage_count += 1
                existing.updated_at = datetime.utcnow()
                insight = existing
            else:
                # Create new
                insight = SessionInsight(
                    session_id=session_id,
                    insight_type=insight_type,
                    insight_key=insight_key,
                    insight_value=insight_value,
                    confidence=confidence,
                    expires_at=expires_at,
                )
                db_session.add(insight)

        logger.debug(f"Saved insight: {insight_type}/{insight_key}")

        if self.event_bus:
            await self.event_bus.emit(
                Events.INSIGHT_EXTRACTED,
                {
                    "session_id": session_id,
                    "insight_type": insight_type,
                    "insight_key": insight_key,
                },
            )

        return insight

    async def get_insights(
        self,
        project_id: str | None = None,
        insight_type: str | None = None,
        limit: int = 50,
    ) -> list[SessionInsight]:
        """
        Get insights, optionally filtered.

        Args:
            project_id: Filter by project
            insight_type: Filter by type
            limit: Maximum results

        Returns:
            List of SessionInsight models
        """
        async with self.db.session() as db_session:
            query = (
                select(SessionInsight)
                .join(Session)
                .order_by(SessionInsight.confidence.desc(), SessionInsight.usage_count.desc())
                .limit(limit)
            )

            if project_id:
                query = query.where(Session.project_id == project_id)
            if insight_type:
                query = query.where(SessionInsight.insight_type == insight_type)

            result = await db_session.execute(query)
            return list(result.scalars())

    async def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        async with self.db.session() as db_session:
            result = await db_session.execute(
                select(Session).where(Session.session_id == session_id)
            )
            return result.scalar_one_or_none()

    async def list_sessions(
        self,
        project_id: str | None = None,
        status: SessionStatus | None = None,
        limit: int = 50,
    ) -> list[Session]:
        """
        List sessions with optional filters.

        Args:
            project_id: Filter by project
            status: Filter by status
            limit: Maximum results

        Returns:
            List of Session models
        """
        async with self.db.session() as db_session:
            query = select(Session).order_by(Session.last_active.desc()).limit(limit)

            if project_id:
                query = query.where(Session.project_id == project_id)
            if status:
                query = query.where(Session.status == status.value)

            result = await db_session.execute(query)
            return list(result.scalars())

    async def cleanup_expired_sessions(
        self,
        max_age_days: int | None = None,
    ) -> int:
        """
        Clean up old sessions.

        Args:
            max_age_days: Maximum session age (defaults to config)

        Returns:
            Number of sessions deleted
        """
        max_age = max_age_days or self.config.max_session_age_days
        cutoff = datetime.utcnow() - timedelta(days=max_age)

        async with self.db.session() as db_session:
            # Delete old completed/expired sessions
            result = await db_session.execute(
                delete(Session).where(
                    Session.last_active < cutoff,
                    Session.status.in_([
                        SessionStatus.COMPLETED.value,
                        SessionStatus.EXPIRED.value,
                    ]),
                )
            )
            deleted = result.rowcount

            # Mark old active sessions as expired
            await db_session.execute(
                update(Session)
                .where(
                    Session.last_active < cutoff,
                    Session.status == SessionStatus.ACTIVE.value,
                )
                .values(status=SessionStatus.EXPIRED.value)
            )

        logger.info(f"Cleaned up {deleted} expired sessions")
        return deleted

    async def _load_project_context(self, project_path: str) -> str | None:
        """Load CLAUDE.md and other project context files."""
        claude_md_path = Path(project_path) / "CLAUDE.md"

        if claude_md_path.exists():
            try:
                content = claude_md_path.read_text(encoding="utf-8")
                return f"Project Context (CLAUDE.md):\n\n{content}"
            except Exception as e:
                logger.warning(f"Failed to read CLAUDE.md: {e}")

        return None

    def derive_project_id(self, project_path: str) -> str:
        """Derive a project ID from the path."""
        return hashlib.md5(project_path.encode()).hexdigest()[:12]
