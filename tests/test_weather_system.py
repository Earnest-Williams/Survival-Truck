import sys
from pathlib import Path

import pytest
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.engine.turn_engine import (  # noqa: E402
    TurnEngine,
    compute_weight_power_factor,
)
from game.engine.world import TruckComponent  # noqa: E402
from game.events.event_queue import EventQueue  # noqa: E402
from game.time.season_tracker import SeasonTracker  # noqa: E402
from game.time.weather import WeatherCondition, WeatherSystem  # noqa: E402
from game.truck.inventory import Inventory, InventoryItem, ItemCategory  # noqa: E402
from game.truck.models import Dimensions, Truck  # noqa: E402


def test_weather_system_respects_season_tables():
    clear = WeatherCondition("clear")
    snow = WeatherCondition("snow", travel_cost_multiplier=1.4)
    system = WeatherSystem(
        seasonal_tables={
            "default": ((clear, 1.0),),
            "winter": ((snow, 1.0),),
        },
        starting_day=0,
        starting_season="winter",
    )

    assert system.current_condition.name == "snow"
    system.advance_day(season="winter")
    assert system.current_condition.name == "snow"
    system.advance_day(season="summer")
    assert system.current_condition.name == "clear"


def test_turn_engine_records_weather_and_modifiers():
    queue = EventQueue()
    tracker = SeasonTracker(days_per_season=1)
    clear = WeatherCondition("clear", travel_cost_multiplier=1.0, maintenance_cost_multiplier=1.0)
    storm = WeatherCondition("storm", travel_cost_multiplier=1.5, maintenance_cost_multiplier=1.2)
    weather_system = WeatherSystem(
        seasonal_tables={
            "default": ((clear, 1.0),),
            "spring": ((clear, 1.0),),
            "summer": ((storm, 1.0),),
        },
        starting_day=tracker.current_day,
        starting_season=tracker.current_season.name,
    )

    engine = TurnEngine(
        season_tracker=tracker,
        event_queue=queue,
        weather_system=weather_system,
    )

    world_state: dict[str, object] = {}
    context = engine.run_turn({}, world_state=world_state)

    assert context.day == 0
    assert context.weather.name == "clear"
    assert context.travel_modifier == pytest.approx(
        context.season.movement_cost_multiplier * clear.travel_cost_multiplier
    )
    assert context.maintenance_modifier == pytest.approx(
        context.season.resource_cost_multiplier * clear.maintenance_cost_multiplier
    )

    weather_entry = context.world_state["weather"]
    assert weather_entry["day"] == 0
    assert weather_entry["condition"] == "clear"
    assert weather_entry["travel_modifier"] == pytest.approx(clear.travel_cost_multiplier)
    assert weather_entry["maintenance_modifier"] == pytest.approx(clear.maintenance_cost_multiplier)
    assert context.world_state["weather_history"][0]["condition"] == "clear"

    assert engine.weather_system.current_day == 1
    assert engine.weather_system.current_condition.name == "storm"

    # Second turn should use the summer table (storm)
    context_next = engine.run_turn({}, world_state=world_state)
    assert context_next.day == 1
    assert context_next.weather.name == "storm"
    assert context_next.travel_modifier == pytest.approx(
        context_next.season.movement_cost_multiplier * storm.travel_cost_multiplier
    )
    assert context_next.maintenance_modifier == pytest.approx(
        context_next.season.resource_cost_multiplier * storm.maintenance_cost_multiplier
    )
    history_conditions = [
        entry["condition"] for entry in context_next.world_state["weather_history"]
    ]
    assert history_conditions == ["clear", "storm"]


