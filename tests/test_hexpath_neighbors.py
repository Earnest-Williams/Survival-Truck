from survival_truck.hexpath import Axial, Layout, Offset
from survival_truck.hexpath import neighbors_axial, neighbors_offset


def test_neighbors_axial_six():
    n = list(neighbors_axial(Axial(0, 0)))
    assert len(n) == 6
    assert Axial(1, 0) in n
    assert Axial(0, 1) in n


def test_neighbors_offset_parity_odd_r():
    o = Offset(2, 3, Layout.ODD_R)  # row 3 odd
    n = list(neighbors_offset(o))
    assert len(n) == 6
    o_even = Offset(2, 2, Layout.ODD_R)
    n_even = {(x.col, x.row) for x in neighbors_offset(o_even)}
    n_odd = {(x.col, x.row) for x in neighbors_offset(o)}
    assert n_even != n_odd


def test_neighbors_offset_even_q_canonical():
    base_even = Offset(4, 2, Layout.EVEN_Q)  # even column
    base_odd = Offset(5, 2, Layout.EVEN_Q)  # odd column

    even_expected = {
        (5, 2),
        (5, 1),
        (4, 1),
        (3, 1),
        (3, 2),
        (4, 3),
    }
    odd_expected = {
        (6, 3),
        (6, 2),
        (5, 1),
        (4, 2),
        (4, 3),
        (5, 3),
    }

    assert {(n.col, n.row) for n in neighbors_offset(base_even)} == even_expected
    assert {(n.col, n.row) for n in neighbors_offset(base_odd)} == odd_expected


def test_neighbors_offset_odd_q_canonical():
    base_even = Offset(4, 2, Layout.ODD_Q)  # even column
    base_odd = Offset(5, 2, Layout.ODD_Q)  # odd column

    even_expected = {
        (5, 3),
        (5, 2),
        (4, 1),
        (3, 2),
        (3, 3),
        (4, 3),
    }
    odd_expected = {
        (6, 2),
        (6, 1),
        (5, 1),
        (4, 1),
        (4, 2),
        (5, 3),
    }

    assert {(n.col, n.row) for n in neighbors_offset(base_even)} == even_expected
    assert {(n.col, n.row) for n in neighbors_offset(base_odd)} == odd_expected
