from __future__ import annotations

from typing import Iterable

from .coords import Axial, Cube, Layout, Offset

_AXIAL_DIRS = (
    Axial(+1, 0),
    Axial(+1, -1),
    Axial(0, -1),
    Axial(-1, 0),
    Axial(-1, +1),
    Axial(0, +1),
)

_CUBE_DIRS = (
    (+1, -1, 0),
    (+1, 0, -1),
    (0, +1, -1),
    (-1, +1, 0),
    (-1, 0, +1),
    (0, -1, +1),
)


def neighbors_axial(a: Axial) -> Iterable[Axial]:
    for d in _AXIAL_DIRS:
        yield Axial(a.q + d.q, a.r + d.r)


def neighbors_cube(c: Cube) -> Iterable[Cube]:
    for dx, dy, dz in _CUBE_DIRS:
        yield Cube(c.x + dx, c.y + dy, c.z + dz)


def neighbors_offset(o: Offset) -> Iterable[Offset]:
    col, row, layout = o.col, o.row, o.layout

    if layout == Layout.EVEN_R:
        if (row & 1) == 0:
            deltas = [
                (+1, 0),
                (+1, -1),
                (0, -1),
                (-1, 0),
                (0, +1),
                (+1, +1),
            ]
        else:
            deltas = [
                (-1, -1),
                (-1, 0),
                (-1, +1),
                (0, -1),
                (0, +1),
                (+1, 0),
            ]
    elif layout == Layout.ODD_R:
        if (row & 1) == 1:
            deltas = [
                (+1, 0),
                (+1, -1),
                (0, -1),
                (-1, 0),
                (0, +1),
                (+1, +1),
            ]
        else:
            deltas = [
                (-1, -1),
                (-1, 0),
                (-1, +1),
                (0, -1),
                (0, +1),
                (+1, 0),
            ]
    elif layout == Layout.EVEN_Q:
        if (col & 1) == 0:
            deltas = [
                (-1, 0),
                (-1, +1),
                (0, -1),
                (0, +1),
                (+1, 0),
                (+1, +1),
            ]
        else:
            deltas = [
                (-1, -1),
                (-1, 0),
                (0, -1),
                (0, +1),
                (+1, -1),
                (+1, 0),
            ]
    elif layout == Layout.ODD_Q:
        if (col & 1) == 1:
            deltas = [
                (-1, 0),
                (-1, +1),
                (0, -1),
                (0, +1),
                (+1, 0),
                (+1, +1),
            ]
        else:
            deltas = [
                (-1, -1),
                (-1, 0),
                (0, -1),
                (0, +1),
                (+1, -1),
                (+1, 0),
            ]
    else:
        raise ValueError("Unknown layout")

    for dc, dr in deltas:
        yield Offset(col + dc, row + dr, layout)


def neighbors_axial_bounded(a: Axial, width: int, height: int) -> Iterable[Axial]:
    for n in neighbors_axial(a):
        if 0 <= n.q < width and 0 <= n.r < height:
            yield n


def neighbors_offset_bounded(o: Offset, width: int, height: int) -> Iterable[Offset]:
    for n in neighbors_offset(o):
        if 0 <= n.col < width and 0 <= n.row < height:
            yield n
