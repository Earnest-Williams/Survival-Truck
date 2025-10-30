"""Textual widget for previewing hex-grid paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from textual import events
from textual.message import Message
from textual.widget import Widget

from survival_truck.pathfinding import Hex, Pathfinder, PathState


class PathCommitted(Message):
    """Message emitted when the user confirms the current preview path."""

    def __init__(self, path: List[Hex], total_cost: float) -> None:
        self.path = path
        self.total_cost = total_cost
        super().__init__()


@dataclass
class Viewport:
    """Logical viewport describing the rendered axial window."""

    center: Hex = (0, 0)
    radius_q: int = 12
    radius_r: int = 8


class HexCanvas(Widget):
    """Minimal ASCII renderer for a hex grid with live path previews."""

    DEFAULT_CSS = """
    HexCanvas {
        height: 100%;
        width: 100%;
        content-align: left middle;
    }
    """

    def __init__(self, pf: Pathfinder, state: PathState, *, origin: Hex = (0, 0)) -> None:
        super().__init__()
        self.pf = pf
        self.state = state
        self.origin: Hex = origin
        self.cursor: Hex = origin
        self.preview_path: Optional[List[Hex]] = None
        self.viewport = Viewport(center=origin)
        self.budget_key: int = state.version
        self._update_preview()

    # ---------------------------------------------------------------------
    # Interaction

    async def on_key(self, event: events.Key) -> None:  # pragma: no cover - UI glue
        moved = False
        q, r = self.cursor

        if event.key in ("right", "l"):
            self.cursor = (q + 1, r)
            moved = True
        elif event.key in ("up", "k"):
            self.cursor = (q, r - 1)
            moved = True
        elif event.key in ("left", "h"):
            self.cursor = (q - 1, r)
            moved = True
        elif event.key in ("down", "j"):
            self.cursor = (q, r + 1)
            moved = True
        elif event.key == "u":
            self.cursor = (q + 1, r - 1)
            moved = True
        elif event.key == "b":
            self.cursor = (q - 1, r + 1)
            moved = True

        if event.key in ("enter", "return"):
            await self._commit_if_possible()
            return

        if moved:
            self._update_preview()
            self._recenter_if_needed()
            self.refresh()

    async def on_mouse_move(self, event: events.MouseMove) -> None:  # pragma: no cover - UI glue
        x, y = event.x, event.y
        cq, cr = self._approx_screen_to_axial(x, y)
        if (cq, cr) != self.cursor:
            self.cursor = (cq, cr)
            self._update_preview()
            self._recenter_if_needed()
            self.refresh()

    async def on_click(self, event: events.Click) -> None:  # pragma: no cover - UI glue
        await self._commit_if_possible()

    async def _commit_if_possible(self) -> None:  # pragma: no cover - UI glue
        if not self.preview_path:
            return

        total = 0.0
        for a, b in zip(self.preview_path, self.preview_path[1:]):
            total += self.pf.edge_cost(a, b)
        await self.post_message(PathCommitted(self.preview_path, total))

    # ---------------------------------------------------------------------
    # Preview helpers

    def _update_preview(self) -> None:
        self.preview_path = self.pf.path(self.origin, self.cursor, budget_key=self.budget_key)

    def _recenter_if_needed(self) -> None:
        cq, cr = self.cursor
        oq, or_ = self.viewport.center
        if abs(cq - oq) > self.viewport.radius_q - 2 or abs(cr - or_) > self.viewport.radius_r - 2:
            self.viewport.center = (cq, cr)

    # ---------------------------------------------------------------------
    # Rendering

    def render(self) -> str:
        v = self.viewport
        oq, or_ = v.center
        q_min, q_max = oq - v.radius_q, oq + v.radius_q
        r_min, r_max = or_ - v.radius_r, or_ + v.radius_r

        path_set = set(self.preview_path or [])
        rows: List[str] = []
        for r in range(r_min, r_max + 1):
            offset = " " if ((r - r_min) % 2) else ""
            line_chars: List[str] = []
            for q in range(q_min, q_max + 1):
                p = (q, r)
                ch = "."
                if p in self.state.blocked:
                    ch = "#"
                elif self.state.road_bonus.get(p, 0.0) < 0.0:
                    ch = "o"
                if p in path_set:
                    ch = "*"
                if p == self.origin:
                    ch = "@"
                if p == self.cursor:
                    ch = "+"
                line_chars.append(ch)
            rows.append(offset + " ".join(line_chars))

        return "\n".join(rows)

    # ---------------------------------------------------------------------
    # Screen-to-axial approximation

    def _approx_screen_to_axial(self, x: int, y: int) -> Hex:
        v = self.viewport
        oq, or_ = v.center
        q_min = oq - v.radius_q
        r_min = or_ - v.radius_r

        col = max(0, x // 2)
        row = max(0, y)
        r = r_min + row
        stagger = ((r - r_min) % 2) == 1
        q = q_min + col - (1 if stagger else 0)
        return (q, r)
