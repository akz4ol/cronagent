"""
Job store for persistence.

Supports:
- SQLAlchemy-based storage (SQLite/PostgreSQL)
- Job CRUD operations
- Run history tracking
- Statistics and queries
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cronagent.bus.events import EventBus, Events
from cronagent.cron.job import (
    JobDefinition,
    JobRun,
    JobStatus,
    ScheduleType,
)
from cronagent.storage.database import Database
from cronagent.storage.models import JobRun as JobRunModel
from cronagent.storage.models import ScheduledJob

logger = logging.getLogger(__name__)


class JobStore:
    """
    Persistent storage for jobs and runs.

    Provides:
    - Job CRUD operations
    - Run history tracking
    - Statistics queries
    - Dependent job lookups

    Usage:
        store = JobStore(database, event_bus)

        # Add a job
        await store.add_job(job_definition)

        # Get job
        job = await store.get_job("job-id")

        # Record a run
        run_id = await store.create_run("job-id")
        await store.update_run(run_id, status=JobStatus.SUCCESS)

        # Get stats
        stats = await store.get_job_stats("job-id")
    """

    def __init__(
        self,
        database: Database,
        event_bus: EventBus | None = None,
    ) -> None:
        self.db = database
        self.event_bus = event_bus

    # --- Job CRUD ---

    async def add_job(self, job: JobDefinition) -> str:
        """
        Add a new job to the store.

        Args:
            job: Job definition to add

        Returns:
            Job ID
        """
        job_dict = job.to_dict()

        async with self.db.session() as session:
            db_job = ScheduledJob(
                id=job.id,
                name=job.name,
                description=job.description,
                schedule_type=job.schedule_type.value,
                schedule_config=job_dict["schedule_config"],
                execution_type=job.execution_type.value,
                execution_config=job_dict["execution_config"],
                retry_config=job_dict["retry_config"],
                notification_config=job_dict["notification_config"],
                enabled=job.enabled,
                paused=job.paused,
                tags=job.tags,
                category=job.category,
                created_by=job.created_by,
            )
            session.add(db_job)

        logger.info(f"Added job: {job.id} ({job.name})")

        if self.event_bus:
            await self.event_bus.emit(
                Events.JOB_CREATED,
                {"job_id": job.id, "name": job.name},
            )

        return job.id

    async def get_job(self, job_id: str) -> JobDefinition | None:
        """Get a job by ID."""
        async with self.db.session() as session:
            result = await session.execute(
                select(ScheduledJob).where(ScheduledJob.id == job_id)
            )
            db_job = result.scalar_one_or_none()

            if not db_job:
                return None

            return self._model_to_definition(db_job)

    async def update_job(
        self,
        job_id: str,
        updates: dict[str, Any],
    ) -> bool:
        """
        Update a job.

        Args:
            job_id: Job to update
            updates: Fields to update

        Returns:
            True if updated, False if not found
        """
        async with self.db.session() as session:
            result = await session.execute(
                update(ScheduledJob)
                .where(ScheduledJob.id == job_id)
                .values(**updates, updated_at=datetime.utcnow())
            )

            if result.rowcount == 0:
                return False

        logger.info(f"Updated job: {job_id}")

        if self.event_bus:
            await self.event_bus.emit(
                Events.JOB_UPDATED,
                {"job_id": job_id, "updates": list(updates.keys())},
            )

        return True

    async def delete_job(self, job_id: str) -> bool:
        """Delete a job and its run history."""
        async with self.db.session() as session:
            result = await session.execute(
                delete(ScheduledJob).where(ScheduledJob.id == job_id)
            )

            if result.rowcount == 0:
                return False

        logger.info(f"Deleted job: {job_id}")

        if self.event_bus:
            await self.event_bus.emit(
                Events.JOB_DELETED,
                {"job_id": job_id},
            )

        return True

    async def list_jobs(
        self,
        enabled_only: bool = False,
        category: str | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
    ) -> list[JobDefinition]:
        """
        List jobs with optional filters.

        Args:
            enabled_only: Only return enabled jobs
            category: Filter by category
            tags: Filter by tags (any match)
            limit: Maximum results

        Returns:
            List of job definitions
        """
        async with self.db.session() as session:
            query = select(ScheduledJob).limit(limit)

            if enabled_only:
                query = query.where(
                    ScheduledJob.enabled == True,
                    ScheduledJob.paused == False,
                )

            if category:
                query = query.where(ScheduledJob.category == category)

            result = await session.execute(query)
            jobs = []

            for db_job in result.scalars():
                # Filter by tags if specified
                if tags:
                    job_tags = db_job.tags or []
                    if not any(t in job_tags for t in tags):
                        continue

                jobs.append(self._model_to_definition(db_job))

            return jobs

    async def get_dependent_jobs(self, parent_job_id: str) -> list[JobDefinition]:
        """Get all jobs that depend on a given job."""
        async with self.db.session() as session:
            # Query jobs with dependent schedule type
            result = await session.execute(
                select(ScheduledJob).where(
                    ScheduledJob.schedule_type == ScheduleType.DEPENDENT.value
                )
            )

            dependent_jobs = []
            for db_job in result.scalars():
                config = db_job.schedule_config or {}
                if config.get("parent_job_id") == parent_job_id:
                    dependent_jobs.append(self._model_to_definition(db_job))

            return dependent_jobs

    # --- Run Management ---

    async def create_run(
        self,
        job_id: str,
        triggered_by: str = "schedule",
        triggered_by_user: str | None = None,
        parent_run_id: str | None = None,
    ) -> str:
        """
        Create a new job run record.

        Args:
            job_id: Job being executed
            triggered_by: Trigger type (schedule, manual, webhook, dependency)
            triggered_by_user: User who triggered (for manual runs)
            parent_run_id: Parent run (for dependent jobs)

        Returns:
            Run ID
        """
        run_id = str(uuid4())[:16]

        async with self.db.session() as session:
            # Get job for max_attempts
            job_result = await session.execute(
                select(ScheduledJob).where(ScheduledJob.id == job_id)
            )
            db_job = job_result.scalar_one_or_none()
            max_attempts = 3
            if db_job and db_job.retry_config:
                max_attempts = db_job.retry_config.get("max_attempts", 3)

            db_run = JobRunModel(
                id=run_id,
                job_id=job_id,
                status=JobStatus.PENDING.value,
                attempt=1,
                max_attempts=max_attempts,
                triggered_by=triggered_by,
                triggered_by_user=triggered_by_user,
                parent_run_id=parent_run_id,
            )
            session.add(db_run)

        logger.debug(f"Created run {run_id} for job {job_id}")

        return run_id

    async def start_run(self, run_id: str) -> bool:
        """Mark a run as started."""
        now = datetime.utcnow()

        async with self.db.session() as session:
            result = await session.execute(
                update(JobRunModel)
                .where(JobRunModel.id == run_id)
                .values(status=JobStatus.RUNNING.value, started_at=now)
            )

            if result.rowcount == 0:
                return False

            # Get job_id for event
            run_result = await session.execute(
                select(JobRunModel.job_id).where(JobRunModel.id == run_id)
            )
            job_id = run_result.scalar_one_or_none()

        if self.event_bus and job_id:
            await self.event_bus.emit(
                Events.JOB_STARTED,
                {"job_id": job_id, "run_id": run_id},
            )

        return True

    async def complete_run(
        self,
        run_id: str,
        status: JobStatus,
        output: str | None = None,
        error: str | None = None,
        cost_usd: float | None = None,
    ) -> bool:
        """
        Mark a run as completed.

        Args:
            run_id: Run to complete
            status: Final status
            output: Output content
            error: Error message
            cost_usd: Cost for Claude runs

        Returns:
            True if updated
        """
        now = datetime.utcnow()

        async with self.db.session() as session:
            # Get run to calculate duration
            run_result = await session.execute(
                select(JobRunModel).where(JobRunModel.id == run_id)
            )
            db_run = run_result.scalar_one_or_none()

            if not db_run:
                return False

            duration_ms = None
            if db_run.started_at:
                delta = now - db_run.started_at
                duration_ms = int(delta.total_seconds() * 1000)

            # Update run
            await session.execute(
                update(JobRunModel)
                .where(JobRunModel.id == run_id)
                .values(
                    status=status.value,
                    completed_at=now,
                    duration_ms=duration_ms,
                    output=output,
                    error=error,
                    cost_usd=cost_usd,
                )
            )

            # Update job statistics
            update_values: dict[str, Any] = {
                "last_run_at": now,
                "last_run_status": status.value,
                "run_count": ScheduledJob.run_count + 1,
            }

            if status == JobStatus.SUCCESS:
                update_values["success_count"] = ScheduledJob.success_count + 1
            elif status in (JobStatus.FAILURE, JobStatus.TIMEOUT):
                update_values["failure_count"] = ScheduledJob.failure_count + 1

            await session.execute(
                update(ScheduledJob)
                .where(ScheduledJob.id == db_run.job_id)
                .values(**update_values)
            )

            job_id = db_run.job_id

        logger.info(f"Completed run {run_id} with status {status.value}")

        # Emit events
        if self.event_bus:
            event = Events.JOB_COMPLETED if status == JobStatus.SUCCESS else Events.JOB_FAILED
            await self.event_bus.emit(
                event,
                {
                    "job_id": job_id,
                    "run_id": run_id,
                    "status": status.value,
                    "duration_ms": duration_ms,
                    "cost_usd": cost_usd,
                },
            )

        return True

    async def increment_attempt(self, run_id: str) -> int:
        """Increment retry attempt counter. Returns new attempt number."""
        async with self.db.session() as session:
            result = await session.execute(
                update(JobRunModel)
                .where(JobRunModel.id == run_id)
                .values(
                    attempt=JobRunModel.attempt + 1,
                    status=JobStatus.PENDING.value,
                    started_at=None,
                    completed_at=None,
                )
                .returning(JobRunModel.attempt)
            )
            new_attempt = result.scalar_one_or_none()
            return new_attempt or 1

    async def get_run(self, run_id: str) -> JobRun | None:
        """Get a run by ID."""
        async with self.db.session() as session:
            result = await session.execute(
                select(JobRunModel).where(JobRunModel.id == run_id)
            )
            db_run = result.scalar_one_or_none()

            if not db_run:
                return None

            return self._run_model_to_dataclass(db_run)

    async def get_runs(
        self,
        job_id: str | None = None,
        status: JobStatus | None = None,
        limit: int = 50,
        since: datetime | None = None,
    ) -> list[JobRun]:
        """
        Get runs with optional filters.

        Args:
            job_id: Filter by job
            status: Filter by status
            limit: Maximum results
            since: Only runs after this time

        Returns:
            List of job runs
        """
        async with self.db.session() as session:
            query = (
                select(JobRunModel)
                .order_by(JobRunModel.started_at.desc())
                .limit(limit)
            )

            if job_id:
                query = query.where(JobRunModel.job_id == job_id)
            if status:
                query = query.where(JobRunModel.status == status.value)
            if since:
                query = query.where(JobRunModel.started_at >= since)

            result = await session.execute(query)
            return [self._run_model_to_dataclass(r) for r in result.scalars()]

    # --- Statistics ---

    async def get_job_stats(self, job_id: str) -> dict[str, Any]:
        """Get statistics for a job."""
        async with self.db.session() as session:
            # Get job
            job_result = await session.execute(
                select(ScheduledJob).where(ScheduledJob.id == job_id)
            )
            db_job = job_result.scalar_one_or_none()

            if not db_job:
                return {}

            # Calculate success rate
            total = db_job.run_count or 0
            successes = db_job.success_count or 0
            success_rate = (successes / total * 100) if total > 0 else 0

            # Get average duration
            duration_result = await session.execute(
                select(func.avg(JobRunModel.duration_ms))
                .where(
                    JobRunModel.job_id == job_id,
                    JobRunModel.duration_ms.isnot(None),
                )
            )
            avg_duration = duration_result.scalar_one_or_none() or 0

            # Get total cost
            cost_result = await session.execute(
                select(func.sum(JobRunModel.cost_usd))
                .where(
                    JobRunModel.job_id == job_id,
                    JobRunModel.cost_usd.isnot(None),
                )
            )
            total_cost = cost_result.scalar_one_or_none() or 0

            return {
                "job_id": job_id,
                "name": db_job.name,
                "enabled": db_job.enabled,
                "paused": db_job.paused,
                "run_count": total,
                "success_count": successes,
                "failure_count": db_job.failure_count or 0,
                "success_rate": round(success_rate, 2),
                "avg_duration_ms": int(avg_duration),
                "total_cost_usd": round(total_cost, 4),
                "last_run_at": db_job.last_run_at.isoformat() if db_job.last_run_at else None,
                "last_run_status": db_job.last_run_status,
            }

    async def get_summary_stats(self) -> dict[str, Any]:
        """Get overall scheduler statistics."""
        async with self.db.session() as session:
            # Job counts
            total_jobs = await session.execute(select(func.count(ScheduledJob.id)))
            enabled_jobs = await session.execute(
                select(func.count(ScheduledJob.id)).where(
                    ScheduledJob.enabled == True,
                    ScheduledJob.paused == False,
                )
            )

            # Run counts (last 24 hours)
            yesterday = datetime.utcnow() - timedelta(days=1)
            runs_24h = await session.execute(
                select(func.count(JobRunModel.id)).where(
                    JobRunModel.started_at >= yesterday
                )
            )
            success_24h = await session.execute(
                select(func.count(JobRunModel.id)).where(
                    JobRunModel.started_at >= yesterday,
                    JobRunModel.status == JobStatus.SUCCESS.value,
                )
            )
            failed_24h = await session.execute(
                select(func.count(JobRunModel.id)).where(
                    JobRunModel.started_at >= yesterday,
                    JobRunModel.status.in_([
                        JobStatus.FAILURE.value,
                        JobStatus.TIMEOUT.value,
                    ]),
                )
            )

            return {
                "total_jobs": total_jobs.scalar_one(),
                "enabled_jobs": enabled_jobs.scalar_one(),
                "runs_24h": runs_24h.scalar_one(),
                "success_24h": success_24h.scalar_one(),
                "failed_24h": failed_24h.scalar_one(),
            }

    # --- Cleanup ---

    async def cleanup_old_runs(self, days: int = 30) -> int:
        """Delete runs older than specified days."""
        cutoff = datetime.utcnow() - timedelta(days=days)

        async with self.db.session() as session:
            result = await session.execute(
                delete(JobRunModel).where(JobRunModel.completed_at < cutoff)
            )
            deleted = result.rowcount

        logger.info(f"Cleaned up {deleted} old job runs")
        return deleted

    # --- Helpers ---

    def _model_to_definition(self, db_job: ScheduledJob) -> JobDefinition:
        """Convert database model to JobDefinition."""
        return JobDefinition.from_dict({
            "id": db_job.id,
            "name": db_job.name,
            "description": db_job.description,
            "schedule_type": db_job.schedule_type,
            "schedule_config": db_job.schedule_config,
            "execution_type": db_job.execution_type,
            "execution_config": db_job.execution_config,
            "retry_config": db_job.retry_config,
            "notification_config": db_job.notification_config,
            "enabled": db_job.enabled,
            "paused": db_job.paused,
            "tags": db_job.tags,
            "category": db_job.category,
            "created_at": db_job.created_at,
            "created_by": db_job.created_by,
        })

    def _run_model_to_dataclass(self, db_run: JobRunModel) -> JobRun:
        """Convert database model to JobRun dataclass."""
        return JobRun(
            run_id=db_run.id,
            job_id=db_run.job_id,
            status=JobStatus(db_run.status),
            scheduled_at=db_run.started_at or datetime.utcnow(),
            started_at=db_run.started_at,
            completed_at=db_run.completed_at,
            attempt=db_run.attempt,
            max_attempts=db_run.max_attempts,
            output=db_run.output,
            error=db_run.error,
            triggered_by=db_run.triggered_by,
            triggered_by_user=db_run.triggered_by_user,
            parent_run_id=db_run.parent_run_id,
            cost_usd=db_run.cost_usd,
        )
