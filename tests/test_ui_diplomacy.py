"""Tests covering the diplomacy dashboard widget."""

from __future__ import annotations

from rich.console import Console

from game.factions import Faction, FactionDiplomacy
from game.ui.diplomacy import DiplomacyView


def _render_widget(widget: DiplomacyView) -> str:
    console = Console(width=80, record=True)
    console.print(widget.render())
    return console.export_text(clear=False)


def test_diplomacy_view_renders_standings_and_alliances() -> None:
    view = DiplomacyView()
    factions = {
        "Northern Guild": Faction(name="Northern Guild"),
        "Dune Riders": Faction(name="Dune Riders"),
        "River Union": Faction(name="River Union"),
    }
    diplomacy = FactionDiplomacy()
    diplomacy.set_standing("Northern Guild", "Dune Riders", 22.5)
    diplomacy.set_standing("Northern Guild", "River Union", -12.0)
    graph = diplomacy.as_graph(factions.keys())

    view.update_snapshot(factions, graph)
    output = _render_widget(view)

    assert "Standings" in output
    assert "Northern Guild" in output
    assert "+22.5" in output
    assert "Alliances" in output
    assert "Dune Riders" in output


def test_diplomacy_view_handles_empty_state() -> None:
    view = DiplomacyView()
    view.update_snapshot({}, None)
    output = _render_widget(view)

    assert "No faction data available" in output
