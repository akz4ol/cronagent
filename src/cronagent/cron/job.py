"""
Job definitions for scheduled tasks.

Supports:
- Cron expressions (0 9 * * *)
- Interval scheduling (every 15 minutes)
- One-time execution
- Dependent jobs (run after another completes)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class ScheduleType(str, Enum):
    """Types of job schedules."""

    CRON = "cron"  # Cron expression
    INTERVAL = "interval"  # Fixed interval
    ONE_TIME = "one_time"  # Single execution
    DEPENDENT = "dependent"  # Triggered by another job


class ExecutionType(str, Enum):
    """Types of job execution."""

    CLAUDE_PROMPT = "claude_prompt"  # Execute via Claude agent
    SCRIPT = "script"  # Run shell script
    WEBHOOK = "webhook"  # HTTP webhook call
    PYTHON = "python"  # Python function


class JobStatus(str, Enum):
    """Job execution status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class BackoffType(str, Enum):
    """Retry backoff strategies."""

    FIXED = "fixed"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


@dataclass
class CronSchedule:
    """Cron expression schedule."""

    expression: str  # e.g., "0 9 * * *" = 9 AM daily
    timezone: str = "UTC"

    def __post_init__(self) -> None:
        # Validate cron expression
        parts = self.expression.split()
        if len(parts) not in (5, 6):
            raise ValueError(
                f"Invalid cron expression: {self.expression}. "
                "Expected 5 or 6 fields (minute hour day month weekday [second])"
            )


@dataclass
class IntervalSchedule:
    """Fixed interval schedule."""

    seconds: int = 0
    minutes: int = 0
    hours: int = 0
    days: int = 0

    def __post_init__(self) -> None:
        total = self.seconds + self.minutes * 60 + self.hours * 3600 + self.days * 86400
        if total <= 0:
            raise ValueError("Interval must be positive")

    @property
    def total_seconds(self) -> int:
        return self.seconds + self.minutes * 60 + self.hours * 3600 + self.days * 86400

    @classmethod
    def from_seconds(cls, seconds: int) -> IntervalSchedule:
        return cls(seconds=seconds)

    @classmethod
    def from_minutes(cls, minutes: int) -> IntervalSchedule:
        return cls(minutes=minutes)

    @classmethod
    def from_hours(cls, hours: int) -> IntervalSchedule:
        return cls(hours=hours)


@dataclass
class OneTimeSchedule:
    """One-time execution schedule."""

    run_at: datetime

    def __post_init__(self) -> None:
        if self.run_at < datetime.utcnow():
            logger.warning(f"One-time schedule is in the past: {self.run_at}")


@dataclass
class DependentSchedule:
    """Schedule triggered by another job."""

    parent_job_id: str
    trigger_on: list[JobStatus] = field(
        default_factory=lambda: [JobStatus.SUCCESS]
    )
    delay_seconds: int = 0  # Delay after parent completes


@dataclass
class RetryConfig:
    """Configuration for job retries."""

    max_attempts: int = 3
    backoff_type: BackoffType = BackoffType.EXPONENTIAL
    initial_delay: int = 60  # seconds
    max_delay: int = 3600  # seconds
    retry_on: list[JobStatus] = field(
        default_factory=lambda: [JobStatus.FAILURE, JobStatus.TIMEOUT]
    )

    def get_delay(self, attempt: int) -> int:
        """Calculate delay for a given attempt number."""
        if self.backoff_type == BackoffType.FIXED:
            return self.initial_delay
        elif self.backoff_type == BackoffType.LINEAR:
            delay = self.initial_delay * attempt
        else:  # EXPONENTIAL
            delay = self.initial_delay * (2 ** (attempt - 1))

        return min(delay, self.max_delay)


@dataclass
class NotificationConfig:
    """Configuration for job notifications."""

    on_success: list[str] = field(default_factory=list)  # Channel IDs
    on_failure: list[str] = field(default_factory=list)
    on_start: list[str] = field(default_factory=list)
    include_output: bool = True
    include_error: bool = True


@dataclass
class ClaudePromptExecution:
    """Execution config for Claude agent prompts."""

    prompt: str
    system_prompt: str | None = None
    project_path: str | None = None
    max_turns: int = 50
    model: str = "claude-sonnet-4-20250514"
    allowed_tools: list[str] | None = None
    environment: dict[str, str] = field(default_factory=dict)


@dataclass
class ScriptExecution:
    """Execution config for shell scripts."""

    command: str
    working_directory: str = "."
    shell: str = "/bin/bash"
    timeout: int = 300  # seconds
    environment: dict[str, str] = field(default_factory=dict)


@dataclass
class WebhookExecution:
    """Execution config for HTTP webhooks."""

    url: str
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] | str | None = None
    timeout: int = 30  # seconds
    verify_ssl: bool = True


