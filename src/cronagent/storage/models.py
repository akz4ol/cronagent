"""
SQLAlchemy models for CronAgent persistence.

Tables:
- sessions: Conversation sessions
- session_messages: Messages within sessions
- session_insights: Learned insights from sessions
- scheduled_jobs: Scheduled task definitions (Phase 3)
- job_runs: Job execution history (Phase 3)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Session(Base):
    """
    Conversation session model.

    Stores metadata about agent sessions including project context,
    status, and fork relationships.
    """

    __tablename__ = "sessions"

    # Primary key
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Project context
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    project_path: Mapped[str] = mapped_column(Text, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        nullable=False,
    )
    last_active: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Status
    status: Mapped[str] = mapped_column(
        String(20),
        default="active",
        nullable=False,
        index=True,
    )  # active, paused, completed, expired

    # Fork tracking
    parent_session_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("sessions.session_id", ondelete="SET NULL"),
        nullable=True,
    )
    fork_depth: Mapped[int] = mapped_column(Integer, default=0)

    # Metadata (JSON)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSON,
        default=dict,
    )

    # Relationships
    messages: Mapped[list[SessionMessage]] = relationship(
        "SessionMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionMessage.message_index",
    )
    insights: Mapped[list[SessionInsight]] = relationship(
        "SessionInsight",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    children: Mapped[list[Session]] = relationship(
        "Session",
        back_populates="parent",
        remote_side=[session_id],
    )
    parent: Mapped[Session | None] = relationship(
        "Session",
        back_populates="children",
        remote_side=[parent_session_id],
    )

    # Indexes
    __table_args__ = (
        Index("ix_sessions_project_active", "project_id", "last_active"),
        Index("ix_sessions_status_active", "status", "last_active"),
    )

    def __repr__(self) -> str:
        return f"Session(id={self.session_id!r}, project={self.project_id!r}, status={self.status!r})"


class SessionMessage(Base):
    """
    Message within a session.

    Stores the full conversation history including user messages,
    assistant responses, and system messages.
    """

    __tablename__ = "session_messages"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Foreign key to session
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Message ordering
    message_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Content
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )  # user, assistant, system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(20),
        default="text",
    )  # text, tool_use, tool_result

    # Token tracking
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        nullable=False,
    )

    # Additional metadata
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSON,
        default=dict,
    )

    # Relationship
    session: Mapped[Session] = relationship("Session", back_populates="messages")

    # Indexes
    __table_args__ = (
        Index("ix_messages_session_order", "session_id", "message_index"),
    )

    def __repr__(self) -> str:
        return f"SessionMessage(session={self.session_id!r}, index={self.message_index}, role={self.role!r})"


class SessionInsight(Base):
    """
    Learned insight from sessions.

    Stores patterns, preferences, and knowledge extracted from
    conversations for cross-session learning.
    """

    __tablename__ = "session_insights"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Foreign key to origin session
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Insight identification
    insight_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )  # code_pattern, user_preference, error_resolution, project_context
    insight_key: Mapped[str] = mapped_column(String(255), nullable=False)

    # Content
    insight_value: Mapped[str] = mapped_column(Text, nullable=False)

    # Quality metrics
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    usage_count: Mapped[int] = mapped_column(Integer, default=1)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationship
    session: Mapped[Session] = relationship("Session", back_populates="insights")

    # Indexes and constraints
    __table_args__ = (
        Index("ix_insights_type_key", "insight_type", "insight_key"),
        Index("ix_insights_confidence", "confidence"),
    )

    def __repr__(self) -> str:
        return f"SessionInsight(type={self.insight_type!r}, key={self.insight_key!r})"


class ScheduledJob(Base):
    """
    Scheduled job definition (Phase 3).

    Stores task definitions for cron/interval scheduling.
    """

    __tablename__ = "scheduled_jobs"

    # Primary key
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Schedule configuration (JSON)
    schedule_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )  # cron, interval, one_time, dependent
    schedule_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Execution configuration (JSON)
    execution_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )  # claude_prompt, script, webhook
    execution_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Retry configuration (JSON)
    retry_config: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default={"max_attempts": 3, "backoff_type": "exponential", "delay": 60},
    )

    # Notification configuration (JSON)
    notification_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Status
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Statistics
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)

    # Tags and category
    tags: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relationships
    runs: Mapped[list[JobRun]] = relationship(
        "JobRun",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobRun.started_at.desc()",
    )

    def __repr__(self) -> str:
        return f"ScheduledJob(id={self.id!r}, name={self.name!r}, enabled={self.enabled})"


class JobRun(Base):
    """
    Job execution history (Phase 3).

    Records each execution attempt of a scheduled job.
    """

    __tablename__ = "job_runs"

    # Primary key
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Foreign key to job
    job_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("scheduled_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Execution details
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )  # pending, running, success, failure, timeout, cancelled
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Retry tracking
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)

    # Output and errors
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Trigger information
    triggered_by: Mapped[str] = mapped_column(
        String(20),
        default="schedule",
    )  # schedule, manual, webhook, dependency
    triggered_by_user: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Parent run (for dependent jobs)
    parent_run_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("job_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Cost tracking
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationship
    job: Mapped[ScheduledJob] = relationship("ScheduledJob", back_populates="runs")

    # Indexes (note: status already indexed via index=True)
    __table_args__ = (
        Index("ix_job_runs_job_started", "job_id", "started_at"),
    )

    def __repr__(self) -> str:
        return f"JobRun(id={self.id!r}, job={self.job_id!r}, status={self.status!r})"
