import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.engine.turn_engine import TurnEngine
from game.events.event_queue import EventQueue
from game.time.season_tracker import SeasonTracker
from game.time.weather import WeatherCondition, WeatherSystem


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
    history_conditions = [entry["condition"] for entry in context_next.world_state["weather_history"]]
    assert history_conditions == ["clear", "storm"]
