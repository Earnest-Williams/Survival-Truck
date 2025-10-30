"""
Hex-grid pathfinding adapter for Textual TUI.

Primary goals:
- Provide a clean adapter around `hexagonal_pathfinding_astar`.
- Keep a robust, admissible fallback A* when the library is missing.
- Centralize cost layers (terrain, slope, hazard, noise, roads) and global multipliers.
- Offer a cache invalidation mechanism via a version key when costs change.

Usage:
    state = PathState()
    # Optionally populate cost layers / blocked, then:
    pf = Pathfinder(state)
    path = pf.path((0, 0), (8, -3), budget_key=state.version)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple
from collections import defaultdict
import heapq

# --- Types --------------------------------------------------------------------

Hex = Tuple[int, int]  # axial (q, r)


# --- Hex math -----------------------------------------------------------------

AXIAL_DIRECTIONS: List[Hex] = [
    (+1, 0), (+1, -1), (0, -1),
    (-1, 0), (-1, +1), (0, +1),
]


def hex_add(a: Hex, b: Hex) -> Hex:
    return (a[0] + b[0], a[1] + b[1])


def hex_neighbors(h: Hex) -> List[Hex]:
    return [hex_add(h, d) for d in AXIAL_DIRECTIONS]


def axial_to_cube(q: int, r: int) -> Tuple[int, int, int]:
    # x = q, z = r, y = -x - z
    return q, -q - r, r


def cube_distance(a: Hex, b: Hex) -> int:
    aq, ar = a
    bq, br = b
    ax, ay, az = axial_to_cube(aq, ar)
    bx, by, bz = axial_to_cube(bq, br)
    return max(abs(ax - bx), abs(ay - by), abs(az - bz))


# --- Path state and cost model ------------------------------------------------

@dataclass
class PathState:
    """
    Holds all data needed to compute movement cost and constraints.

    All cost layers are additive (except the negative road "bonus").
    Global multipliers scale the final step cost.
    """
    blocked: Set[Hex] = field(default_factory=set)

    # Base cost and additive layers:
    base_cost: Dict[Hex, float] = field(default_factory=lambda: defaultdict(lambda: 1.0))
    slope_cost: Dict[Hex, float] = field(default_factory=lambda: defaultdict(float))
    hazard_cost: Dict[Hex, float] = field(default_factory=lambda: defaultdict(float))
    noise_cost: Dict[Hex, float] = field(default_factory=lambda: defaultdict(float))

    # Road "bonus": typically <= 0 to bias selection toward roads.
    road_bonus: Dict[Hex, float] = field(default_factory=lambda: defaultdict(float))

    # Global multipliers:
    truck_load_mult: float = 1.0
    weather_mult: float = 1.0

    # Heuristic scaling: min possible step cost in the current config.
    # Keep this <= true min edge cost to remain admissible.
    min_step_cost: float = 1.0

    # Increment this whenever any cost layer changes to invalidate cache.
    version: int = 0


def move_cost(a: Hex, b: Hex, *, state: PathState) -> float:
    """
    Compute final edge cost from a -> b using layered costs and multipliers.
    """
    c = state.base_cost[b]
    c += state.slope_cost[b]
    c += state.hazard_cost[b]
    c += state.noise_cost[b]
    c += state.road_bonus[b]  # this can be negative for roads

    # Apply global multipliers last
    c *= state.truck_load_mult
    c *= state.weather_mult

    # Guard against zero or negative costs
    if c < 0.01:
        c = 0.01
    return c


# --- Pathfinder ---------------------------------------------------------------

class Pathfinder:
    """
    Hex pathfinding facade.

    - Uses `hexagonal_pathfinding_astar` if present.
    - Falls back to an internal, admissible A* if not.
    - Caches results keyed on (start, goal, budget_key).
    """

    def __init__(self, state: PathState) -> None:
        self.state = state
        self._cache: Dict[Tuple[Hex, Hex, int], Optional[List[Hex]]] = {}

        # Try to import the external library once; keep callables if available.
        self._use_external = False
        self._external_find_path = None

        try:
            # Replace with the exact import / API once confirmed.
            # The library name below matches the user's request.
            import hexagonal_pathfinding_astar as _hpa  # type: ignore
            # Heuristic shape expected by the lib can vary. We will adapt below.
            self._external_find_path = getattr(_hpa, "find_path", None)
            self._use_external = callable(self._external_find_path)
        except Exception:
            self._use_external = False
            self._external_find_path = None

    # --------- Public API ---------

    def path(self, start: Hex, goal: Hex, *, budget_key: int) -> Optional[List[Hex]]:
        """
        Compute a path from start to goal. Returns list of axial hexes or None.
        Cached by (start, goal, budget_key).
        """
        key = (start, goal, budget_key)
        if key in self._cache:
            return self._cache[key]

        if self._use_external and self._external_find_path is not None:
            path = self._run_external_astar(start, goal)
        else:
            path = self._run_internal_astar(start, goal)

        self._cache[key] = path
        return path

    def invalidate(self) -> None:
        """
        Clear the internal path cache. Call after large updates.
        Prefer incrementing state.version and passing it as budget_key for fine-grained control.
        """
        self._cache.clear()

    # --------- Internal helpers ---------

    def is_blocked(self, h: Hex) -> bool:
        return h in self.state.blocked

    def neighbors(self, h: Hex) -> Iterable[Hex]:
        for n in hex_neighbors(h):
            if not self.is_blocked(n):
                yield n

    def heuristic(self, a: Hex, b: Hex) -> float:
        # Admissible if min_step_cost is <= true min edge cost
        return cube_distance(a, b) * self.state.min_step_cost

    def edge_cost(self, a: Hex, b: Hex) -> float:
        return move_cost(a, b, state=self.state)

    # --------- External adapter ----------------------------------------------

    def _run_external_astar(self, start: Hex, goal: Hex) -> Optional[List[Hex]]:
        """
        Adapter for `hexagonal_pathfinding_astar.find_path`.

        Replace this with the exact call signature once known.
        Common patterns:
          - find_path(start, goal, neighbors_fn, cost_fn, heuristic_fn)
          - find_path(graph_like_object, start, goal)
          - find_path(start, goal, *, get_neighbors=..., get_cost=..., heuristic=...)

        The code below tries the most flexible style first.
        """
        # Strategy 1: keyword callables
        try:
            path = self._external_find_path(  # type: ignore
                start,
                goal,
                get_neighbors=self.neighbors,
                get_cost=self.edge_cost,
                heuristic=self.heuristic,
            )
            return list(path) if path else None
        except TypeError:
            pass

        # Strategy 2: positional callables
        try:
            path = self._external_find_path(  # type: ignore
                start,
                goal,
                self.neighbors,
                self.edge_cost,
                self.heuristic,
            )
            return list(path) if path else None
        except TypeError:
            pass

        # Strategy 3: fall back to internal
        return self._run_internal_astar(start, goal)

    # --------- Internal A* ----------------------------------------------------

    def _run_internal_astar(self, start: Hex, goal: Hex) -> Optional[List[Hex]]:
        """
        Admissible A* on axial hex grid.
        """
        if self.is_blocked(start) or self.is_blocked(goal):
            return None

        g_cost = {start: 0.0}
        parent: Dict[Hex, Optional[Hex]] = {start: None}
        heap: List[Tuple[float, float, Hex]] = []
        h0 = self.heuristic(start, goal)
        heapq.heappush(heap, (h0, 0.0, start))

        # Optional search window to constrain explosion:
        # max_radius = cube_distance(start, goal) + 8

        while heap:
            f, g, current = heapq.heappop(heap)
            if current == goal:
                return self._reconstruct(parent, current)
            for n in self.neighbors(current):
                # If constraining by radius, uncomment:
                # if cube_distance(start, n) > max_radius: continue
                tentative = g + self.edge_cost(current, n)
                if tentative < g_cost.get(n, 1e18):
                    g_cost[n] = tentative
                    parent[n] = current
                    fn = tentative + self.heuristic(n, goal)
                    heapq.heappush(heap, (fn, tentative, n))

        return None

    @staticmethod
    def _reconstruct(parent: Dict[Hex, Optional[Hex]], goal: Hex) -> List[Hex]:
        out: List[Hex] = []
        node: Optional[Hex] = goal
        while node is not None:
            out.append(node)
            node = parent[node]
        out.reverse()
        return out
