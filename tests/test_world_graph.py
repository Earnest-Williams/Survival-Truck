import math
from collections.abc import Mapping
from typing import cast

from game.world.graph import (
    allied_factions,
    build_diplomacy_graph,
    build_site_movement_graph,
    hostile_factions,
    path_travel_cost,
    relationship,
    shortest_path_between_sites,
)
from game.world.map import HexCoord


def test_site_movement_graph_uses_astar_shortest_path() -> None:
    site_positions = {
        "alpha": HexCoord(0, 0),
        "beta": HexCoord(1, 0),
        "gamma": HexCoord(2, 0),
    }
    terrain_costs = {
        HexCoord(0, 0): 1.0,
        HexCoord(1, 0): 3.0,
        HexCoord(2, 0): 2.0,
    }
    connections = {
        "alpha": ["beta"],
        "beta": ["alpha", "gamma"],
        "gamma": ["beta"],
    }

    graph = build_site_movement_graph(
        site_positions,
        terrain_costs=cast(Mapping[object, float], terrain_costs),
        connections=connections,
    )

    path = list(shortest_path_between_sites(graph, "alpha", "gamma"))
    assert path == ["alpha", "beta", "gamma"]
    assert math.isclose(path_travel_cost(graph, path), 4.5)


def test_diplomacy_graph_relationship_queries() -> None:
    standings = {
        ("Traders", "Nomads"): 25.0,
        ("Traders", "Raiders"): -35.0,
    }
    graph = build_diplomacy_graph(["Traders", "Nomads", "Raiders"], standings, neutral_value=0.0)

    assert allied_factions(graph, "Traders") == ["Nomads"]
    assert hostile_factions(graph, "Traders") == ["Raiders"]
    assert relationship(graph, "Nomads", "Raiders") == 0.0
    assert relationship(graph, "Traders", "Traders") == math.inf
