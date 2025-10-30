"""Diplomacy overview widgets for the Survival Truck UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import networkx as nx
from textual.widget import Widget

from ..factions import FactionRecord
from ..world.graph import allied_factions


@dataclass
class DiplomacySnapshot:
    """Light-weight container describing current diplomacy state."""

    factions: Mapping[str, FactionRecord]
    graph: nx.Graph | None


class DiplomacyView(Widget):
    """Render faction standings and alliances for quick reference."""

    def __init__(
        self,
        *,
        title: str = "Diplomacy",
        alliance_threshold: float = 15.0,
        border_style: str = "purple",
    ) -> None:
        super().__init__(id="diplomacy")
        self.title = title
        self.alliance_threshold = float(alliance_threshold)
        self.border_style = border_style
        self._snapshot = DiplomacySnapshot(factions={}, graph=None)

    # ------------------------------------------------------------------
    def update_snapshot(
        self, factions: Mapping[str, FactionRecord], graph: nx.Graph | None
    ) -> None:
        """Store the latest diplomacy state and refresh the widget."""

        self._snapshot = DiplomacySnapshot(factions=dict(factions), graph=graph)
        self.refresh()

    # ------------------------------------------------------------------
    def render(self):  # type: ignore[override]
        from rich.console import Group
        from rich.panel import Panel
        from rich.table import Table

        factions = self._snapshot.factions
        graph = self._snapshot.graph

        if not factions:
            return Panel(
                "No faction data available",
                title=self.title,
                border_style=self.border_style,
            )

        if graph is None or graph.number_of_nodes() == 0:
            return Panel(
                "Diplomacy records pending",
                title=self.title,
                border_style=self.border_style,
            )

        standings_table = Table.grid(padding=(0, 1), expand=True)
        standings_table.add_row(
            "[bold]Faction A[/bold]", "[bold]Faction B[/bold]", "[bold]Standing[/bold]"
        )

        edges = sorted(
            (
                faction_a,
                faction_b,
                float(data.get("weight", graph.graph.get("neutral_value", 0.0))),
            )
            for faction_a, faction_b, data in graph.edges(data=True)
        )

        if edges:
            for faction_a, faction_b, value in edges:
                standings_table.add_row(faction_a, faction_b, f"{value:+.1f}")
        else:
            neutral = float(graph.graph.get("neutral_value", 0.0))
            standings_table.add_row("(no records)", "", f"{neutral:+.1f}")

        alliances_table = Table.grid(padding=(0, 1), expand=True)
        alliances_table.add_row("[bold]Faction[/bold]", "[bold]Allies[/bold]")

        alliance_rows = 0
        for faction in sorted(graph.nodes):
            allies = sorted(
                allied_factions(graph, faction, threshold=self.alliance_threshold)
            )
            if not allies:
                continue
            alliance_rows += 1
            alliances_table.add_row(faction, ", ".join(allies))

        if alliance_rows == 0:
            alliances_table.add_row("(none)", "")

        body = Group(
            Panel(standings_table, title="Standings", border_style=self.border_style),
            Panel(alliances_table, title="Alliances", border_style=self.border_style),
        )

        return Panel(body, title=self.title, border_style=self.border_style)


__all__ = ["DiplomacySnapshot", "DiplomacyView"]
