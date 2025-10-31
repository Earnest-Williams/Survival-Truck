from __future__ import annotations

from .coords import Axial, Cube, Layout, Offset


def axial_to_cube(a: Axial) -> Cube:
    x = a.q
    z = a.r
    y = -x - z
    return Cube(x, y, z)


def cube_to_axial(c: Cube) -> Axial:
    return Axial(c.x, c.z)


def axial_to_offset(a: Axial, layout: Layout) -> Offset:
    q, r = a.q, a.r
    if layout == Layout.EVEN_R:
        col = q + (r + (r & 1)) // 2
        row = r
    elif layout == Layout.ODD_R:
        col = q + (r - (r & 1)) // 2
        row = r
    elif layout == Layout.EVEN_Q:
        col = q
        row = r + (q + (q & 1)) // 2
    elif layout == Layout.ODD_Q:
        col = q
        row = r + (q - (q & 1)) // 2
    else:
        raise ValueError("Unknown layout")
    return Offset(col, row, layout)


def offset_to_axial(o: Offset) -> Axial:
    col, row, layout = o.col, o.row, o.layout
    if layout == Layout.EVEN_R:
        q = col - (row + (row & 1)) // 2
        r = row
    elif layout == Layout.ODD_R:
        q = col - (row - (row & 1)) // 2
        r = row
    elif layout == Layout.EVEN_Q:
        q = col
        r = row - (col + (col & 1)) // 2
    elif layout == Layout.ODD_Q:
        q = col
        r = row - (col - (col & 1)) // 2
    else:
        raise ValueError("Unknown layout")
    return Axial(q, r)
