# Integrating hex A* into the Textual TUI

Adopt **Axial** coordinates globally.

```python
from survival_truck.hexpath import Axial, neighbors_axial_bounded, hex_distance_axial, astar

def compute_path(map_w: int, map_h: int, blocked: set[Axial], start: Axial, goal: Axial):
    def passable(a: Axial) -> bool: return a not in blocked
    def neighbors(a: Axial): return neighbors_axial_bounded(a, map_w, map_h)
    return astar(start, goal, neighbors, hex_distance_axial, passable=passable)
```

Render the returned `path` as highlights.
