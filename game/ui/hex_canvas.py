from __future__ import annotations

import math
from typing import Dict, List, Tuple

from rich.canvas import Canvas as RichCanvas
from textual import events
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

Point = Tuple[float, float]
Poly = List[Point]


def hex_points_pointy_top(cx: float, cy: float, r: float) -> Poly:
    """Return the six vertices of a pointy-top hex centred at (cx, cy)."""

    angles = (0, 60, 120, 180, 240, 300)
    points: Poly = []
    for angle in angles:
        radians = math.radians(angle)
        points.append((cx + r * math.sin(radians), cy - r * math.cos(radians)))
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
    ) -> None:
        super().__init__()
        self._centres: Dict[Tuple[int, int], Point] = {}
        self.cols = cols
        self.rows = rows
        self.radius = radius
        self.tiles = dict(tiles or {})
        self.labels = dict(labels or {})
        self.highlights = {}

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

    # ------------------------------------------------------------------
    def _rebuild_centres(self) -> None:
        self._centres.clear()
        for q in range(self.cols):
            for r in range(self.rows):
                self._centres[(q, r)] = self._centre_for(q, r)

    def _centre_for(self, q: int, r: int) -> Point:
        size = float(self.radius)
        x_pos = q * (size * 1.5) + size + 1.0
        y_pos = (r + 0.5 * (q & 1)) * (size * math.sqrt(3)) + size + 1.0
        return (x_pos, y_pos)

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

            points = hex_points_pointy_top(cx, cy, radius)

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
    def _hit(self, x: int, y: int) -> tuple[int, int] | None:
        px, py = float(x), float(y)
        for key, (cx, cy) in self._centres.items():
            points = hex_points_pointy_top(cx, cy, float(self.radius))
            if point_in_convex_poly(px + 0.5, py + 0.5, points):
                return key
        return None

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
