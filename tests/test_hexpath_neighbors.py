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
