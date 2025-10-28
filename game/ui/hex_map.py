"""Hex map rendering utilities for the text UI."""

from __future__ import annotations

from typing import Dict, Mapping, Sequence, Tuple

Coordinate = Tuple[int, int]


class HexMapView:
    """Render a hex map using the Rich text UI primitives."""

    def __init__(
        self,
        *,
        terrain_symbols: Mapping[str, str] | None = None,
        unknown_symbol: str = "??",
        title: str = "Hex Map",
    ) -> None:
        self.terrain_symbols: Dict[str, str] = {
            "plains": "Pl",
            "forest": "Fo",
            "tundra": "Tu",
            "mountain": "Mt",
            "coast": "Co",
            "ruin": "Ru",
            "wasteland": "Wa",
        }
        if terrain_symbols:
            self.terrain_symbols.update({str(key): str(value) for key, value in terrain_symbols.items()})
        self.unknown_symbol = unknown_symbol
        self.title = title

    def render(
        self,
        grid: Sequence[Sequence[str]],
        *,
        highlights: Mapping[Coordinate, str] | None = None,
    ):
        """Return a Rich renderable representing the provided grid."""

        from rich.panel import Panel
        from rich.text import Text

        lines = []
        highlight_map: Dict[Coordinate, str] = (
            { (int(r), int(c)): str(text) for (r, c), text in highlights.items() }
            if highlights
            else {}
        )

        for row_index, row in enumerate(grid):
            prefix = " " if row_index % 2 else ""
            cell_text: list[str] = []
            for col_index, terrain in enumerate(row):
                coord = (row_index, col_index)
                if coord in highlight_map:
                    cell_text.append(highlight_map[coord])
                    continue
                symbol = self.terrain_symbols.get(str(terrain), None)
                if symbol is None:
                    symbol = str(terrain)[:2].title() if terrain else self.unknown_symbol
                cell_text.append(symbol)
            lines.append(prefix + " ".join(cell_text))

        if not lines:
            lines.append("(no map data)")

        map_text = Text.from_markup("\n".join(lines))
        return Panel(map_text, title=self.title, border_style="cyan")


__all__ = ["HexMapView", "Coordinate"]
