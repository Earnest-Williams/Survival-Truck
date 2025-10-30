from game.factions import FactionAIController, FactionDiplomacy
from game.world.rng import WorldRandomness
from game.world.sites import Site


def _make_site(identifier: str, controlling: str | None = None) -> Site:
    return Site(identifier=identifier, controlling_faction=controlling or None)


def test_faction_ai_plans_routes_with_networkx() -> None:
    factions = [
        {
            "name": "Traders",
            "caravans": {"caravan-1": {"identifier": "caravan-1", "location": "alpha"}},
        },
        {"name": "Nomads"},
    ]

    diplomacy = FactionDiplomacy()
    randomness = WorldRandomness(seed=0)
    ai = FactionAIController(
        factions,
        diplomacy=diplomacy,
        rng=randomness.generator("test-factions"),
    )

    sites = {
        "alpha": _make_site("alpha", "Traders"),
        "beta": _make_site("beta", "Nomads"),
        "gamma": _make_site("gamma", "Nomads"),
    }

    world_state = {
        "sites": sites,
        "site_positions": {
            "alpha": (0, 0),
            "beta": (1, 0),
            "gamma": (2, 0),
        },
        "site_connections": {
            "alpha": ["beta"],
            "beta": ["alpha", "gamma"],
            "gamma": ["beta"],
        },
        "terrain_costs": {
            (0, 0): 1.0,
            (1, 0): 2.0,
            (2, 0): 4.0,
        },
    }

    ai.run_turn(world_state=world_state, day=1)

    caravan = ai.factions["Traders"].caravans["caravan-1"]
    assert caravan.location == "alpha"
    assert caravan.route == ["alpha", "beta", "gamma"]

    ai.run_turn(world_state=world_state, day=2)

    caravan = ai.factions["Traders"].caravans["caravan-1"]
    assert caravan.location == "beta"
    assert caravan.route == ["gamma"]
    assert caravan.days_until_move == 2


def test_faction_ai_fsm_cycle_records_path() -> None:
    factions = [
        {
            "name": "Traders",
            "caravans": {"caravan-1": {"identifier": "caravan-1", "location": "alpha"}},
        }
    ]

    diplomacy = FactionDiplomacy()
    randomness = WorldRandomness(seed=0)
    ai = FactionAIController(
        factions, diplomacy=diplomacy, rng=randomness.generator("test-factions")
    )

    world_state = {"sites": {"alpha": _make_site("alpha", "Traders")}}

    ai.run_turn(world_state=world_state, day=1)

    assert ai.state == "patrol"
    assert ai.state_path == ("patrol", "trade", "raid", "alliance")

    # ensure the path resets each turn
    ai.run_turn(world_state=world_state, day=2)
    assert ai.state_path == ("patrol", "trade", "raid", "alliance")


def test_faction_ai_fsm_manual_transitions_progress_states() -> None:
    ai = FactionAIController([])

    assert ai.state == "patrol"

    ai.advance_patrol()
    assert ai.state == "trade"

    ai.process_trade()
    assert ai.state == "raid"

    ai.engage_raid()
    assert ai.state == "alliance"

    ai.refresh_alliance()
    assert ai.state == "patrol"
