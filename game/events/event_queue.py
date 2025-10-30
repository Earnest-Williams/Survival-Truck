"""Event queue for scheduling world updates between turns."""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from itertools import count
from typing import Any, Dict, Iterable, List, Tuple


@dataclass
class QueuedEvent:
    """A scheduled world event."""

    day: int
    event_type: str
    payload: Dict[str, Any]


class EventQueue:
    """Manages future events keyed by the day they should resolve."""

    def __init__(self) -> None:
        self._heap: List[Tuple[int, int, QueuedEvent]] = []
        self._counter = count()

    def schedule(
        self, day: int, event_type: str, payload: Dict[str, Any] | None = None
    ) -> None:
        """Schedule an event to fire on the provided day."""

        if day < 0:
            raise ValueError("day must be non-negative")
        event = QueuedEvent(day=day, event_type=event_type, payload=payload or {})
        heapq.heappush(self._heap, (day, next(self._counter), event))

    def schedule_in(
        self,
        days_from_now: int,
        current_day: int,
        event_type: str,
        payload: Dict[str, Any] | None = None,
    ) -> None:
        """Convenience helper to schedule relative to the current day."""

        if days_from_now < 0:
            raise ValueError("days_from_now must be non-negative")
        self.schedule(current_day + days_from_now, event_type, payload)

    def events_for_day(self, day: int) -> List[QueuedEvent]:
        """Return events queued for the specified day without removing them."""

        return [entry[2] for entry in sorted(self._heap) if entry[0] == day]

    def pop_events_for_day(self, day: int) -> Iterable[QueuedEvent]:
        """Retrieve and remove events scheduled for the provided day."""

        popped: List[QueuedEvent] = []
        to_requeue: List[Tuple[int, int, QueuedEvent]] = []
        while self._heap and self._heap[0][0] <= day:
            event_day, order, event = heapq.heappop(self._heap)
            if event_day == day:
                popped.append(event)
            else:
                to_requeue.append((event_day, order, event))
        for entry in to_requeue:
            heapq.heappush(self._heap, entry)
        return popped

    def has_events(self) -> bool:
        return bool(self._heap)

    def upcoming_days(self) -> List[int]:
        return sorted({day for day, _, _ in self._heap})

    def clear(self) -> None:
        self._heap.clear()
        self._counter = count()
