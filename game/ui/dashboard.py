"""Dashboard composition helpers for the text UI."""

from __future__ import annotations

from typing import Dict, Mapping

from rich.console import RenderableType
from textual.binding import Binding
from textual.widget import Widget

from .channels import NotificationChannel, TurnLogChannel


def _build_stats_panel(stats: Mapping[str, str]):
    from rich.panel import Panel
    from rich.table import Table

    table = Table.grid(padding=(0, 1), expand=True)
    for key, value in stats.items():
        table.add_row(f"[bold]{key}[/bold]", str(value))
    return Panel(table, title="Campaign Stats", border_style="blue")


def _placeholder_panel(title: str, message: str, *, border_style: str = "blue") -> RenderableType:
    from rich.panel import Panel

    return Panel(message, title=title, border_style=border_style)


class DashboardView(Widget):
    """Display expedition status information alongside notifications."""

    BINDINGS = [
        Binding("c", "clear_notifications", "Clear Notifs", show=False),
    ]

    def __init__(
        self,
        *,
        title: str = "Expedition Dashboard",
        stats: Mapping[str, str] | None = None,
        notification_channel: NotificationChannel | None = None,
    ) -> None:
        super().__init__(id="status")
        self.title = title
        self._focus_detail: str | None = None
        self.notification_channel = notification_channel or NotificationChannel()
        self._stats: Dict[str, str] = {str(key): str(value) for key, value in (stats or {}).items()}

    def update_stats(self, stats: Mapping[str, str]) -> None:
        self._stats = {str(key): str(value) for key, value in stats.items()}
        if self._focus_detail:
            self._stats["Focus"] = self._focus_detail
        self.refresh()

    def set_focus_detail(self, detail: str | None) -> None:
        self._focus_detail = detail
        if detail:
            self._stats["Focus"] = detail
        elif "Focus" in self._stats:
            del self._stats["Focus"]
        self.refresh()

    def action_clear_notifications(self) -> None:
        self.notification_channel.clear()
        self.refresh()

    def render(self):  # type: ignore[override]
        from rich.layout import Layout

        layout = Layout(name="status")
        stats_mapping: Mapping[str, str] = self._stats
        stats_panel = _build_stats_panel(stats_mapping) if stats_mapping else _placeholder_panel(
            "Campaign Stats", "No statistics available"
        )
        notifications = self.notification_channel.render_panel(title="Notifications")
        layout.split_column(
            Layout(stats_panel, name="stats", ratio=2),
            Layout(notifications, name="notifications", ratio=1),
        )
        return layout


class TurnLogWidget(Widget):
    """Render the recent turn summaries using the existing channel helpers."""

    log_channel: TurnLogChannel

    def __init__(self, log_channel: TurnLogChannel, *, title: str = "Turn Log") -> None:
        super().__init__(id="log")
        self.log_channel = log_channel
        self.title = title

    def refresh_from_channel(self) -> None:
        self.refresh()

    def render(self):  # type: ignore[override]
        return self.log_channel.render_table(title=self.title)


__all__ = ["DashboardView", "TurnLogWidget"]
