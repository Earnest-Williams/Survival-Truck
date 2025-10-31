import pytest

from survival_truck.hexpath import Axial, Layout, Offset
from survival_truck.hexpath import neighbors_axial, neighbors_offset


def test_neighbors_axial_six():
    n = list(neighbors_axial(Axial(0, 0)))
    assert len(n) == 6
    assert Axial(1, 0) in n
    assert Axial(0, 1) in n


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (
            Offset(4, 4, Layout.EVEN_R),
            {
                (3, 4),
                (4, 3),
                (4, 5),
                (5, 3),
                (5, 4),
                (5, 5),
            },
        ),
        (
            Offset(4, 5, Layout.EVEN_R),
            {
                (3, 4),
                (3, 5),
                (3, 6),
                (4, 4),
                (4, 6),
                (5, 5),
            },
        ),
        (
            Offset(4, 4, Layout.ODD_R),
            {
                (3, 3),
                (3, 4),
                (3, 5),
                (4, 3),
                (4, 5),
                (5, 4),
            },
        ),
        (
            Offset(4, 5, Layout.ODD_R),
            {
                (3, 5),
                (4, 4),
                (4, 6),
                (5, 4),
                (5, 5),
                (5, 6),
            },
        ),
        (
            Offset(4, 4, Layout.EVEN_Q),
            {
                (3, 4),
                (3, 5),
                (4, 3),
                (4, 5),
                (5, 4),
                (5, 5),
            },
        ),
        (
            Offset(5, 4, Layout.EVEN_Q),
            {
                (4, 3),
                (4, 4),
                (5, 3),
                (5, 5),
                (6, 3),
                (6, 4),
            },
        ),
        (
            Offset(4, 4, Layout.ODD_Q),
            {
                (3, 3),
                (3, 4),
                (4, 3),
                (4, 5),
                (5, 3),
                (5, 4),
            },
        ),
        (
            Offset(5, 4, Layout.ODD_Q),
            {
                (4, 4),
                (4, 5),
                (5, 3),
                (5, 5),
                (6, 4),
                (6, 5),
            },
        ),
    ],
)
def test_neighbors_offset_exact_neighbor_sets(offset: Offset, expected: set[tuple[int, int]]):
    actual = {(n.col, n.row) for n in neighbors_offset(offset)}
    assert actual == expected
