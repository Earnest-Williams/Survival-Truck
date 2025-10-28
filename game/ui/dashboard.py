"""Dashboard composition helpers for the text UI."""

from __future__ import annotations

from typing import Mapping, Sequence

from .channels import NotificationChannel, TurnLogChannel
from .hex_map import HexMapView
from .truck_layout import TruckLayoutView


class DashboardView:
    """Compose map, truck, and log views into a single Rich layout."""

    def __init__(self, *, title: str = "Expedition Dashboard") -> None:
        self.title = title

    def render(
        self,
        *,
        map_view: HexMapView,
        map_data: Sequence[Sequence[str]],
        truck_view: TruckLayoutView,
        truck,
        log_channel: TurnLogChannel,
        notification_channel: NotificationChannel,
        stats: Mapping[str, str] | None = None,
    ):
        from rich.layout import Layout

        layout = Layout(name="root")
        left = Layout(name="left", ratio=2)
        right = Layout(name="right", ratio=1)
        layout.split_row(left, right)

        if stats:
            left.split_column(
                Layout(map_view.render(map_data), name="map", ratio=3),
                Layout(_build_stats_panel(stats), name="stats", ratio=1),
            )
        else:
            left.split_column(Layout(map_view.render(map_data), name="map", ratio=1))

        right.split_column(
            Layout(truck_view.render(truck), name="truck"),
            Layout(notification_channel.render_panel(), name="notifications"),
            Layout(log_channel.render_table(), name="log"),
        )

        return layout

    def display(
        self,
        *,
        console=None,
        **render_kwargs,
    ):
        from rich.console import Console

        con = console or Console()
        if self.title:
            con.print(f"[bold underline]{self.title}[/bold underline]")
        con.print(self.render(**render_kwargs))


def _build_stats_panel(stats: Mapping[str, str]):
    from rich.panel import Panel
    from rich.table import Table

    table = Table.grid(padding=(0, 1), expand=True)
    for key, value in stats.items():
        table.add_row(f"[bold]{key}[/bold]", str(value))
    return Panel(table, title="Campaign Stats", border_style="blue")


__all__ = ["DashboardView"]
