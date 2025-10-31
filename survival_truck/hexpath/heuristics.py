from __future__ import annotations

from .coords import Axial, Cube


def hex_distance_cube(a: Cube, b: Cube) -> int:
    return max(abs(a.x - b.x), abs(a.y - b.y), abs(a.z - b.z))


def hex_distance_axial(a: Axial, b: Axial) -> int:
    ax, ay, az = a.q, -a.q - a.r, a.r
    bx, by, bz = b.q, -b.q - b.r, b.r
    return max(abs(ax - bx), abs(ay - by), abs(az - bz))
