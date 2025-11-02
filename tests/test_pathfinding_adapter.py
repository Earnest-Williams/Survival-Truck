import pytest

from survival_truck.pathfinding import Pathfinder, PathState, move_cost


def test_pathfinder_downgrades_after_signature_typeerrors():
    state = PathState()
    pf = Pathfinder(state)

    call_counter = {"count": 0}

    def bad_signature(*args, **kwargs):
        call_counter["count"] += 1
        raise TypeError("unexpected arguments")

    # Simulate external adapter being present but with incompatible signature.
    pf._use_external = True
    pf._external_find_path = bad_signature

    path_one = pf.path((0, 0), (1, 0), budget_key=0)

    assert path_one is not None
    # Both signature probes should have been attempted once.
    assert call_counter["count"] == 2
    assert pf._external_find_path is None
    assert pf._use_external is False

    # Subsequent calls should bypass the external adapter entirely.
    path_two = pf.path((0, 0), (1, 0), budget_key=1)
    assert path_two is not None
    assert call_counter["count"] == 2


def test_internal_astar_prefers_low_cost_long_paths():
    state = PathState()

    # Expensive direct column toward the goal.
    for r in (1, 2):
        state.base_cost[(0, r)] = 5.0

    # Meandering road with very low step cost to reach the same goal tile.
    walkway = []
    q, r = 0, 0
    for _ in range(10):
        q += 1
        walkway.append((q, r))
    for _ in range(2):
        r += 1
        walkway.append((q, r))
    for _ in range(10):
        q -= 1
        walkway.append((q, r))

    for node in walkway:
        state.road_bonus[node] = -0.99

    pf = Pathfinder(state)
    best_path = pf.path((0, 0), (0, 2), budget_key=state.version)
    assert best_path is not None

    tuned_state = PathState(
        blocked=set(state.blocked),
        base_cost=state.base_cost.copy(),
        slope_cost=state.slope_cost.copy(),
        hazard_cost=state.hazard_cost.copy(),
        noise_cost=state.noise_cost.copy(),
        road_bonus=state.road_bonus.copy(),
        truck_load_mult=state.truck_load_mult,
        weather_mult=state.weather_mult,
        min_step_cost=0.01,
        version=state.version,
    )

    tuned_pf = Pathfinder(tuned_state)
    tuned_path = tuned_pf.path((0, 0), (0, 2), budget_key=tuned_state.version)
    assert tuned_path is not None

    def path_cost(path, *, state):
        return sum(move_cost(a, b, state=state) for a, b in zip(path, path[1:]))

    assert path_cost(best_path, state=state) == pytest.approx(
        path_cost(tuned_path, state=tuned_state)
    )
