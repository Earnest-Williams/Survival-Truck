from survival_truck.hexpath import Axial, Cube
from survival_truck.hexpath import hex_distance_axial, hex_distance_cube


def test_hex_distance_axial():
    a = Axial(0, 0)
    b = Axial(2, -1)
    assert hex_distance_axial(a, b) == 2


def test_hex_distance_cube():
    a = Cube(0, 0, 0)
    b = Cube(1, -2, 1)
    assert hex_distance_cube(a, b) == 2
