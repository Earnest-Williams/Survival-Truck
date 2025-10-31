import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from survival_truck.widgets.hex_canvas import HexCanvas, Viewport
from survival_truck.pathfinding import PathState


class DummyPathfinder:
    def __init__(self):
        self.calls = []

    def path(self, start, goal, budget_key):
        self.calls.append((start, goal, budget_key))
        if start == goal:
            return [start]
        return [start, goal]

    def edge_cost(self, a, b):
        return 1.0


def make_canvas():
    state = PathState()
    canvas = HexCanvas(DummyPathfinder(), state, origin=(0, 0))
    canvas.viewport = Viewport(center=(0, 0), radius_q=2, radius_r=2)
    return canvas


def test_screen_to_axial_even_row_alignment():
    canvas = make_canvas()
    q, r = canvas._approx_screen_to_axial(0, 0)
    assert (q, r) == (-2, -2)


def test_screen_to_axial_odd_row_leading_cell_maps_correctly():
    canvas = make_canvas()
    q, r = canvas._approx_screen_to_axial(1, 1)
    assert (q, r) == (-2, -1)


def test_screen_to_axial_odd_row_second_cell_maps_correctly():
    canvas = make_canvas()
    q, r = canvas._approx_screen_to_axial(3, 1)
    assert (q, r) == (-1, -1)


def test_preview_updates_when_state_version_changes():
    state = PathState()
    pf = DummyPathfinder()
    canvas = HexCanvas(pf, state, origin=(0, 0))

    assert pf.calls[-1][2] == state.version

    state.version = 5
    canvas._update_preview()
    assert pf.calls[-1][2] == state.version


def test_set_budget_key_overrides_preview_budget():
    state = PathState()
    pf = DummyPathfinder()
    canvas = HexCanvas(pf, state, origin=(0, 0))

    canvas.set_budget_key(42)
    assert pf.calls[-1][2] == 42

    canvas.set_budget_key(None)
    state.version = 9
    canvas._update_preview()
    assert pf.calls[-1][2] == state.version
