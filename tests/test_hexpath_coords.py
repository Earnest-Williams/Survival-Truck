from survival_truck.hexpath import Axial, Cube
from survival_truck.hexpath import axial_to_cube, cube_to_axial


def test_cube_invariant():
    c = Cube(1, -2, 1)
    assert c.x + c.y + c.z == 0


def test_axial_cube_roundtrip():
    a = Axial(3, -2)
    c = axial_to_cube(a)
    a2 = cube_to_axial(c)
    assert a == a2
