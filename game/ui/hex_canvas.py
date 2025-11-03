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
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from .config_store import CONFIG_PATH, HexLayoutConfig
from .hex_layout import FLAT, Layout, POINTY, cube_round


Point = Tuple[float, float]
Poly = List[Point]


def hex_polygon(layout: Layout, cx: float, cy: float) -> Poly:
    """Return the six vertices of a hex centred at ``(cx, cy)``."""

    orientation = layout.orientation
    points: Poly = []
    for index in range(6):
        angle = math.tau * (orientation.start_angle + index) / 6.0
        points.append(
            (
                cx + layout.size_x * math.cos(angle),
                cy - layout.size_y * math.sin(angle),
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
    """Hex grid drawn on a Rich canvas with hover and click support."""

    BINDINGS = [
        Binding("shift+up", "flatten_increase", "Flatten +"),
        Binding("shift+down", "flatten_decrease", "Flatten -"),
        Binding("shift+right", "height_increase", "H +"),
        Binding("shift+left", "height_decrease", "H -"),
        Binding("ctrl+shift+left", "origin_left", "OX -"),
        Binding("ctrl+shift+right", "origin_right", "OX +"),
        Binding("ctrl+shift+up", "origin_up", "OY -"),
        Binding("ctrl+shift+down", "origin_down", "OY +"),
        Binding("ctrl+o", "orientation_toggle", "Toggle orient"),
        Binding("ctrl+shift+o", "offset_cycle", "Cycle offset"),
        Binding("ctrl+s", "save_layout", "Save layout"),
        Binding("ctrl+r", "reload_layout", "Reload layout"),
        # New binding to reset the layout to defaults.
        Binding("ctrl+shift+r", "reset_layout", "Reset layout"),
    ]

    DEFAULT_CSS = """
    HexCanvas {
        background: #141414;
    }
    """

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
        self._hex_layout: Layout | None = None
        self.cfg: HexLayoutConfig | None = None
        self._initial_hex_height = float(radius) * 2.0
        self.cols = cols
        self.rows = rows
        self.tiles = dict(tiles or {})
        self.labels = dict(labels or {})
        self.highlights = {}

    OFFSET_SEQUENCE: tuple[str, ...] = ("odd-r", "even-r", "odd-q", "even-q")

    def on_mount(self) -> None:
        config_exists = CONFIG_PATH.exists()
        self.cfg = HexLayoutConfig.load()
        if not config_exists and self.cfg is not None:
            # The very first time we run the app the default layout size
            # should respect the requested radius.  Subsequent runs will
            # use the saved height from disk.
            self.cfg.hex_height = self._initial_hex_height
        self._rebuild_layout()
        self._rebuild_centres()
        self._emit_config_changed()

    def watch_cols(self, _value: int) -> None:
        self._rebuild_centres()
        self.refresh()

    def watch_rows(self, _value: int) -> None:
        self._rebuild_centres()
        self.refresh()

    # ------------------------------------------------------------------
    def _rebuild_centres(self) -> None:
        if self._hex_layout is None:
            self._rebuild_layout()
        self._centres.clear()
        for q in range(self.cols):
            for r in range(self.rows):
                self._centres[(q, r)] = self._centre_for(q, r)

    def _centre_for(self, q: int, r: int) -> tuple[float, float]:
        config = self._ensure_config()
        if self._hex_layout is None:
            self._rebuild_layout()

        layout = self._hex_layout
        offset_mode = config.offset_mode
        if config.orientation == "pointy":
            parity = (r & 1) if offset_mode in ("odd-r", "even-r") else 0
            if offset_mode == "even-r":
                parity ^= 1
            return layout.hex_to_pixel(q + 0.5 * parity, r)
        parity = (q & 1) if offset_mode in ("odd-q", "even-q") else 0
        if offset_mode == "even-q":
            parity ^= 1
        return layout.hex_to_pixel(q, r + 0.5 * parity)

    def _rebuild_layout(self) -> None:
        if self.cfg is None:
            self.cfg = HexLayoutConfig.load()

        height = float(self.cfg.hex_height)
        flatten = float(self.cfg.flatten)
        origin_x = float(self.cfg.origin_x)
        origin_y = float(self.cfg.origin_y)

        if self.cfg.orientation == "pointy":
            size_x = height / math.sqrt(3.0)
            size_y = (height / 2.0) * flatten
            orientation = POINTY
        else:
            size_x = height / 2.0
            size_y = (height / math.sqrt(3.0)) * flatten
            orientation = FLAT

        self._hex_layout = Layout(
            orientation=orientation,
            size_x=size_x,
            size_y=size_y,
            origin_x=origin_x,
            origin_y=origin_y,
        )

    # ------------------------------------------------------------------
    def render(self) -> RichCanvas:
        width, height = self.size
        canvas = RichCanvas(width, height)
        if self._hex_layout is None:
            self._rebuild_layout()
        layout = self._hex_layout
        assert layout is not None

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

            points = hex_polygon(layout, cx, cy)

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
    def _ensure_config(self) -> HexLayoutConfig:
        if self.cfg is None:
            self.cfg = HexLayoutConfig.load()
        return self.cfg

    def _emit_config_changed(self, *, saved: bool = False) -> None:
        cfg = self._ensure_config()
        message: Message
        if saved:
            message = self.LayoutConfigSaved(cfg)
        else:
            message = self.LayoutConfigChanged(cfg)
        self.post_message(message)

    # Configuration adjustment actions.  Each method updates the model,
    # rebuilds the layout, recomputes centres, refreshes the widget and
    # emits a change message.  They also mark the configuration as dirty so
    # the UI can display an unsaved indicator.

    def action_flatten_increase(self) -> None:
        cfg = self._ensure_config()
        # Increase flatten up to 1.10.  Higher values elongate the hex vertically,
        # which is seldom desirable.  Each keypress adds 0.01.
        cfg.flatten = min(1.10, round(cfg.flatten + 0.01, 3))
        cfg.dirty = True
        self._rebuild_layout()
        self._rebuild_centres()
        self.refresh()
        self._emit_config_changed()

    def action_flatten_decrease(self) -> None:
        cfg = self._ensure_config()
        # Decrease flatten down to 0.30.  Lower values further compress the
        # vertical dimension and may distort the hex.  Each keypress
        # subtracts 0.01.
        cfg.flatten = max(0.30, round(cfg.flatten - 0.01, 3))
        cfg.dirty = True
        self._rebuild_layout()
        self._rebuild_centres()
        self.refresh()
        self._emit_config_changed()

    def action_height_increase(self) -> None:
        cfg = self._ensure_config()
        cfg.hex_height = min(256.0, cfg.hex_height + 1.0)
        cfg.dirty = True
        self._rebuild_layout()
        self._rebuild_centres()
        self.refresh()
        self._emit_config_changed()

    def action_height_decrease(self) -> None:
        cfg = self._ensure_config()
        cfg.hex_height = max(8.0, cfg.hex_height - 1.0)
        cfg.dirty = True
        self._rebuild_layout()
        self._rebuild_centres()
        self.refresh()
        self._emit_config_changed()

    def action_origin_left(self) -> None:
        cfg = self._ensure_config()
        cfg.origin_x -= 4.0
        cfg.dirty = True
        self._rebuild_layout()
        self._rebuild_centres()
        self.refresh()
        self._emit_config_changed()

    def action_origin_right(self) -> None:
        cfg = self._ensure_config()
        cfg.origin_x += 4.0
        cfg.dirty = True
        self._rebuild_layout()
        self._rebuild_centres()
        self.refresh()
        self._emit_config_changed()

    def action_origin_up(self) -> None:
        cfg = self._ensure_config()
        cfg.origin_y -= 4.0
        cfg.dirty = True
        self._rebuild_layout()
        self._rebuild_centres()
        self.refresh()
        self._emit_config_changed()

    def action_origin_down(self) -> None:
        cfg = self._ensure_config()
        cfg.origin_y += 4.0
        cfg.dirty = True
        self._rebuild_layout()
        self._rebuild_centres()
        self.refresh()
        self._emit_config_changed()

    def action_orientation_toggle(self) -> None:
        cfg = self._ensure_config()
        cfg.orientation = "flat" if cfg.orientation == "pointy" else "pointy"
        cfg.dirty = True
        self._rebuild_layout()
        self._rebuild_centres()
        self.refresh()
        self._emit_config_changed()

    def action_offset_cycle(self) -> None:
        cfg = self._ensure_config()
        try:
            index = self.OFFSET_SEQUENCE.index(cfg.offset_mode)
        except ValueError:
            index = 0
        cfg.offset_mode = self.OFFSET_SEQUENCE[(index + 1) % len(self.OFFSET_SEQUENCE)]
        cfg.dirty = True
        self._rebuild_centres()
        self.refresh()
        self._emit_config_changed()

    def action_save_layout(self) -> None:
        """Persist the current layout configuration.

        Attempts to write the configuration to disk using the config store.  If
        the save operation is successful the ``dirty`` flag will be reset and
        a ``LayoutConfigSaved`` message will be posted.  If an exception is
        raised during the save attempt a ``LayoutConfigSaveFailed`` message
        will be posted carrying the original error.  Regardless of outcome the
        layout change will be emitted so the UI can update its indicators.
        """
        cfg = self._ensure_config()
        try:
            cfg.save()
            # Saving will clear the dirty flag.  Emit a saved message so the
            # dashboard knows to clear the unsaved indicator.
            self._emit_config_changed(saved=True)
        except Exception as error:
            # On failure, do not clear the dirty flag and notify observers.
            self.post_message(self.LayoutConfigSaveFailed(cfg, error))
            # Still emit change notification so the UI reflects the attempted save.
            self._emit_config_changed()

    def action_reload_layout(self) -> None:
        self.cfg = HexLayoutConfig.load()
        self._rebuild_layout()
        self._rebuild_centres()
        self.refresh()
        self._emit_config_changed()

    def action_reset_layout(self) -> None:
        """Reset the layout to its default values.

        This action discards any current settings and reinitialises the
        configuration with the class defaults.  The height is scaled to
        match the original radius passed to the constructor.  After
        resetting the configuration is marked dirty so the UI indicates
        that changes should be saved.
        """
        cfg = HexLayoutConfig()
        # Respect the initial radius (stored as diameter) for height
        cfg.hex_height = self._initial_hex_height
        cfg.dirty = True
        self.cfg = cfg
        self._rebuild_layout()
        self._rebuild_centres()
        self.refresh()
        self._emit_config_changed()

    # ------------------------------------------------------------------
    def hex_at_pixel(self, px: float, py: float) -> tuple[int, int]:
        config = self._ensure_config()
        if self._hex_layout is None:
            self._rebuild_layout()

        qf, rf, _ = self._hex_layout.pixel_to_hex_fractional(px, py)

        if config.orientation == "pointy":
            ri = round(rf)
            parity = (ri & 1) if config.offset_mode in ("odd-r", "even-r") else 0
            if config.offset_mode == "even-r":
                parity ^= 1
            qf -= 0.5 * parity
            qi, ri, _ = cube_round(qf, rf, -qf - rf)
            return qi, ri

        qi = round(qf)
        parity = (qi & 1) if config.offset_mode in ("odd-q", "even-q") else 0
        if config.offset_mode == "even-q":
            parity ^= 1
        rf -= 0.5 * parity
        qi, ri, _ = cube_round(qf, rf, -qf - rf)
        return qi, ri

    def _hit_test(self, px: float, py: float) -> tuple[int, int]:
        """Return the offset coordinates for a pixel position."""

        return self.hex_at_pixel(px, py)

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

    class LayoutConfigChanged(Message):
        """Raised when the hex layout configuration has been adjusted."""

        def __init__(self, config: HexLayoutConfig) -> None:
            super().__init__()
            self.config = config

    class LayoutConfigSaved(LayoutConfigChanged):
        """Raised when the hex layout configuration has been persisted."""

    class LayoutConfigSaveFailed(Message):
        """Raised when persisting the hex layout configuration fails.

        Attributes:
            config: The configuration that failed to save.
            error: The exception raised during persistence.
        """

        def __init__(self, config: HexLayoutConfig, error: Exception) -> None:
            super().__init__()
            self.config = config
            self.error = error
