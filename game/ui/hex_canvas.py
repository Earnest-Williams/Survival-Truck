from __future__ import annotations

import math
from typing import Dict, List, Tuple

from typing import TYPE_CHECKING

try:  # pragma: no cover - prefer Rich's Canvas when available
    from rich.canvas import Canvas as RichCanvas
except ModuleNotFoundError:  # pragma: no cover - fallback for newer Rich releases
    from dataclasses import dataclass

    from rich.console import Console, ConsoleOptions, RenderResult
    from rich.measure import Measurement
    from rich.style import Style
    from rich.text import Text

    @dataclass
    class _Cell:
        char: str
        style: Style | str | None

    class RichCanvas:
        """Minimal stand-in for :class:`rich.canvas.Canvas`.

        Newer versions of Rich no longer expose ``rich.canvas``.  Textual still
        expects a renderable canvas, so we emulate the parts of the original API
        that :class:`HexCanvas` relies on (setting cells, drawing lines, and
        rendering text).  The implementation stores a simple 2D grid of cells and
        renders them as ``Text`` lines for Rich.
        """

        def __init__(self, width: int, height: int) -> None:
            self.width = width
            self.height = height
            self._grid: list[list[_Cell]] = [
                [_Cell(" ", None) for _ in range(width)] for _ in range(height)
            ]

        @staticmethod
        def _normalise_style(style: Style | str | None) -> Style | str | None:
            if isinstance(style, str) and style and not style.startswith("on "):
                # The original canvas treated bare colours as edge fills; mimic
                # that behaviour with a background colour so the line remains
                # visible against the dark theme.
                return f"on {style}"
            return style

        def set(self, x: int, y: int, char: str, *, style: Style | str | None = None) -> None:
            if 0 <= x < self.width and 0 <= y < self.height:
                self._grid[y][x] = _Cell(char, style)

        def text(self, x: int, y: int, value: str, *, style: Style | str | None = None) -> None:
            for offset, char in enumerate(value):
                self.set(x + offset, y, char, style=style)

        def line(
            self,
            start: tuple[float, float],
            end: tuple[float, float],
            *,
            style: Style | str | None = None,
        ) -> None:
            style = self._normalise_style(style)
            x1, y1 = start
            x2, y2 = end
            x1 = int(round(x1))
            y1 = int(round(y1))
            x2 = int(round(x2))
            y2 = int(round(y2))

            dx = abs(x2 - x1)
            dy = abs(y2 - y1)
            sx = 1 if x1 < x2 else -1
            sy = 1 if y1 < y2 else -1
            err = dx - dy

            while True:
                self.set(x1, y1, " ", style=style)
                if x1 == x2 and y1 == y2:
                    break
                e2 = err * 2
                if e2 > -dy:
                    err -= dy
                    x1 += sx
                if e2 < dx:
                    err += dx
                    y1 += sy

        def __rich_console__(
            self, console: Console, options: ConsoleOptions
        ) -> RenderResult:  # pragma: no cover - exercised via Textual render
            for row in self._grid:
                text = Text()
                for cell in row:
                    style = cell.style
                    if isinstance(style, Style):
                        style_obj = style
                    elif style:
                        style_obj = console.get_style(style)
                    else:
                        style_obj = None
                    text.append(cell.char, style=style_obj)
                yield text

        def __rich_measure__(
            self, console: Console, options: ConsoleOptions
        ) -> Measurement:  # pragma: no cover - trivial
            return Measurement(self.width, self.width)


if TYPE_CHECKING:  # pragma: no cover - typing aid for mypy
    from rich.canvas import Canvas as RichCanvas
from textual import events
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from .hex_layout import Layout, POINTY, cube_round

# Tune this between ~0.82 and 0.95 until it looks right on your terminal.
VISUAL_FLATTEN = 0.88


Point = Tuple[float, float]
Poly = List[Point]


