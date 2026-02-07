"""
Event bus for decoupled inter-component communication.

Enables loose coupling between agent, scheduler, channels, and skills.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# Type alias for event handlers
EventHandler = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class Event:
    """Represents a bus event."""

    name: str
    payload: dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def __repr__(self) -> str:
        return f"Event(name={self.name!r}, payload_keys={list(self.payload.keys())})"


class EventBus:
    """
    Central message bus for component communication.

    Supports:
    - Async event handlers
    - Pattern-based subscriptions (e.g., "agent.*")
    - Event history for debugging
    - Safe handler execution with error isolation

    Event naming conventions:
    - agent.* - Agent lifecycle events (agent.started, agent.message, agent.completed)
    - scheduler.* - Scheduler events (scheduler.job_started, scheduler.job_completed)
    - channel.* - Channel events (channel.message_received, channel.connected)
    - memory.* - Memory events (memory.session_created, memory.insight_extracted)
    """

    def __init__(self, max_history: int = 1000) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._event_history: list[Event] = []
        self._max_history = max_history
        self._lock = asyncio.Lock()

    def subscribe(self, event_pattern: str, handler: EventHandler) -> Callable[[], None]:
        """
        Subscribe to events matching a pattern.

        Patterns support wildcards:
        - "agent.*" matches all agent events
        - "job.completed" matches exact event
        - "*" matches all events

        Args:
            event_pattern: Event pattern to subscribe to
            handler: Async function to handle events

        Returns:
            Unsubscribe function
        """
        self._handlers[event_pattern].append(handler)
        logger.debug(f"Subscribed to {event_pattern}")

        def unsubscribe() -> None:
            if handler in self._handlers[event_pattern]:
                self._handlers[event_pattern].remove(handler)
                logger.debug(f"Unsubscribed from {event_pattern}")

        return unsubscribe

    def unsubscribe(self, event_pattern: str, handler: EventHandler) -> None:
        """Unsubscribe a handler from an event pattern."""
        if handler in self._handlers[event_pattern]:
            self._handlers[event_pattern].remove(handler)

    async def emit(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        """
        Emit an event to all matching subscribers.

        Args:
            event_name: Name of the event (e.g., "agent.message")
            payload: Event data
        """
        payload = payload or {}
        event = Event(name=event_name, payload=payload)

        # Store in history
        async with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history = self._event_history[-self._max_history :]

        logger.debug(f"Emitting event: {event_name}")

        # Find matching handlers
        handlers_to_call: list[EventHandler] = []
        for pattern, handlers in self._handlers.items():
            if self._matches(pattern, event_name):
                handlers_to_call.extend(handlers)

        # Call all handlers concurrently
        if handlers_to_call:
            await asyncio.gather(
                *[self._safe_call(h, event_name, payload) for h in handlers_to_call],
                return_exceptions=True,
            )

    def _matches(self, pattern: str, event_name: str) -> bool:
        """Check if event name matches pattern."""
        if pattern == "*":
            return True
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            return event_name.startswith(prefix + ".")
        return pattern == event_name

    async def _safe_call(
        self,
        handler: EventHandler,
        event_name: str,
        payload: dict[str, Any],
    ) -> None:
        """Safely call handler with error handling."""
        try:
            await handler(event_name, payload)
        except Exception as e:
            logger.error(f"Event handler error for {event_name}: {e}", exc_info=True)

    def get_recent_events(self, count: int = 50) -> list[Event]:
        """Get recent events from history."""
        return self._event_history[-count:]

    def get_events_by_pattern(self, pattern: str, count: int = 50) -> list[Event]:
        """Get recent events matching a pattern."""
        matching = [e for e in self._event_history if self._matches(pattern, e.name)]
        return matching[-count:]

    def clear_history(self) -> None:
        """Clear event history."""
        self._event_history.clear()

    @property
    def handler_count(self) -> int:
        """Total number of registered handlers."""
        return sum(len(handlers) for handlers in self._handlers.values())


# Common event names as constants for type safety
class Events:
    """Common event names."""

    # Agent events
    AGENT_STARTED = "agent.started"
    AGENT_MESSAGE = "agent.message"
    AGENT_TOOL_USE = "agent.tool_use"
    AGENT_TOOL_RESULT = "agent.tool_result"
    AGENT_COMPLETED = "agent.completed"
    AGENT_ERROR = "agent.error"

    # Scheduler events
    SCHEDULER_STARTED = "scheduler.started"
    SCHEDULER_STOPPED = "scheduler.stopped"
    JOB_CREATED = "scheduler.job_created"
    JOB_UPDATED = "scheduler.job_updated"
    JOB_DELETED = "scheduler.job_deleted"
    JOB_SCHEDULED = "scheduler.job_scheduled"
    JOB_STARTED = "scheduler.job_started"
    JOB_EXECUTING = "scheduler.job_executing"
    JOB_COMPLETED = "scheduler.job_completed"
    JOB_FAILED = "scheduler.job_failed"
    JOB_MISSED = "scheduler.job_missed"
    JOB_RETRY = "scheduler.job_retry"
    JOB_NOTIFICATION = "scheduler.job_notification"

    # Channel events
    CHANNEL_CONNECTED = "channel.connected"
    CHANNEL_DISCONNECTED = "channel.disconnected"
    CHANNEL_MESSAGE_RECEIVED = "channel.message_received"
    CHANNEL_MESSAGE_SENT = "channel.message_sent"
    CHANNEL_ERROR = "channel.error"

    # Memory events
    SESSION_CREATED = "memory.session_created"
    SESSION_RESUMED = "memory.session_resumed"
    SESSION_COMPLETED = "memory.session_completed"
    INSIGHT_EXTRACTED = "memory.insight_extracted"
    KNOWLEDGE_INDEXED = "memory.knowledge_indexed"

    # Notification events
    NOTIFICATION_SENT = "notification.sent"
    NOTIFICATION_FAILED = "notification.failed"
