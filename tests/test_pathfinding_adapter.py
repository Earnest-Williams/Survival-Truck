from survival_truck.pathfinding import Pathfinder, PathState


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
