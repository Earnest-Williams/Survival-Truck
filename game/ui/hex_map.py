"""Hex map rendering utilities for the text UI."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import cast

from rich.console import RenderableType
from rich.panel import Panel
from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.message_pump import MessagePump
from textual.reactive import Reactive, reactive
from textual.widget import Widget

Coordinate = tuple[int, int]
GridData = tuple[tuple[str, ...], ...]


def _normalise_map(
    grid: Sequence[Sequence[str]] | None,
) -> GridData:
    """Return an immutable copy of the provided map grid."""

    if not grid:
        return cast(GridData, tuple())
    return cast(
        GridData,
        tuple(tuple(str(cell) for cell in row) for row in grid),
    )


def _render_hex_map(
    grid: Sequence[Sequence[str]],
    terrain_symbols: Mapping[str, str],
    unknown_symbol: str,
    title: str,
    highlight_map: Mapping[Coordinate, str],
) -> RenderableType:
    lines: list[str] = []
    for row_index, row in enumerate(grid):
        prefix = " " if row_index % 2 else ""
        cell_text: list[str] = []
        for col_index, terrain in enumerate(row):
            coord = (row_index, col_index)
            if coord in highlight_map:
                cell_text.append(highlight_map[coord])
                continue
            symbol = terrain_symbols.get(str(terrain), None)
            if symbol is None:
                symbol = str(terrain)[:2].title() if terrain else unknown_symbol
            cell_text.append(symbol)
        lines.append(prefix + " ".join(cell_text))

    if not lines:
        lines.append("(no map data)")

    map_text = Text.from_markup("\n".join(lines))
    return Panel(map_text, title=title, border_style="cyan")


@dataclass(frozen=True)
class MapSelection:
    """Details of the currently selected map coordinate."""

    coordinate: Coordinate
    terrain: str


class HexMapView(Widget):
    """Render and interact with the overworld hex map."""

    DEFAULT_TERRAIN_SYMBOLS: Mapping[str, str] = {
        "plains": "Pl",
        "forest": "Fo",
        "tundra": "Tu",
        "mountain": "Mt",
        "coast": "Co",
        "ruin": "Ru",
        "wasteland": "Wa",
    }

    BINDINGS = [
        Binding("left", "move_left", "←"),
        Binding("right", "move_right", "→"),
        Binding("up", "move_up", "↑"),
        Binding("down", "move_down", "↓"),
        Binding("enter", "confirm", "Add Waypoint"),
    ]

    class CoordinateSelected(Message):
        """Posted when the user confirms a map coordinate."""

        def __init__(self, sender: HexMapView, selection: MapSelection) -> None:
            super().__init__()
            self.selection = selection
            self.set_sender(cast(MessagePump, sender))

    _grid: Reactive[GridData] = reactive(tuple(), layout=True)
    cursor: Reactive[Coordinate] = reactive((0, 0), layout=False)

    def __init__(
        self,
        *,
        terrain_symbols: Mapping[str, str] | None = None,
        unknown_symbol: str = "??",
        title: str = "Hex Map",
        grid: Sequence[Sequence[str]] | None = None,
    ) -> None:
        super().__init__(id="map")
        self.terrain_symbols: dict[str, str] = dict(self.DEFAULT_TERRAIN_SYMBOLS)
        if terrain_symbols:
            self.terrain_symbols.update(
                {str(key): str(value) for key, value in terrain_symbols.items()}
            )
        self.unknown_symbol = unknown_symbol
        self.title = title
        self._highlights: MutableMapping[Coordinate, str] = {}
        if grid is not None:
            self.grid_data = _normalise_map(grid)

    @property
    def grid_data(self) -> GridData:
        """Return the current reactive grid value."""

        grid_value: GridData = self._grid
        return grid_value

    @grid_data.setter
    def grid_data(self, grid: GridData) -> None:
        self._grid = grid

    def set_map_data(self, grid: Sequence[Sequence[str]]) -> None:
        self.grid_data = _normalise_map(grid)
        max_row = max(len(grid) - 1, 0)
        max_col = max((len(row) for row in grid), default=1) - 1 if grid else 0
        cursor: Coordinate = self.cursor
        row = min(cursor[0], max_row)
        col = min(cursor[1], max_col)
        self.cursor = (row, col)
        self.refresh()

    def set_highlights(self, highlights: Mapping[Coordinate, str]) -> None:
        self._highlights = {(int(r), int(c)): str(text) for (r, c), text in highlights.items()}
        self.refresh()

    def move_cursor(self, row_delta: int, col_delta: int) -> None:
        grid = self.grid_data
        if not grid:
            return
        cursor: Coordinate = self.cursor
        row, col = cursor
        max_row = len(grid) - 1
        max_col = max((len(r) for r in grid), default=1) - 1 if grid else 0
        row = max(0, min(max_row, row + row_delta))
        col = max(0, min(max_col, col + col_delta))
        if (row, col) != cursor:
            self.cursor = (row, col)
            self.refresh()
            self._announce_selection()

    def action_move_left(self) -> None:
        self.move_cursor(0, -1)

    def action_move_right(self) -> None:
        self.move_cursor(0, 1)

    def action_move_up(self) -> None:
        self.move_cursor(-1, 0)

    def action_move_down(self) -> None:
        self.move_cursor(1, 0)

    def action_confirm(self) -> None:
        grid = self.grid_data
        if not grid:
            return
        cursor: Coordinate = self.cursor
        row, col = cursor
        terrain = grid[row][col] if row < len(grid) and col < len(grid[row]) else "?"
        self.post_message(self.CoordinateSelected(self, MapSelection((row, col), terrain)))

    def _announce_selection(self) -> None:
        grid = self.grid_data
        if not grid:
            return
        cursor: Coordinate = self.cursor
        row, col = cursor
        if row >= len(grid) or col >= len(grid[row]):
            return
        terrain = grid[row][col]
        self.post_message(self.CoordinateSelected(self, MapSelection((row, col), terrain)))

    def render(self) -> RenderableType:
        highlight_map: dict[Coordinate, str] = dict(self._highlights)
        grid = self.grid_data
        if grid:
            cursor: Coordinate = self.cursor
            row, col = cursor
            if row < len(grid) and col < len(grid[row]):
                terrain = grid[row][col]
                symbol = self.terrain_symbols.get(str(terrain))
                if symbol is None:
                    symbol = str(terrain)[:2].title() if terrain else self.unknown_symbol
                highlight_map[(row, col)] = f"[reverse]{symbol}[/reverse]"
        return _render_hex_map(
            grid,
            self.terrain_symbols,
            self.unknown_symbol,
            self.title,
            highlight_map,
        )


__all__ = ["HexMapView", "Coordinate", "MapSelection"]
