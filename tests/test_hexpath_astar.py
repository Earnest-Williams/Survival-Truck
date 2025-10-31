from survival_truck.hexpath import Axial
from survival_truck.hexpath import astar, hex_distance_axial, neighbors_axial


def test_astar_straight_line():
    start = Axial(0, 0)
    goal = Axial(3, 0)
    path, cost = astar(start, goal, neighbors_axial, hex_distance_axial)
    assert path is not None
    assert path[0] == start and path[-1] == goal
    assert cost == 3


def test_astar_blocked_detour():
    start = Axial(0, 0)
    goal = Axial(2, 0)
    blocked = {Axial(1, 0)}

    def passable(a: Axial) -> bool:
        return a not in blocked

    path, cost = astar(start, goal, neighbors_axial, hex_distance_axial, passable=passable)
    assert path is not None
    assert path[0] == start and path[-1] == goal
    assert cost > 2
