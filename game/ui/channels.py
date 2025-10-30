"""Logging and notification channels for the text user interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Mapping, Sequence

from ..events.event_queue import QueuedEvent


if TYPE_CHECKING:
    from ..engine.turn_engine import TurnContext


@dataclass
class LogEntry:
    """High level summary of a completed turn."""

    day: int
    summary: str
    highlights: List[str] = field(default_factory=list)
    events: List[str] = field(default_factory=list)
    scheduled: List[str] = field(default_factory=list)


@dataclass
class NotificationRecord:
    """Light-weight notification for surfacing events to the UI."""

    day: int
    message: str
    category: str = "info"
    payload: Dict[str, Any] = field(default_factory=dict)

    def format_brief(self) -> str:
        payload_bits = [f"{key}={value}" for key, value in self.payload.items()]
        payload_text = f" ({', '.join(payload_bits)})" if payload_bits else ""
        return f"[{self.category}] Day {self.day}: {self.message}{payload_text}"


class TurnLogChannel:
    """Collects turn summaries that can be rendered in the dashboard."""

    def __init__(self, *, max_entries: int = 100) -> None:
        self.max_entries = max_entries
        self._entries: List[LogEntry] = []

    @property
    def entries(self) -> Sequence[LogEntry]:
        return tuple(self._entries)

    def push(self, entry: LogEntry) -> None:
        self._entries.append(entry)
        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries :]

    def record_context(
        self, context: "TurnContext", *, summary: str | None = None
    ) -> LogEntry:
        """Create a log entry from the provided turn context."""

        summary_text = summary or _build_default_summary(context)
        highlights = (
            list(context.summary_lines)
            if getattr(context, "summary_lines", None)
            else []
        )
        events = [_format_event_line(event) for event in context.events]
        scheduled = [
            _format_scheduled_line(event) for event in context.scheduled_events
        ]
        entry = LogEntry(
            day=context.day,
            summary=summary_text,
            highlights=highlights,
            events=events,
            scheduled=scheduled,
        )
        self.push(entry)
        return entry

    # Rendering helpers -------------------------------------------------
    def render_table(self, *, title: str = "Turn Log"):
        """Return a Rich renderable summarising recent log entries."""

        from rich import box
        from rich.panel import Panel
        from rich.table import Table

        table = Table(title=title, expand=True, box=box.SIMPLE_HEAVY)
        table.add_column("Day", justify="right", no_wrap=True)
        table.add_column("Summary", overflow="fold")
        table.add_column("Highlights", overflow="fold")
        table.add_column("Events", overflow="fold")

        for entry in reversed(self._entries):
            highlight_text = "\n".join(entry.highlights) if entry.highlights else "—"
            event_lines = entry.events + entry.scheduled
            event_text = "\n".join(event_lines) if event_lines else "—"
            table.add_row(str(entry.day), entry.summary, highlight_text, event_text)

        return Panel(table, title=title, border_style="yellow")


class NotificationChannel:
    """Capture lightweight notifications for dashboard display."""

    def __init__(self, *, max_entries: int = 200) -> None:
        self.max_entries = max_entries
        self._notifications: List[NotificationRecord] = []

    @property
    def notifications(self) -> Sequence[NotificationRecord]:
        return tuple(self._notifications)

    def push(self, notification: NotificationRecord) -> None:
        self._notifications.append(notification)
        if len(self._notifications) > self.max_entries:
            self._notifications = self._notifications[-self.max_entries :]

    def notify(
        self,
        day: int,
        message: str,
        *,
        category: str = "info",
        payload: Mapping[str, Any] | None = None,
    ) -> NotificationRecord:
        record = NotificationRecord(
            day=day, message=message, category=category, payload=dict(payload or {})
        )
        self.push(record)
        return record

    def extend_from_events(self, day: int, events: Iterable[QueuedEvent]) -> None:
        for event in events:
            payload = dict(event.payload)
            message = str(
                payload.pop("message", event.event_type.replace("_", " ").title())
            )
            payload.setdefault("event_type", event.event_type)
            payload.setdefault("scheduled_for", event.day)
            self.push(
                NotificationRecord(
                    day=day,
                    message=message,
                    category="event",
                    payload=payload,
                )
            )

    def extend_from_schedule(self, scheduled: Iterable[QueuedEvent]) -> None:
        for event in scheduled:
            payload = dict(event.payload)
            payload.setdefault("event_type", event.event_type)
            payload.setdefault("scheduled_for", event.day)
            self.push(
                NotificationRecord(
                    day=event.day,
                    message=f"Scheduled {event.event_type}",
                    category="schedule",
                    payload=payload,
                )
            )

    def clear(self) -> None:
        """Remove all stored notifications."""

        self._notifications.clear()

    def render_panel(self, *, title: str = "Notifications"):
        from rich.panel import Panel
        from rich.table import Table

        table = Table(expand=True)
        table.add_column("Day", justify="right", no_wrap=True)
        table.add_column("Category", no_wrap=True)
        table.add_column("Message", overflow="fold")

        for record in reversed(self._notifications[-10:]):
            table.add_row(str(record.day), record.category, record.format_brief())

        return Panel(table, title=title, border_style="magenta")


# ---------------------------------------------------------------------------
def _format_event_line(event: QueuedEvent) -> str:
    payload = ", ".join(f"{key}={value}" for key, value in event.payload.items())
    if payload:
        return f"{event.event_type} ({payload})"
    return event.event_type


def _format_scheduled_line(event: QueuedEvent) -> str:
    payload = ", ".join(f"{key}={value}" for key, value in event.payload.items())
    base = f"Day {event.day}: {event.event_type}"
    if payload:
        base = f"{base} ({payload})"
    return base


def _build_default_summary(context: "TurnContext") -> str:
    if getattr(context, "summary_lines", None):
        return " | ".join(context.summary_lines)
    if context.events:
        return ", ".join(event.event_type for event in context.events)
    if context.scheduled_events:
        return f"Scheduled {len(context.scheduled_events)} future event(s)"
    return "Quiet day on the road."


__all__ = [
    "LogEntry",
    "NotificationChannel",
    "NotificationRecord",
    "TurnLogChannel",
]
