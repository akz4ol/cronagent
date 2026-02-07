"""
Scheduler service using APScheduler.

Provides:
- Job scheduling with cron/interval/one-time schedules
- Persistent job storage
- Retry with exponential backoff
- Dependent job triggering
- Event-driven notifications
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MISSED,
    JobExecutionEvent,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from cronagent.bus.events import EventBus, Events
from cronagent.config import SchedulerConfig
from cronagent.cron.executor import ExecutionResult, TaskExecutor, execute_with_retry
from cronagent.cron.job import (
    CronSchedule,
    DependentSchedule,
    IntervalSchedule,
    JobDefinition,
    JobRun,
    JobStatus,
    OneTimeSchedule,
    ScheduleType,
)
from cronagent.cron.store import JobStore
from cronagent.storage.database import Database

logger = logging.getLogger(__name__)


class SchedulerService:
    """
    Main scheduler service.

    Manages job scheduling, execution, and lifecycle events.

    Usage:
        db = Database.from_config(config.memory)
        await db.initialize()

        scheduler = SchedulerService(db, config.scheduler, event_bus)
        await scheduler.start()

        # Add a job
        job = JobDefinition(
            name="Daily Report",
            schedule_type=ScheduleType.CRON,
            schedule=CronSchedule("0 9 * * *"),
            execution_type=ExecutionType.CLAUDE_PROMPT,
            execution=ClaudePromptExecution(prompt="Generate daily report"),
        )
        await scheduler.add_job(job)

        # Manually trigger a job
        await scheduler.trigger_job("job-id")

        # Graceful shutdown
        await scheduler.shutdown()
    """

    def __init__(
        self,
        database: Database,
        config: SchedulerConfig,
        event_bus: EventBus | None = None,
    ) -> None:
        self.db = database
        self.config = config
        self.event_bus = event_bus

        # Initialize components
        self.store = JobStore(database, event_bus)
        self.executor = TaskExecutor(event_bus)

        # APScheduler
        self._scheduler = AsyncIOScheduler(
            timezone=config.timezone,
            job_defaults={
                "coalesce": True,  # Combine missed runs
                "max_instances": config.max_concurrent_jobs,
                "misfire_grace_time": 60,  # 1 minute grace
            },
        )

        # Track running jobs
        self._running_jobs: dict[str, asyncio.Task] = {}
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """Start the scheduler service."""
        logger.info("Starting scheduler service...")

        # Add APScheduler event listeners
        self._scheduler.add_listener(
            self._on_job_executed,
            EVENT_JOB_EXECUTED,
        )
        self._scheduler.add_listener(
            self._on_job_error,
            EVENT_JOB_ERROR,
        )
        self._scheduler.add_listener(
            self._on_job_missed,
            EVENT_JOB_MISSED,
        )

        # Load existing jobs
        await self._load_jobs()

        # Start the scheduler
        self._scheduler.start()

        logger.info("Scheduler service started")

        if self.event_bus:
            await self.event_bus.emit(
                Events.SCHEDULER_STARTED,
                {"timezone": self.config.timezone},
            )

    async def shutdown(self, wait: bool = True) -> None:
        """
        Shutdown the scheduler service.

        Args:
            wait: Wait for running jobs to complete
        """
        logger.info("Shutting down scheduler service...")

        self._shutdown_event.set()

        # Stop accepting new jobs
        self._scheduler.shutdown(wait=wait)

        # Wait for running jobs
        if wait and self._running_jobs:
            logger.info(f"Waiting for {len(self._running_jobs)} running jobs...")
            await asyncio.gather(
                *self._running_jobs.values(),
                return_exceptions=True,
            )

        logger.info("Scheduler service shutdown complete")

        if self.event_bus:
            await self.event_bus.emit(Events.SCHEDULER_STOPPED, {})

    async def add_job(self, job: JobDefinition) -> str:
        """
        Add a new job to the scheduler.

        Args:
            job: Job definition

        Returns:
            Job ID
        """
        # Save to store
        await self.store.add_job(job)

        # Schedule in APScheduler if enabled and not paused
        if job.enabled and not job.paused:
            self._schedule_job(job)

        return job.id

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
            True if updated
        """
        # Update in store
        if not await self.store.update_job(job_id, updates):
            return False

        # Reschedule if enabled/paused changed
        job = await self.store.get_job(job_id)
        if job:
            self._unschedule_job(job_id)

            if job.enabled and not job.paused:
                self._schedule_job(job)

        return True

    async def remove_job(self, job_id: str) -> bool:
        """Remove a job from the scheduler."""
        # Unschedule
        self._unschedule_job(job_id)

        # Delete from store
        return await self.store.delete_job(job_id)

    async def pause_job(self, job_id: str) -> bool:
        """Pause a job."""
        self._unschedule_job(job_id)
        return await self.store.update_job(job_id, {"paused": True})

    async def resume_job(self, job_id: str) -> bool:
        """Resume a paused job."""
        job = await self.store.get_job(job_id)
        if not job:
            return False

        await self.store.update_job(job_id, {"paused": False})

        if job.enabled:
            self._schedule_job(job)

        return True

    async def trigger_job(
        self,
        job_id: str,
        triggered_by: str = "manual",
        triggered_by_user: str | None = None,
    ) -> str | None:
        """
        Manually trigger a job execution.

        Args:
            job_id: Job to trigger
            triggered_by: Trigger source
            triggered_by_user: User who triggered

        Returns:
            Run ID if triggered, None if job not found
        """
        job = await self.store.get_job(job_id)
        if not job:
            return None

        # Create run record
        run_id = await self.store.create_run(
            job_id,
            triggered_by=triggered_by,
            triggered_by_user=triggered_by_user,
        )

        # Execute asynchronously
        task = asyncio.create_task(
            self._execute_job(job, run_id)
        )
        self._running_jobs[run_id] = task

        return run_id

    async def get_job(self, job_id: str) -> JobDefinition | None:
        """Get a job by ID."""
        return await self.store.get_job(job_id)

    async def list_jobs(
        self,
        enabled_only: bool = False,
        category: str | None = None,
    ) -> list[JobDefinition]:
        """List jobs with optional filters."""
        return await self.store.list_jobs(
            enabled_only=enabled_only,
            category=category,
        )

    async def get_job_stats(self, job_id: str) -> dict[str, Any]:
        """Get statistics for a job."""
        return await self.store.get_job_stats(job_id)

    async def get_runs(
        self,
        job_id: str | None = None,
        status: JobStatus | None = None,
        limit: int = 50,
    ) -> list[JobRun]:
        """Get job runs with optional filters."""
        return await self.store.get_runs(job_id, status, limit)

    async def get_summary(self) -> dict[str, Any]:
        """Get scheduler summary statistics."""
        stats = await self.store.get_summary_stats()
        stats["running_jobs"] = len(self._running_jobs)
        stats["scheduler_running"] = self._scheduler.running
        return stats

    # --- Internal Methods ---

    async def _load_jobs(self) -> None:
        """Load existing jobs from store and schedule them."""
        jobs = await self.store.list_jobs(enabled_only=True)

        for job in jobs:
            if not job.paused:
                self._schedule_job(job)

        logger.info(f"Loaded {len(jobs)} jobs")

    def _schedule_job(self, job: JobDefinition) -> None:
        """Schedule a job in APScheduler."""
        # Skip dependent jobs (triggered by other jobs)
        if job.schedule_type == ScheduleType.DEPENDENT:
            return

        trigger = self._create_trigger(job)
        if not trigger:
            return

        self._scheduler.add_job(
            self._job_callback,
            trigger=trigger,
            id=job.id,
            name=job.name,
            args=[job.id],
            replace_existing=True,
        )

        logger.debug(f"Scheduled job: {job.id} ({job.name})")

    def _unschedule_job(self, job_id: str) -> None:
        """Remove a job from APScheduler."""
        try:
            self._scheduler.remove_job(job_id)
            logger.debug(f"Unscheduled job: {job_id}")
        except Exception:
            pass  # Job might not be scheduled

    def _create_trigger(
        self,
        job: JobDefinition,
    ) -> CronTrigger | IntervalTrigger | DateTrigger | None:
        """Create APScheduler trigger from job schedule."""
        if job.schedule_type == ScheduleType.CRON:
            schedule = job.schedule
            if isinstance(schedule, CronSchedule):
                return CronTrigger.from_crontab(
                    schedule.expression,
                    timezone=schedule.timezone,
                )

        elif job.schedule_type == ScheduleType.INTERVAL:
            schedule = job.schedule
            if isinstance(schedule, IntervalSchedule):
                return IntervalTrigger(
                    seconds=schedule.total_seconds,
                )

        elif job.schedule_type == ScheduleType.ONE_TIME:
            schedule = job.schedule
            if isinstance(schedule, OneTimeSchedule):
                return DateTrigger(run_date=schedule.run_at)

        return None

    async def _job_callback(self, job_id: str) -> None:
        """Callback for scheduled job execution."""
        job = await self.store.get_job(job_id)
        if not job:
            logger.warning(f"Job not found for callback: {job_id}")
            return

        # Create run record
        run_id = await self.store.create_run(job_id)

        # Execute
        await self._execute_job(job, run_id)

    async def _execute_job(self, job: JobDefinition, run_id: str) -> None:
        """Execute a job."""
        try:
            # Get run record
            run = await self.store.get_run(run_id)
            if not run:
                logger.error(f"Run not found: {run_id}")
                return

            # Mark as started
            await self.store.start_run(run_id)

            # Send start notification
            await self._send_notifications(job, run, "start")

            # Execute with retry
            async def on_retry(attempt: int, delay: int, result: ExecutionResult) -> None:
                await self.store.increment_attempt(run_id)

            result = await execute_with_retry(
                self.executor,
                job,
                run,
                on_retry=on_retry,
            )

            # Update run with result
            await self.store.complete_run(
                run_id,
                status=result.status,
                output=result.output,
                error=result.error,
                cost_usd=result.cost_usd,
            )

            # Send completion notification
            await self._send_notifications(job, run, "complete", result)

            # Trigger dependent jobs on success
            if result.status == JobStatus.SUCCESS:
                await self._trigger_dependent_jobs(job.id, run_id)

        except Exception as e:
            logger.error(f"Job execution error: {e}", exc_info=True)

            await self.store.complete_run(
                run_id,
                status=JobStatus.FAILURE,
                error=str(e),
            )

        finally:
            # Remove from running jobs
            self._running_jobs.pop(run_id, None)

    async def _trigger_dependent_jobs(
        self,
        parent_job_id: str,
        parent_run_id: str,
    ) -> None:
        """Trigger jobs that depend on the completed job."""
        dependent_jobs = await self.store.get_dependent_jobs(parent_job_id)

        for dep_job in dependent_jobs:
            if not dep_job.enabled or dep_job.paused:
                continue

            schedule = dep_job.schedule
            if isinstance(schedule, DependentSchedule):
                # Check if should trigger on this status
                # (currently only triggers on SUCCESS)

                # Apply delay if configured
                if schedule.delay_seconds > 0:
                    await asyncio.sleep(schedule.delay_seconds)

                # Trigger the dependent job
                run_id = await self.store.create_run(
                    dep_job.id,
                    triggered_by="dependency",
                    parent_run_id=parent_run_id,
                )

                task = asyncio.create_task(
                    self._execute_job(dep_job, run_id)
                )
                self._running_jobs[run_id] = task

                logger.info(
                    f"Triggered dependent job {dep_job.id} from {parent_job_id}"
                )

    async def _send_notifications(
        self,
        job: JobDefinition,
        run: JobRun,
        event_type: str,
        result: ExecutionResult | None = None,
    ) -> None:
        """Send notifications for job events."""
        if not self.event_bus:
            return

        notif = job.notifications

        if event_type == "start" and notif.on_start:
            await self.event_bus.emit(
                Events.JOB_NOTIFICATION,
                {
                    "job_id": job.id,
                    "job_name": job.name,
                    "run_id": run.run_id,
                    "event": "start",
                    "channels": notif.on_start,
                },
            )

        elif event_type == "complete" and result:
            channels = []
            if result.status == JobStatus.SUCCESS:
                channels = notif.on_success
            else:
                channels = notif.on_failure

            if channels:
                payload: dict[str, Any] = {
                    "job_id": job.id,
                    "job_name": job.name,
                    "run_id": run.run_id,
                    "event": "complete",
                    "status": result.status.value,
                    "channels": channels,
                }

                if notif.include_output and result.output:
                    # Truncate long output
                    output = result.output
                    if len(output) > 2000:
                        output = output[:2000] + "... (truncated)"
                    payload["output"] = output

                if notif.include_error and result.error:
                    payload["error"] = result.error

                await self.event_bus.emit(Events.JOB_NOTIFICATION, payload)

    def _on_job_executed(self, event: JobExecutionEvent) -> None:
        """Handle APScheduler job executed event."""
        logger.debug(f"APScheduler job executed: {event.job_id}")

    def _on_job_error(self, event: JobExecutionEvent) -> None:
        """Handle APScheduler job error event."""
        logger.error(f"APScheduler job error: {event.job_id} - {event.exception}")

    def _on_job_missed(self, event: JobExecutionEvent) -> None:
        """Handle APScheduler job missed event."""
        logger.warning(f"APScheduler job missed: {event.job_id}")

        if self.event_bus:
            asyncio.create_task(
                self.event_bus.emit(
                    Events.JOB_MISSED,
                    {"job_id": event.job_id},
                )
            )


async def create_scheduler(
    config: Any,  # CronAgentConfig
    event_bus: EventBus | None = None,
) -> SchedulerService:
    """
    Create and initialize a scheduler service.

    Args:
        config: CronAgent configuration
        event_bus: Optional event bus

    Returns:
        Initialized SchedulerService
    """
    from cronagent.storage import Database

    # Initialize database
    db = Database.from_config(config.memory)
    await db.initialize()

    # Create scheduler
    scheduler = SchedulerService(db, config.scheduler, event_bus)

    return scheduler
