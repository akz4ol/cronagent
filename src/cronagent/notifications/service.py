"""
Notification service for formatting and delivering alerts.

Provides centralized notification handling with:
- Multi-channel delivery (Slack, Discord, email, webhooks)
- Template-based formatting
- Rate limiting and deduplication
- Notification history tracking
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable

from cronagent.bus.events import EventBus, Events
from cronagent.config import NotificationConfig

logger = logging.getLogger(__name__)


class NotificationLevel(str, Enum):
    """Notification severity levels."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NotificationChannel(str, Enum):
    """Supported notification channels."""

    SLACK = "slack"
    DISCORD = "discord"
    EMAIL = "email"
    WEBHOOK = "webhook"
    TELEGRAM = "telegram"


@dataclass
class NotificationTemplate:
    """Template for notification formatting."""

    name: str
    title_template: str
    body_template: str
    level: NotificationLevel = NotificationLevel.INFO
    include_timestamp: bool = True
    include_metadata: bool = True


@dataclass
class Notification:
    """A notification to be sent."""

    id: str
    title: str
    message: str
    level: NotificationLevel = NotificationLevel.INFO
    channels: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    template: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    dedupe_key: str | None = None


@dataclass
class NotificationResult:
    """Result of sending a notification."""

    notification_id: str
    channel: str
    success: bool
    error: str | None = None
    sent_at: datetime = field(default_factory=datetime.now)
    response: dict[str, Any] = field(default_factory=dict)


# Built-in templates
BUILTIN_TEMPLATES: dict[str, NotificationTemplate] = {
    "job_started": NotificationTemplate(
        name="job_started",
        title_template="🚀 Job Started: {job_name}",
        body_template="Job `{job_id}` has started execution.\n\nSchedule: {schedule}",
        level=NotificationLevel.INFO,
    ),
    "job_completed": NotificationTemplate(
        name="job_completed",
        title_template="✅ Job Completed: {job_name}",
        body_template="Job `{job_id}` completed successfully.\n\nDuration: {duration}\nOutput: {output}",
        level=NotificationLevel.SUCCESS,
    ),
    "job_failed": NotificationTemplate(
        name="job_failed",
        title_template="❌ Job Failed: {job_name}",
        body_template="Job `{job_id}` failed with error:\n```\n{error}\n```\n\nAttempt: {attempt}/{max_attempts}",
        level=NotificationLevel.ERROR,
    ),
    "job_retry": NotificationTemplate(
        name="job_retry",
        title_template="🔄 Job Retrying: {job_name}",
        body_template="Job `{job_id}` is retrying after failure.\n\nAttempt: {attempt}/{max_attempts}\nNext retry: {next_retry}",
        level=NotificationLevel.WARNING,
    ),
    "system_alert": NotificationTemplate(
        name="system_alert",
        title_template="⚠️ System Alert",
        body_template="{message}",
        level=NotificationLevel.WARNING,
    ),
    "health_check": NotificationTemplate(
        name="health_check",
        title_template="🏥 Health Check: {status}",
        body_template="Service: {service}\nStatus: {status}\nDetails: {details}",
        level=NotificationLevel.INFO,
    ),
}


