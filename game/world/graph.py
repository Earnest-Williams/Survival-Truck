"""Graph utilities for world navigation and diplomatic reasoning."""

from __future__ import annotations

from itertools import combinations
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Iterable,
    Mapping,
    MutableMapping,
    Sequence,
    TypeAlias,
    cast,
)

import networkx as nx

from .map import HexCoord

CostFunction = Callable[[HexCoord], float]

if TYPE_CHECKING:  # pragma: no cover - typing only
    import esper

    EsperWorld = esper.World
else:  # pragma: no cover - runtime fallback for typing only
    EsperWorld = Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    WorldGraph: TypeAlias = nx.Graph[str]
else:  # pragma: no cover - runtime alias without subscripting
    WorldGraph: TypeAlias = nx.Graph


def build_site_movement_graph(
    site_positions: Mapping[str, HexCoord],
    *,
    terrain_costs: Mapping[object, float] | CostFunction | None = None,
    connections: Mapping[str, Iterable[str]] | None = None,
    default_cost: float = 1.0,
) -> WorldGraph:
    """Return a weighted graph describing travel between known sites."""

    graph: WorldGraph = nx.Graph()
    for site_id, coord in site_positions.items():
        graph.add_node(site_id, coord=coord)

    if len(graph) < 2:
        return graph

    cost_fn = _resolve_cost_function(terrain_costs, default_cost)

    if connections is None:
        for (site_a, coord_a), (site_b, coord_b) in combinations(
            site_positions.items(), 2
        ):
            if coord_a.distance_to(coord_b) != 1:
                continue
            _add_edge_with_cost(graph, site_a, coord_a, site_b, coord_b, cost_fn)
        return graph

    for origin, neighbors in connections.items():
        if origin not in site_positions:
            continue
        coord_origin = site_positions[origin]
        for neighbor in neighbors:
            if neighbor not in site_positions:
                continue
            coord_neighbor = site_positions[neighbor]
            _add_edge_with_cost(
                graph, origin, coord_origin, neighbor, coord_neighbor, cost_fn
            )
    return graph


def shortest_path_between_sites(
    graph: WorldGraph, start: str, goal: str
) -> Sequence[str]:
    """Return the lowest-cost path between ``start`` and ``goal`` using A* search."""

    if start == goal:
        return [start]

    def heuristic(node_a: str, node_b: str) -> float:
        coord_a = graph.nodes[node_a].get("coord")
        coord_b = graph.nodes[node_b].get("coord")
        if isinstance(coord_a, HexCoord) and isinstance(coord_b, HexCoord):
            return coord_a.distance_to(coord_b)
        return 0.0

    return nx.astar_path(graph, start, goal, heuristic=heuristic, weight="weight")


def path_travel_cost(graph: WorldGraph, path: Sequence[str]) -> float:
    """Return the total travel cost for ``path`` within ``graph``."""

    if len(path) < 2:
        return 0.0
    total = 0.0
    for origin, destination in zip(path, path[1:]):
        data = graph.get_edge_data(origin, destination) or {}
        total += float(data.get("weight", 0.0))
    return total


def build_diplomacy_graph(
    factions: Iterable[str],
    standings: Mapping[tuple[str, str], float],
    *,
    neutral_value: float = 0.0,
) -> WorldGraph:
    """Construct an undirected graph capturing faction relationships."""

    graph: WorldGraph = nx.Graph(neutral_value=float(neutral_value))
    for faction in factions:
        graph.add_node(faction)
    for (faction_a, faction_b), value in standings.items():
        if faction_a == faction_b:
            continue
        graph.add_edge(faction_a, faction_b, weight=float(value))
    return graph


def relationship(
    graph: WorldGraph, faction_a: str, faction_b: str, *, default: float | None = None
) -> float:
    """Return the stored relationship between two factions."""

    if faction_a == faction_b:
        return float("inf")
    if default is None:
        default = float(graph.graph.get("neutral_value", 0.0))
    if graph.has_edge(faction_a, faction_b):
        return float(graph.edges[faction_a, faction_b].get("weight", default))
    return float(default)