def test_travel_phase_applies_weather_modifier():
    queue = EventQueue()
    tracker = SeasonTracker(days_per_season=10)
    windy = WeatherCondition("windy", travel_cost_multiplier=1.4, maintenance_cost_multiplier=1.0)
    weather_system = WeatherSystem(
        seasonal_tables={
            tracker.current_season.name: ((windy, 1.0),),
        },
        starting_day=tracker.current_day,
        starting_season=tracker.current_season.name,
    )

    engine = TurnEngine(
        season_tracker=tracker,
        event_queue=queue,
        weather_system=weather_system,
    )

    command = {"route": {"waypoints": ["A", "B"], "base_cost": 10}}
    world_state: dict[str, object] = {}
    context = engine.run_turn(command, world_state=world_state)

    travel_reports = cast(list[dict[str, Any]], world_state["travel_reports"])
    assert len(travel_reports) == 1
    entry = travel_reports[0]
    assert entry["day"] == context.day
    assert entry["base_cost"] == pytest.approx(10.0)
    assert entry["modifier"] == pytest.approx(context.travel_modifier)
    assert entry["load_factor"] == pytest.approx(context.travel_load_factor)
    assert entry["adjusted_cost"] == pytest.approx(context.travel_cost_for(10.0))
    assert world_state["last_travel_cost"] == entry


def test_travel_cost_reflects_weight_and_power():
    queue = EventQueue()
    tracker = SeasonTracker(days_per_season=10)
    calm = WeatherCondition("calm", travel_cost_multiplier=1.0, maintenance_cost_multiplier=1.0)
    weather_system = WeatherSystem(
        seasonal_tables={
            tracker.current_season.name: ((calm, 1.0),),
        },
        starting_day=tracker.current_day,
        starting_season=tracker.current_season.name,
    )

    engine = TurnEngine(
        season_tracker=tracker,
        event_queue=queue,
        weather_system=weather_system,
    )

    truck = Truck(
        name="Hauler",
        module_capacity=Dimensions(4, 2, 2),
        crew_capacity=4,
        base_power_output=18,
        base_power_draw=6,
        base_storage_capacity=120,
        base_weight_capacity=2800.0,
    )
    truck.inventory = Inventory(max_weight=truck.weight_capacity, max_volume=truck.storage_capacity)
    truck.inventory.add_item(
        InventoryItem(
            item_id="steel",
            name="Steel Plates",
            category=ItemCategory.MATERIALS,
            quantity=700.0,
            weight_per_unit=1.0,
            volume_per_unit=1.0,
        )
    )
    engine.world.add_singleton(TruckComponent(truck=truck))

    command = {"route": {"waypoints": ["A", "B"], "base_cost": 20}}
    world_state: dict[str, object] = {}
    context = engine.run_turn(command, world_state=world_state)

    expected_factor = compute_weight_power_factor(truck.stats)
    assert context.travel_load_factor == pytest.approx(expected_factor)

    expected_cost = 20.0 * context.travel_modifier * expected_factor
    travel_reports = cast(list[dict[str, Any]], world_state["travel_reports"])
    entry = travel_reports[0]
    assert entry["load_factor"] == pytest.approx(expected_factor)
    assert entry["adjusted_cost"] == pytest.approx(expected_cost)


def test_maintenance_modifier_increases_required_effort():
    queue = EventQueue()
    tracker = SeasonTracker(days_per_season=10)
    harsh = WeatherCondition(
        "acid_rain", travel_cost_multiplier=1.0, maintenance_cost_multiplier=1.5
    )
    weather_system = WeatherSystem(
        seasonal_tables={
            tracker.current_season.name: ((harsh, 1.0),),
        },
        starting_day=tracker.current_day,
        starting_season=tracker.current_season.name,
    )

    engine = TurnEngine(
        season_tracker=tracker,
        event_queue=queue,
        weather_system=weather_system,
    )

    truck = Truck(
        name="Test Truck",
        module_capacity=Dimensions(10, 10, 10),
        crew_capacity=5,
        base_power_output=0,
        base_maintenance_load=12,
    )
    engine.world.add_singleton(TruckComponent(truck=truck))

    command = {"maintenance_points": 12}
    world_state: dict[str, object] = {}
    context = engine.run_turn(command, world_state=world_state)

    reports = cast(list[Any] | None, world_state.get("maintenance_reports"))
    assert reports is not None
    report = reports[0]
    assert report.cost_multiplier == pytest.approx(context.maintenance_modifier)
    assert report.maintenance_applied == pytest.approx(12.0)
    assert report.maintenance_required == pytest.approx(12.0 * context.maintenance_modifier)
    assert report.shortfall == pytest.approx(
        report.maintenance_required - report.maintenance_applied
    )
