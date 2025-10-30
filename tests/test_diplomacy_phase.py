"""Tests covering the dedicated diplomacy phase in the turn engine."""

from __future__ import annotations

from typing import Dict, List, Tuple

from game.engine.turn_engine import TurnEngine
from game.engine.world import FactionControllerComponent
from game.events.event_queue import EventQueue
from game.time.season_tracker import SeasonTracker
from game.time.weather import WeatherCondition, WeatherSystem


class _RecordingDiplomacy:
    def __init__(self, log: List[str]) -> None:
        self.log = log

    def decay(self) -> None:
        self.log.append("diplomacy")


class _RecordingController:
    def __init__(self, log: List[str]) -> None:
        self.log = log
        self.diplomacy = _RecordingDiplomacy(log)
        self.turn_calls: List[Tuple[int, Dict[str, object]]] = []

    def run_turn(self, *, world_state: Dict[str, object], day: int) -> None:
        self.log.append("faction")
        self.turn_calls.append((day, dict(world_state)))


def test_turn_engine_runs_diplomacy_phase_before_faction() -> None:
    queue = EventQueue()
    tracker = SeasonTracker(days_per_season=10)
    clear = WeatherCondition(
        "clear", travel_cost_multiplier=1.0, maintenance_cost_multiplier=1.0
    )
    weather_system = WeatherSystem(
        seasonal_tables={tracker.current_season.name: ((clear, 1.0),)},
        starting_day=tracker.current_day,
        starting_season=tracker.current_season.name,
    )

    engine = TurnEngine(
        season_tracker=tracker,
        event_queue=queue,
        weather_system=weather_system,
    )

    log: List[str] = []
    controller = _RecordingController(log)
    engine.world.add_singleton(FactionControllerComponent(controller=controller))

    world_state: Dict[str, object] = {}
    context = engine.run_turn({}, world_state=world_state)

    assert log == ["diplomacy", "faction"]
    assert controller.diplomacy.log is log
    assert controller.turn_calls == [(context.day, world_state)]
