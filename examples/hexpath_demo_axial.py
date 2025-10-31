from survival_truck.hexpath import (
    Axial,
    astar,
    hex_distance_axial,
    neighbors_axial_bounded,
)

width, height = 10, 10
start = Axial(0, 0)
goal = Axial(5, 2)  # keep within demo bounds

blocked = {Axial(1, 0), Axial(2, 1), Axial(3, 1)}


def passable(a: Axial) -> bool:
    return a not in blocked


def neighbors(a: Axial):
    return neighbors_axial_bounded(a, width, height)


if __name__ == "__main__":
    path, total_cost = astar(start, goal, neighbors, hex_distance_axial, passable=passable)
    print("path:", path)
    print("cost:", total_cost)
