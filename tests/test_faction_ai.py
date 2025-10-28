import random

from game.factions import Caravan, Faction, FactionDiplomacy
from game.factions.ai import FactionAIController
from game.world.sites import Site


def _make_site(identifier: str, controlling: str | None = None) -> Site:
    return Site(identifier=identifier, controlling_faction=controlling or None)


def test_faction_ai_plans_routes_with_networkx() -> None:
    traders = Faction(name="Traders")
    caravan = Caravan(identifier="caravan-1", faction_name="Traders", location="alpha")
    traders.register_caravan(caravan)

    diplomacy = FactionDiplomacy()
    ai = FactionAIController(
        [traders, Faction(name="Nomads")], diplomacy=diplomacy, rng=random.Random(0)
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

    assert caravan.location == "alpha"
    assert caravan.route == ["alpha", "beta", "gamma"]

    ai.run_turn(world_state=world_state, day=2)

    assert caravan.location == "beta"
    assert caravan.route == ["gamma"]
    assert caravan.days_until_move == 2
