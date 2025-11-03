"""Dashboard composition helpers for the text UI."""

from __future__ import annotations

from collections.abc import Mapping

from rich.console import RenderableType
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from textual.binding import Binding
from textual.widget import Widget

from .channels import NotificationChannel, TurnLogChannel


def _build_stats_panel(stats: Mapping[str, str]) -> RenderableType:
    table = Table.grid(padding=(0, 1), expand=True)
    for key, value in stats.items():
        table.add_row(f"[bold]{key}[/bold]", str(value))
    return Panel(table, title="Campaign Stats", border_style="blue")


def _placeholder_panel(title: str, message: str, *, border_style: str = "blue") -> RenderableType:
    return Panel(message, title=title, border_style=border_style)


def _build_layout_panel(config: Mapping[str, str], *, unsaved: bool = False) -> RenderableType:
    """Build the panel summarising the current hex layout configuration.

    Args:
        config: Mapping of configuration keys to human‑readable strings.
        unsaved: If ``True``, an asterisk is appended to the panel title to
            indicate that the current settings differ from the on‑disk
            configuration.

    Returns:
        RenderableType: A Panel containing the configuration summary.
    """
    table = Table.grid(padding=(0, 1), expand=True)
    for key, value in config.items():
        table.add_row(f"[bold]{key}[/bold]", str(value))
    title = "Hex Layout*" if unsaved else "Hex Layout"
    return Panel(table, title=title, border_style="cyan")


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
        self._stats: dict[str, str] = {str(key): str(value) for key, value in (stats or {}).items()}
        self._layout_config: dict[str, str] | None = None
        # Track whether the layout has unsaved changes to toggle the star.
        self._layout_config_dirty: bool = False
        # Optional site context information displayed when a site is selected.
        self._site_context: list[str] = []

    def update_stats(self, stats: Mapping[str, str]) -> None:
        self._stats = {str(key): str(value) for key, value in stats.items()}
        if self._focus_detail:
            self._stats["Focus"] = self._focus_detail
        self.refresh()

    def update_site_context(self, lines: list[str]) -> None:
        """Update the additional context shown when a map site is selected.

        The provided ``lines`` will be displayed in a small panel beneath
        the statistics.  Passing an empty list clears the context panel.

        Args:
            lines: A list of strings describing events, missions or
                negotiations related to the selected site.
        """
        # Store a shallow copy to avoid external mutation.
        self._site_context = list(lines) if lines else []
        self.refresh()

    def set_focus_detail(self, detail: str | None) -> None:
        self._focus_detail = detail
        if detail:
            self._stats["Focus"] = detail
        elif "Focus" in self._stats:
            del self._stats["Focus"]
        self.refresh()

    def update_layout_config(self, config: Mapping[str, str], *, unsaved: bool = False) -> None:
        """Update the displayed layout configuration summary.

        Args:
            config: Mapping of configuration fields to their current values.
            unsaved: When ``True`` a star will be appended to the panel title
                to indicate there are unsaved changes.
        """
        self._layout_config = {str(key): str(value) for key, value in config.items()}
        self._layout_config_dirty = bool(unsaved)
        self.refresh()

    def action_clear_notifications(self) -> None:
        self.notification_channel.clear()
        self.refresh()

    def render(self) -> RenderableType:
        layout = Layout(name="status")
        stats_mapping: Mapping[str, str] = self._stats
        stats_panel = (
            _build_stats_panel(stats_mapping)
            if stats_mapping
            else _placeholder_panel("Campaign Stats", "No statistics available")
        )
        notifications = self.notification_channel.render_panel(title="Notifications")
        layout_sections = [Layout(stats_panel, name="stats", ratio=2)]
        if self._layout_config:
            layout_sections.append(
                Layout(
                    _build_layout_panel(self._layout_config, unsaved=self._layout_config_dirty),
                    name="layout",
                    ratio=1,
                )
            )
        layout_sections.append(Layout(notifications, name="notifications", ratio=1))
        # Insert a site context panel if any context lines are provided.
        if self._site_context:
            from rich.text import Text
            context_body = Text()
            for line in self._site_context:
                context_body.append(line + "\n")
            layout_sections.append(
                Layout(
                    Panel(context_body, title="Site Context", border_style="magenta"),
                    name="site_context",
                    ratio=1,
                )
            )
        layout.split_column(*layout_sections)
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

    def render(self) -> RenderableType:
        return self.log_channel.render_table(title=self.title)


__all__ = ["DashboardView", "TurnLogWidget"]