@dataclass
class PythonExecution:
    """Execution config for Python functions."""

    module: str  # e.g., "mypackage.tasks"
    function: str  # e.g., "my_task"
    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class JobDefinition:
    """
    Complete job definition.

    Example usage:
        job = JobDefinition(
            name="Daily Security Scan",
            schedule_type=ScheduleType.CRON,
            schedule=CronSchedule("0 6 * * *"),
            execution_type=ExecutionType.CLAUDE_PROMPT,
            execution=ClaudePromptExecution(
                prompt="Perform security analysis of the codebase",
                project_path="/path/to/project",
            ),
            retry=RetryConfig(max_attempts=3),
            notifications=NotificationConfig(
                on_failure=["slack:#security-alerts"],
            ),
        )
    """

    name: str
    schedule_type: ScheduleType
    schedule: CronSchedule | IntervalSchedule | OneTimeSchedule | DependentSchedule
    execution_type: ExecutionType
    execution: ClaudePromptExecution | ScriptExecution | WebhookExecution | PythonExecution

    # Optional fields
    id: str = field(default_factory=lambda: str(uuid4())[:12])
    description: str = ""
    enabled: bool = True
    paused: bool = False
    tags: list[str] = field(default_factory=list)
    category: str | None = None

    # Retry and notifications
    retry: RetryConfig = field(default_factory=RetryConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)

    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    created_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "schedule_type": self.schedule_type.value,
            "schedule_config": self._schedule_to_dict(),
            "execution_type": self.execution_type.value,
            "execution_config": self._execution_to_dict(),
            "retry_config": {
                "max_attempts": self.retry.max_attempts,
                "backoff_type": self.retry.backoff_type.value,
                "initial_delay": self.retry.initial_delay,
                "max_delay": self.retry.max_delay,
                "retry_on": [s.value for s in self.retry.retry_on],
            },
            "notification_config": {
                "on_success": self.notifications.on_success,
                "on_failure": self.notifications.on_failure,
                "on_start": self.notifications.on_start,
                "include_output": self.notifications.include_output,
                "include_error": self.notifications.include_error,
            },
            "enabled": self.enabled,
            "paused": self.paused,
            "tags": self.tags,
            "category": self.category,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "metadata": self.metadata,
        }

    def _schedule_to_dict(self) -> dict[str, Any]:
        """Convert schedule to dict."""
        if isinstance(self.schedule, CronSchedule):
            return {
                "expression": self.schedule.expression,
                "timezone": self.schedule.timezone,
            }
        elif isinstance(self.schedule, IntervalSchedule):
            return {
                "seconds": self.schedule.seconds,
                "minutes": self.schedule.minutes,
                "hours": self.schedule.hours,
                "days": self.schedule.days,
            }
        elif isinstance(self.schedule, OneTimeSchedule):
            return {"run_at": self.schedule.run_at.isoformat()}
        elif isinstance(self.schedule, DependentSchedule):
            return {
                "parent_job_id": self.schedule.parent_job_id,
                "trigger_on": [s.value for s in self.schedule.trigger_on],
                "delay_seconds": self.schedule.delay_seconds,
            }
        return {}

    def _execution_to_dict(self) -> dict[str, Any]:
        """Convert execution config to dict."""
        if isinstance(self.execution, ClaudePromptExecution):
            return {
                "prompt": self.execution.prompt,
                "system_prompt": self.execution.system_prompt,
                "project_path": self.execution.project_path,
                "max_turns": self.execution.max_turns,
                "model": self.execution.model,
                "allowed_tools": self.execution.allowed_tools,
                "environment": self.execution.environment,
            }
        elif isinstance(self.execution, ScriptExecution):
            return {
                "command": self.execution.command,
                "working_directory": self.execution.working_directory,
                "shell": self.execution.shell,
                "timeout": self.execution.timeout,
                "environment": self.execution.environment,
            }
        elif isinstance(self.execution, WebhookExecution):
            return {
                "url": self.execution.url,
                "method": self.execution.method,
                "headers": self.execution.headers,
                "body": self.execution.body,
                "timeout": self.execution.timeout,
                "verify_ssl": self.execution.verify_ssl,
            }
        elif isinstance(self.execution, PythonExecution):
            return {
                "module": self.execution.module,
                "function": self.execution.function,
                "args": self.execution.args,
                "kwargs": self.execution.kwargs,
            }
        return {}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobDefinition:
        """Create JobDefinition from dictionary."""
        schedule_type = ScheduleType(data["schedule_type"])
        schedule = cls._parse_schedule(schedule_type, data["schedule_config"])

        execution_type = ExecutionType(data["execution_type"])
        execution = cls._parse_execution(execution_type, data["execution_config"])

        retry_data = data.get("retry_config", {})
        retry = RetryConfig(
            max_attempts=retry_data.get("max_attempts", 3),
            backoff_type=BackoffType(retry_data.get("backoff_type", "exponential")),
            initial_delay=retry_data.get("initial_delay", 60),
            max_delay=retry_data.get("max_delay", 3600),
            retry_on=[JobStatus(s) for s in retry_data.get("retry_on", ["failure", "timeout"])],
        )

        notif_data = data.get("notification_config", {})
        notifications = NotificationConfig(
            on_success=notif_data.get("on_success", []),
            on_failure=notif_data.get("on_failure", []),
            on_start=notif_data.get("on_start", []),
            include_output=notif_data.get("include_output", True),
            include_error=notif_data.get("include_error", True),
        )

        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.utcnow()

        return cls(
            id=data.get("id", str(uuid4())[:12]),
            name=data["name"],
            description=data.get("description", ""),
            schedule_type=schedule_type,
            schedule=schedule,
            execution_type=execution_type,
            execution=execution,
            retry=retry,
            notifications=notifications,
            enabled=data.get("enabled", True),
            paused=data.get("paused", False),
            tags=data.get("tags", []),
            category=data.get("category"),
            created_at=created_at,
            created_by=data.get("created_by"),
            metadata=data.get("metadata", {}),
        )

    @staticmethod
    def _parse_schedule(
        schedule_type: ScheduleType,
        config: dict[str, Any],
    ) -> CronSchedule | IntervalSchedule | OneTimeSchedule | DependentSchedule:
        """Parse schedule from config dict."""
        if schedule_type == ScheduleType.CRON:
            return CronSchedule(
                expression=config["expression"],
                timezone=config.get("timezone", "UTC"),
            )
        elif schedule_type == ScheduleType.INTERVAL:
            return IntervalSchedule(
                seconds=config.get("seconds", 0),
                minutes=config.get("minutes", 0),
                hours=config.get("hours", 0),
                days=config.get("days", 0),
            )
        elif schedule_type == ScheduleType.ONE_TIME:
            run_at = config["run_at"]
            if isinstance(run_at, str):
                run_at = datetime.fromisoformat(run_at)
            return OneTimeSchedule(run_at=run_at)
        elif schedule_type == ScheduleType.DEPENDENT:
            return DependentSchedule(
                parent_job_id=config["parent_job_id"],
                trigger_on=[JobStatus(s) for s in config.get("trigger_on", ["success"])],
                delay_seconds=config.get("delay_seconds", 0),
            )
        raise ValueError(f"Unknown schedule type: {schedule_type}")

    @staticmethod
    def _parse_execution(
        execution_type: ExecutionType,
        config: dict[str, Any],
    ) -> ClaudePromptExecution | ScriptExecution | WebhookExecution | PythonExecution:
        """Parse execution config from dict."""
        if execution_type == ExecutionType.CLAUDE_PROMPT:
            return ClaudePromptExecution(
                prompt=config["prompt"],
                system_prompt=config.get("system_prompt"),
                project_path=config.get("project_path"),
                max_turns=config.get("max_turns", 50),
                model=config.get("model", "claude-sonnet-4-20250514"),
                allowed_tools=config.get("allowed_tools"),
                environment=config.get("environment", {}),
            )
        elif execution_type == ExecutionType.SCRIPT:
            return ScriptExecution(
                command=config["command"],
                working_directory=config.get("working_directory", "."),
                shell=config.get("shell", "/bin/bash"),
                timeout=config.get("timeout", 300),
                environment=config.get("environment", {}),
            )
        elif execution_type == ExecutionType.WEBHOOK:
            return WebhookExecution(
                url=config["url"],
                method=config.get("method", "POST"),
                headers=config.get("headers", {}),
                body=config.get("body"),
                timeout=config.get("timeout", 30),
                verify_ssl=config.get("verify_ssl", True),
            )
        elif execution_type == ExecutionType.PYTHON:
            return PythonExecution(
                module=config["module"],
                function=config["function"],
                args=config.get("args", []),
                kwargs=config.get("kwargs", {}),
            )
        raise ValueError(f"Unknown execution type: {execution_type}")


