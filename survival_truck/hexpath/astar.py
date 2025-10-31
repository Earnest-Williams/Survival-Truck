from __future__ import annotations

import heapq
from typing import Any, Callable, Hashable, Iterable, Optional, Tuple


def astar(
    start: Hashable,
    goal: Hashable,
    neighbors: Callable[[Any], Iterable[Any]],
    heuristic: Callable[[Any, Any], float],
    *,
    cost: Callable[[Any, Any], float] = lambda a, b: 1.0,
    passable: Callable[[Any], bool] = lambda x: True,
) -> Tuple[Optional[list], float]:
    """Generic A* over arbitrary node types. Returns (path_list, total_cost) or (None, inf) if no path."""
    g = {start: 0.0}
    f = {start: heuristic(start, goal)}
    open_heap: list[tuple[float, int, Hashable]] = []
    push_id = 0
    heapq.heappush(open_heap, (f[start], push_id, start))
    in_open = {start}
    came_from: dict[Hashable, Hashable] = {}

    while open_heap:
        _, _, current = heapq.heappop(open_heap)
        in_open.discard(current)
        if current == goal:
            rev = [current]
            while current in came_from:
                current = came_from[current]
                rev.append(current)
            rev.reverse()
            return rev, g[rev[-1]]

        for nxt in neighbors(current):
            if not passable(nxt):
                continue
            tentative = g[current] + float(cost(current, nxt))
            if tentative < g.get(nxt, float("inf")):
                came_from[nxt] = current
                g[nxt] = tentative
                f[nxt] = tentative + float(heuristic(nxt, goal))
                if nxt not in in_open:
                    push_id += 1
                    heapq.heappush(open_heap, (f[nxt], push_id, nxt))
                    in_open.add(nxt)

    return None, float("inf")
