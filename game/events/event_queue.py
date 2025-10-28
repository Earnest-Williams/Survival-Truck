"""Event queue for scheduling world updates between turns."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Iterable, List


@dataclass
class QueuedEvent:
    """A scheduled world event."""

    day: int
    event_type: str
    payload: Dict[str, Any]


class EventQueue:
    """Manages future events keyed by the day they should resolve."""

    def __init__(self) -> None:
        self._events: Dict[int, Deque[QueuedEvent]] = defaultdict(deque)

    def schedule(self, day: int, event_type: str, payload: Dict[str, Any] | None = None) -> None:
        """Schedule an event to fire on the provided day."""

        if day < 0:
            raise ValueError("day must be non-negative")
        event = QueuedEvent(day=day, event_type=event_type, payload=payload or {})
        self._events[day].append(event)

    def schedule_in(self, days_from_now: int, current_day: int, event_type: str, payload: Dict[str, Any] | None = None) -> None:
        """Convenience helper to schedule relative to the current day."""

        if days_from_now < 0:
            raise ValueError("days_from_now must be non-negative")
        self.schedule(current_day + days_from_now, event_type, payload)

    def events_for_day(self, day: int) -> List[QueuedEvent]:
        """Return events queued for the specified day without removing them."""

        return list(self._events.get(day, ()))

    def pop_events_for_day(self, day: int) -> Iterable[QueuedEvent]:
        """Retrieve and remove events scheduled for the provided day."""

        return list(self._events.pop(day, ()))

    def has_events(self) -> bool:
        return any(self._events.values())

    def upcoming_days(self) -> List[int]:
        return sorted(self._events.keys())

    def clear(self) -> None:
        self._events.clear()