@dataclass
class JobRun:
    """
    Record of a job execution.

    Tracks:
    - Execution status and timing
    - Output and errors
    - Retry attempts
    - Cost tracking (for Claude jobs)
    """

    job_id: str
    status: JobStatus = JobStatus.PENDING

    # Identification
    run_id: str = field(default_factory=lambda: str(uuid4())[:16])

    # Timing
    scheduled_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Retry tracking
    attempt: int = 1
    max_attempts: int = 3

    # Output
    output: str | None = None
    error: str | None = None

    # Trigger info
    triggered_by: str = "schedule"  # schedule, manual, webhook, dependency
    triggered_by_user: str | None = None
    parent_run_id: str | None = None  # For dependent jobs

    # Cost tracking (Claude jobs)
    cost_usd: float | None = None

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> int | None:
        """Calculate execution duration in milliseconds."""
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            return int(delta.total_seconds() * 1000)
        return None

    @property
    def is_terminal(self) -> bool:
        """Check if this run is in a terminal state."""
        return self.status in (
            JobStatus.SUCCESS,
            JobStatus.FAILURE,
            JobStatus.TIMEOUT,
            JobStatus.CANCELLED,
            JobStatus.SKIPPED,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "run_id": self.run_id,
            "job_id": self.job_id,
            "status": self.status.value,
            "scheduled_at": self.scheduled_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "output": self.output,
            "error": self.error,
            "triggered_by": self.triggered_by,
            "triggered_by_user": self.triggered_by_user,
            "parent_run_id": self.parent_run_id,
            "cost_usd": self.cost_usd,
            "metadata": self.metadata,
        }