class NotificationService:
    """
    Central notification service.

    Handles formatting and delivery of notifications across
    multiple channels with deduplication and rate limiting.
    """

    def __init__(
        self,
        config: NotificationConfig | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.config = config or NotificationConfig()
        self.event_bus = event_bus or EventBus()

        # Channel handlers
        self._handlers: dict[str, Callable] = {}

        # Templates
        self._templates: dict[str, NotificationTemplate] = BUILTIN_TEMPLATES.copy()

        # Deduplication cache (key -> last_sent_time)
        self._dedupe_cache: dict[str, datetime] = {}
        self._dedupe_window = timedelta(minutes=5)

        # Rate limiting per channel
        self._rate_limits: dict[str, list[datetime]] = {}
        self._rate_limit_window = timedelta(minutes=1)
        self._rate_limit_max = 10  # Max notifications per window per channel

        # Notification history
        self._history: list[NotificationResult] = []
        self._max_history = 1000

    def register_handler(
        self,
        channel: str,
        handler: Callable[[Notification], Any],
    ) -> None:
        """Register a handler for a notification channel."""
        self._handlers[channel] = handler
        logger.debug(f"Registered handler for channel: {channel}")

    def register_template(self, template: NotificationTemplate) -> None:
        """Register a custom notification template."""
        self._templates[template.name] = template
        logger.debug(f"Registered template: {template.name}")

    async def send(
        self,
        title: str,
        message: str,
        level: NotificationLevel = NotificationLevel.INFO,
        channels: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
    ) -> list[NotificationResult]:
        """
        Send a notification to specified channels.

        Args:
            title: Notification title
            message: Notification body
            level: Severity level
            channels: Target channels (uses defaults if not specified)
            metadata: Additional data to include
            dedupe_key: Key for deduplication (optional)

        Returns:
            List of results for each channel
        """
        # Use default channels if not specified
        if channels is None:
            channels = self._get_default_channels(level)

        notification = Notification(
            id=self._generate_id(),
            title=title,
            message=message,
            level=level,
            channels=channels,
            metadata=metadata or {},
            dedupe_key=dedupe_key,
        )

        return await self._deliver(notification)

    async def send_from_template(
        self,
        template_name: str,
        variables: dict[str, Any],
        channels: list[str] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> list[NotificationResult]:
        """
        Send a notification using a template.

        Args:
            template_name: Name of the template to use
            variables: Variables to substitute in template
            channels: Target channels (uses defaults if not specified)
            extra_metadata: Additional metadata to include

        Returns:
            List of results for each channel
        """
        template = self._templates.get(template_name)
        if not template:
            raise ValueError(f"Unknown template: {template_name}")

        # Format title and body
        title = self._format_template(template.title_template, variables)
        message = self._format_template(template.body_template, variables)

        # Build metadata
        metadata = variables.copy()
        if extra_metadata:
            metadata.update(extra_metadata)

        if template.include_timestamp:
            metadata["timestamp"] = datetime.now().isoformat()

        # Use template level if not overridden
        level = template.level

        # Generate dedupe key from template and key variables
        dedupe_key = f"{template_name}:{variables.get('job_id', '')}:{variables.get('attempt', '')}"

        return await self.send(
            title=title,
            message=message,
            level=level,
            channels=channels,
            metadata=metadata,
            dedupe_key=dedupe_key,
        )

    async def notify_job_started(
        self,
        job_id: str,
        job_name: str,
        schedule: str,
        channels: list[str] | None = None,
    ) -> list[NotificationResult]:
        """Send job started notification."""
        return await self.send_from_template(
            "job_started",
            {"job_id": job_id, "job_name": job_name, "schedule": schedule},
            channels=channels,
        )

    async def notify_job_completed(
        self,
        job_id: str,
        job_name: str,
        duration: str,
        output: str = "",
        channels: list[str] | None = None,
    ) -> list[NotificationResult]:
        """Send job completed notification."""
        return await self.send_from_template(
            "job_completed",
            {
                "job_id": job_id,
                "job_name": job_name,
                "duration": duration,
                "output": output[:500] if output else "(no output)",
            },
            channels=channels,
        )

    async def notify_job_failed(
        self,
        job_id: str,
        job_name: str,
        error: str,
        attempt: int,
        max_attempts: int,
        channels: list[str] | None = None,
    ) -> list[NotificationResult]:
        """Send job failed notification."""
        return await self.send_from_template(
            "job_failed",
            {
                "job_id": job_id,
                "job_name": job_name,
                "error": error[:1000] if error else "Unknown error",
                "attempt": attempt,
                "max_attempts": max_attempts,
            },
            channels=channels,
        )

    async def notify_job_retry(
        self,
        job_id: str,
        job_name: str,
        attempt: int,
        max_attempts: int,
        next_retry: str,
        channels: list[str] | None = None,
    ) -> list[NotificationResult]:
        """Send job retry notification."""
        return await self.send_from_template(
            "job_retry",
            {
                "job_id": job_id,
                "job_name": job_name,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "next_retry": next_retry,
            },
            channels=channels,
        )

    async def _deliver(self, notification: Notification) -> list[NotificationResult]:
        """Deliver notification to all specified channels."""
        results: list[NotificationResult] = []

        # Check deduplication
        if notification.dedupe_key and self._is_duplicate(notification.dedupe_key):
            logger.debug(f"Skipping duplicate notification: {notification.dedupe_key}")
            return results

        for channel in notification.channels:
            # Check rate limit
            if self._is_rate_limited(channel):
                logger.warning(f"Rate limited on channel: {channel}")
                results.append(NotificationResult(
                    notification_id=notification.id,
                    channel=channel,
                    success=False,
                    error="Rate limited",
                ))
                continue

            # Get handler
            handler = self._handlers.get(channel)
            if not handler:
                logger.warning(f"No handler for channel: {channel}")
                results.append(NotificationResult(
                    notification_id=notification.id,
                    channel=channel,
                    success=False,
                    error=f"No handler registered for {channel}",
                ))
                continue

            # Send notification
            try:
                if asyncio.iscoroutinefunction(handler):
                    response = await handler(notification)
                else:
                    response = handler(notification)

                result = NotificationResult(
                    notification_id=notification.id,
                    channel=channel,
                    success=True,
                    response=response if isinstance(response, dict) else {},
                )

                # Emit success event
                await self.event_bus.emit(Events.NOTIFICATION_SENT, {
                    "notification_id": notification.id,
                    "channel": channel,
                    "level": notification.level.value,
                })

            except Exception as e:
                logger.error(f"Failed to send notification to {channel}: {e}")
                result = NotificationResult(
                    notification_id=notification.id,
                    channel=channel,
                    success=False,
                    error=str(e),
                )

                # Emit failure event
                await self.event_bus.emit(Events.NOTIFICATION_FAILED, {
                    "notification_id": notification.id,
                    "channel": channel,
                    "error": str(e),
                })

            results.append(result)
            self._record_send(channel)

        # Update dedupe cache
        if notification.dedupe_key:
            self._dedupe_cache[notification.dedupe_key] = datetime.now()

        # Add to history
        self._add_to_history(results)

        return results

    def _get_default_channels(self, level: NotificationLevel) -> list[str]:
        """Get default channels for a notification level."""
        # Could be configured, for now return registered handlers
        return list(self._handlers.keys())

    def _generate_id(self) -> str:
        """Generate unique notification ID."""
        import uuid
        return f"notif_{uuid.uuid4().hex[:12]}"

    def _format_template(self, template: str, variables: dict[str, Any]) -> str:
        """Format a template string with variables."""
        try:
            return template.format(**variables)
        except KeyError as e:
            logger.warning(f"Missing template variable: {e}")
            # Return template with missing vars as placeholders
            return template.format_map(DefaultDict(variables))

    def _is_duplicate(self, dedupe_key: str) -> bool:
        """Check if notification is a duplicate within the window."""
        last_sent = self._dedupe_cache.get(dedupe_key)
        if last_sent is None:
            return False
        return datetime.now() - last_sent < self._dedupe_window

    def _is_rate_limited(self, channel: str) -> bool:
        """Check if channel is rate limited."""
        now = datetime.now()
        window_start = now - self._rate_limit_window

        # Get sends in window
        sends = self._rate_limits.get(channel, [])
        sends = [t for t in sends if t > window_start]
        self._rate_limits[channel] = sends

        return len(sends) >= self._rate_limit_max

    def _record_send(self, channel: str) -> None:
        """Record a send for rate limiting."""
        if channel not in self._rate_limits:
            self._rate_limits[channel] = []
        self._rate_limits[channel].append(datetime.now())

    def _add_to_history(self, results: list[NotificationResult]) -> None:
        """Add results to history with size limit."""
        self._history.extend(results)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def get_history(
        self,
        channel: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[NotificationResult]:
        """Get notification history."""
        results = self._history

        if channel:
            results = [r for r in results if r.channel == channel]

        if since:
            results = [r for r in results if r.sent_at >= since]

        return results[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """Get notification statistics."""
        total = len(self._history)
        successful = sum(1 for r in self._history if r.success)
        failed = total - successful

        by_channel: dict[str, dict[str, int]] = {}
        for result in self._history:
            if result.channel not in by_channel:
                by_channel[result.channel] = {"total": 0, "success": 0, "failed": 0}
            by_channel[result.channel]["total"] += 1
            if result.success:
                by_channel[result.channel]["success"] += 1
            else:
                by_channel[result.channel]["failed"] += 1

        return {
            "total": total,
            "successful": successful,
            "failed": failed,
            "success_rate": successful / total if total > 0 else 0,
            "by_channel": by_channel,
            "registered_handlers": list(self._handlers.keys()),
            "registered_templates": list(self._templates.keys()),
        }

    def clear_dedupe_cache(self) -> None:
        """Clear the deduplication cache."""
        self._dedupe_cache.clear()

    def clear_history(self) -> None:
        """Clear notification history."""
        self._history.clear()


class DefaultDict(dict):
    """Dict that returns {key} for missing keys (for template formatting)."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def create_notification_service(
    config: NotificationConfig | None = None,
    event_bus: EventBus | None = None,
    slack_webhook: str | None = None,
    discord_webhook: str | None = None,
) -> NotificationService:
    """
    Factory function to create a configured NotificationService.

    Args:
        config: Notification configuration
        event_bus: Event bus for emitting events
        slack_webhook: Slack webhook URL
        discord_webhook: Discord webhook URL

    Returns:
        Configured NotificationService instance
    """
    import aiohttp

    service = NotificationService(config=config, event_bus=event_bus)

    # Register Slack handler
    if slack_webhook:
        async def slack_handler(notification: Notification) -> dict:
            level_emoji = {
                NotificationLevel.INFO: "ℹ️",
                NotificationLevel.SUCCESS: "✅",
                NotificationLevel.WARNING: "⚠️",
                NotificationLevel.ERROR: "❌",
                NotificationLevel.CRITICAL: "🚨",
            }
            emoji = level_emoji.get(notification.level, "ℹ️")

            payload = {
                "text": f"{emoji} *{notification.title}*\n{notification.message}",
                "username": "CronAgent",
                "icon_emoji": ":robot_face:",
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(slack_webhook, json=payload) as resp:
                    return {"status": resp.status}

        service.register_handler("slack", slack_handler)

    # Register Discord handler
    if discord_webhook:
        async def discord_handler(notification: Notification) -> dict:
            level_colors = {
                NotificationLevel.INFO: 0x3498db,
                NotificationLevel.SUCCESS: 0x2ecc71,
                NotificationLevel.WARNING: 0xf39c12,
                NotificationLevel.ERROR: 0xe74c3c,
                NotificationLevel.CRITICAL: 0x9b59b6,
            }

            payload = {
                "username": "CronAgent",
                "embeds": [{
                    "title": notification.title,
                    "description": notification.message,
                    "color": level_colors.get(notification.level, 0x95a5a6),
                    "timestamp": notification.created_at.isoformat(),
                }],
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(discord_webhook, json=payload) as resp:
                    return {"status": resp.status}

        service.register_handler("discord", discord_handler)

    # Register console handler (always available)
    def console_handler(notification: Notification) -> dict:
        level_prefix = {
            NotificationLevel.INFO: "[INFO]",
            NotificationLevel.SUCCESS: "[SUCCESS]",
            NotificationLevel.WARNING: "[WARNING]",
            NotificationLevel.ERROR: "[ERROR]",
            NotificationLevel.CRITICAL: "[CRITICAL]",
        }
        prefix = level_prefix.get(notification.level, "[INFO]")
        print(f"{prefix} {notification.title}: {notification.message}")
        return {"printed": True}

    service.register_handler("console", console_handler)

    return service