def hex_points_pointy_top(cx: float, cy: float, r: float, flatten: float) -> Poly:
    """Return the six vertices of a pointy-top hex centred at (cx, cy)."""

    angles = (0, 60, 120, 180, 240, 300)
    points: Poly = []
    for angle in angles:
        radians = math.radians(angle)
        points.append(
            (
                cx + r * math.sin(radians),
                cy - (r * math.cos(radians)) * flatten,
            )
        )
    return points


def point_in_convex_poly(x: float, y: float, poly: Poly) -> bool:
    """Return True if the point (x, y) lies within the convex polygon."""

    sign = 0
    total = len(poly)
    for index in range(total):
        x1, y1 = poly[index]
        x2, y2 = poly[(index + 1) % total]
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if cross == 0:
            continue
        if sign == 0:
            sign = 1 if cross > 0 else -1
        elif (cross > 0 and sign < 0) or (cross < 0 and sign > 0):
            return False
    return True


class HexCanvas(Widget):
    """Pointy-top hex grid drawn on a Rich canvas with hover and click."""

    DEFAULT_CSS = """
    HexCanvas {
        background: #141414;
    }
    """

    radius: int = reactive(10)
    cols: int = reactive(8)
    rows: int = reactive(6)
    visual_flatten: float = reactive(VISUAL_FLATTEN)

    fill_forest = "#1b2735"
    fill_scrub = "#17212c"
    fill_barren = "#2a1a1a"
    fill_highlight = "#25364a"
    fill_hover = "#33465e"
    edge = "#2d3b4d"
    edge_hover = "#88c0ff"
    label = "#dbe2ea"
    label_highlight = "#ffe082"

    tiles: Dict[Tuple[int, int], str]
    labels: Dict[Tuple[int, int], str]
    highlights: Dict[Tuple[int, int], str]

    hovered: tuple[int, int] | None = reactive(None)

    def __init__(
        self,
        *,
        cols: int = 8,
        rows: int = 6,
        radius: int = 10,
        tiles: Dict[Tuple[int, int], str] | None = None,
        labels: Dict[Tuple[int, int], str] | None = None,
        visual_flatten: float | None = None,
    ) -> None:
        super().__init__()
        self._centres: Dict[Tuple[int, int], Point] = {}
        # ``Widget`` already exposes a ``_layout`` property, so store the
        # hex-specific layout data under a unique attribute name to avoid
        # clashing with Textual internals.
        self._hex_layout: Layout | None = None
        self.cols = cols
        self.rows = rows
        self.radius = radius
        self.tiles = dict(tiles or {})
        self.labels = dict(labels or {})
        self.highlights = {}
        if visual_flatten is not None:
            self.visual_flatten = visual_flatten

    def on_mount(self) -> None:
        self._rebuild_centres()

    def watch_cols(self, _value: int) -> None:
        self._rebuild_centres()
        self.refresh()

    def watch_rows(self, _value: int) -> None:
        self._rebuild_centres()
        self.refresh()

    def watch_radius(self, _value: int) -> None:
        self._rebuild_centres()
        self.refresh()

    def watch_visual_flatten(self, _value: float) -> None:
        self._rebuild_centres()
        self.refresh()

    # ------------------------------------------------------------------
    def _rebuild_centres(self) -> None:
        self._hex_layout = self._make_layout()
        self._centres.clear()
        for q in range(self.cols):
            for r in range(self.rows):
                self._centres[(q, r)] = self._centre_for(q, r)

    def _centre_for(self, q: int, r: int) -> tuple[float, float]:
        if self._hex_layout is None:
            self._hex_layout = self._make_layout()

        axial_q = q - ((r - (r & 1)) // 2)
        x, y = self._hex_layout.hex_to_pixel(axial_q, r)
        return x, y

    def _make_layout(self) -> Layout:
        radius = float(self.radius)
        flatten = float(self.visual_flatten)
        size_x = radius
        size_y = radius * flatten
        origin_x = radius + 1.0
        origin_y = radius * flatten + 1.0
        return Layout(POINTY, size_x, size_y, origin_x, origin_y)

    # ------------------------------------------------------------------
    def render(self) -> RichCanvas:
        width, height = self.size
        canvas = RichCanvas(width, height)
        radius = float(self.radius)

        for (q, r), (cx, cy) in self._centres.items():
            tile_code = self.tiles.get((q, r), "Sc")
            base_fill = {
                "Fo": self.fill_forest,
                "Sc": self.fill_scrub,
                "Ba": self.fill_barren,
            }.get(tile_code, self.fill_scrub)

            highlight_label = self.highlights.get((q, r))
            is_hovered = self.hovered == (q, r)

            fill_colour = (
                self.fill_hover
                if is_hovered
                else self.fill_highlight
                if highlight_label is not None
                else base_fill
            )
            edge_colour = self.edge_hover if (is_hovered or highlight_label is not None) else self.edge

            points = hex_points_pointy_top(cx, cy, radius, self.visual_flatten)

            min_x = int(max(0, math.floor(min(point[0] for point in points))))
            max_x = int(min(width - 1, math.ceil(max(point[0] for point in points))))
            min_y = int(max(0, math.floor(min(point[1] for point in points))))
            max_y = int(min(height - 1, math.ceil(max(point[1] for point in points))))
            background_style = f"on {fill_colour}"
            for y in range(min_y, max_y + 1):
                for x in range(min_x, max_x + 1):
                    if point_in_convex_poly(x + 0.5, y + 0.5, points):
                        canvas.set(x, y, " ", style=background_style)

            for index in range(6):
                x1, y1 = points[index]
                x2, y2 = points[(index + 1) % 6]
                canvas.line((x1, y1), (x2, y2), style=edge_colour)

            label = self.labels.get((q, r))
            if highlight_label is not None:
                label = highlight_label
                label_style = self.label_highlight
            else:
                label_style = self.label
            if label is None:
                label = f"{q},{r}"
            canvas.text(int(cx - len(label) / 2), int(cy), label, style=label_style)

        return canvas

    # ------------------------------------------------------------------
    def set_tiles(self, tiles: Dict[Tuple[int, int], str]) -> None:
        self.tiles = {(int(q), int(r)): str(code) for (q, r), code in tiles.items()}
        self.refresh()

    def set_labels(self, labels: Dict[Tuple[int, int], str]) -> None:
        self.labels = {(int(q), int(r)): str(text) for (q, r), text in labels.items()}
        self.refresh()

    def set_highlights(self, highlights: Dict[Tuple[int, int], str]) -> None:
        self.highlights = {(int(q), int(r)): str(text) for (q, r), text in highlights.items()}
        self.refresh()

    # ------------------------------------------------------------------
    def _hit_test(self, px: float, py: float) -> tuple[int, int]:
        """Return the odd-r offset coordinates for a pixel position."""

        if self._hex_layout is None:
            self._hex_layout = self._make_layout()

        qf, rf, sf = self._hex_layout.pixel_to_hex_fractional(px, py)

        # ``rf`` corresponds to the axial ``r`` value.  Use it to derive the row
        # parity so we can undo the 0.5 column shift applied for odd rows when
        # converting to pixel space.
        _, ri, _ = cube_round(qf, rf, sf)
        parity = ri & 1

        corrected_qf = qf - 0.5 * parity
        qi, ri, _ = cube_round(corrected_qf, rf, -corrected_qf - rf)
        return qi, ri

    def _hit(self, x: int, y: int) -> tuple[int, int] | None:
        px, py = float(x) + 0.5, float(y) + 0.5
        q, r = self._hit_test(px, py)
        key = (q, r)
        return key if key in self._centres else None

    async def on_mouse_move(self, event: events.MouseMove) -> None:
        new_hover = self._hit(event.x, event.y)
        if new_hover != self.hovered:
            self.hovered = new_hover
            self.refresh()

    async def on_click(self, event: events.Click) -> None:
        hit = self._hit(event.x, event.y)
        if hit is not None:
            q, r = hit
            self.post_message(self.HexClicked(q, r))

    class HexClicked(Message):
        """Message emitted when a hex cell is clicked."""

        def __init__(self, q: int, r: int) -> None:
            super().__init__()
            self.q = q
            self.r = r