def allied_factions(
    graph: WorldGraph, faction: str, threshold: float = 15.0
) -> list[str]:
    """Return factions considered allied to ``faction`` according to ``threshold``."""

    allies: list[str] = []
    if faction not in graph:
        return allies
    for node in graph.nodes:
        neighbor = cast(str, node)
        if neighbor == faction:
            continue
        if relationship(graph, faction, neighbor) >= threshold:
            allies.append(neighbor)
    return allies


def hostile_factions(
    graph: WorldGraph, faction: str, threshold: float = -15.0
) -> list[str]:
    """Return factions considered hostile to ``faction`` according to ``threshold``."""

    hostiles: list[str] = []
    if faction not in graph:
        return hostiles
    for node in graph.nodes:
        neighbor = cast(str, node)
        if neighbor == faction:
            continue
        if relationship(graph, faction, neighbor) <= threshold:
            hostiles.append(neighbor)
    return hostiles


def _add_edge_with_cost(
    graph: nx.Graph,
    site_a: str,
    coord_a: HexCoord,
    site_b: str,
    coord_b: HexCoord,
    cost_fn: CostFunction,
) -> None:
    path = _hex_line(coord_a, coord_b)
    if len(path) < 2:
        weight = 0.0
    else:
        weight = 0.0
        for origin, destination in zip(path, path[1:]):
            weight += (cost_fn(origin) + cost_fn(destination)) * 0.5
    if graph.has_edge(site_a, site_b):
        existing = graph.edges[site_a, site_b].get("weight", weight)
        if weight >= existing:
            return
    graph.add_edge(site_a, site_b, weight=weight, steps=max(1, len(path) - 1))


def _resolve_cost_function(
    terrain_costs: Mapping[object, float] | CostFunction | None, default_cost: float
) -> CostFunction:
    if callable(terrain_costs):
        return terrain_costs

    lookup: MutableMapping[HexCoord, float] = {}
    if isinstance(terrain_costs, Mapping):
        for key, value in terrain_costs.items():
            coord = _coerce_coord(key)
            if coord is None:
                continue
            lookup[coord] = float(value)

    def cost_fn(coord: HexCoord) -> float:
        return float(lookup.get(coord, default_cost))

    return cost_fn


def _coerce_coord(value: object) -> HexCoord | None:
    if isinstance(value, HexCoord):
        return value
    if isinstance(value, Sequence) and len(value) == 2:
        try:
            return HexCoord(int(value[0]), int(value[1]))
        except (TypeError, ValueError):
            return None
    if isinstance(value, str) and "," in value:
        left, right = value.split(",", 1)
        try:
            return HexCoord(int(left), int(right))
        except ValueError:
            return None
    return None


def _hex_line(start: HexCoord, end: HexCoord) -> list[HexCoord]:
    if start == end:
        return [start]
    distance = start.distance_to(end)
    results: list[HexCoord] = []
    cube_a = _to_cube(start)
    cube_b = _to_cube(end)
    for step in range(distance + 1):
        t = 0 if distance == 0 else step / distance
        cube = _cube_round(_cube_lerp(cube_a, cube_b, t))
        results.append(_from_cube(cube))
    return results


def _to_cube(coord: HexCoord) -> tuple[float, float, float]:
    x = coord.q
    z = coord.r
    y = -x - z
    return float(x), float(y), float(z)


def _from_cube(cube: tuple[float, float, float]) -> HexCoord:
    x, y, z = cube
    return HexCoord(int(x), int(z))


def _cube_lerp(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    t: float,
) -> tuple[float, float, float]:
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


def _cube_round(cube: tuple[float, float, float]) -> tuple[int, int, int]:
    x, y, z = cube
    rx = round(x)
    ry = round(y)
    rz = round(z)

    x_diff = abs(rx - x)
    y_diff = abs(ry - y)
    z_diff = abs(rz - z)

    if x_diff > y_diff and x_diff > z_diff:
        rx = -ry - rz
    elif y_diff > z_diff:
        ry = -rx - rz
    else:
        rz = -rx - ry
    return int(rx), int(ry), int(rz)


__all__ = [
    "allied_factions",
    "build_diplomacy_graph",
    "build_site_movement_graph",
    "hostile_factions",
    "path_travel_cost",
    "relationship",
    "shortest_path_between_sites",
]
