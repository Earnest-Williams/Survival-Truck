"""Standalone demo showcasing the HexCanvas widget."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header

from game.ui.hex_canvas import HexCanvas


class Demo(App[None]):
    """Minimal application rendering a HexCanvas for local testing."""

    CSS = """
    Screen { layout: grid; grid-rows: auto 1fr auto; }
    #body { layout: grid; padding: 1; }
    HexCanvas { border: none; }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="body"):
            tiles = {}
            labels = {}
            for q in range(8):
                for r in range(6):
                    terrain_code = (
                        "Fo"
                        if (q + r) % 5 == 0
                        else "Ba"
                        if (q * r) % 7 == 0
                        else "Sc"
                    )
                    tiles[(q, r)] = terrain_code
                    labels[(q, r)] = {"Fo": "Fo", "Ba": "Ba", "Sc": "Sc"}[terrain_code]
            yield HexCanvas(cols=8, rows=6, radius=12, tiles=tiles, labels=labels)
        yield Footer()


if __name__ == "__main__":
    Demo().run()
