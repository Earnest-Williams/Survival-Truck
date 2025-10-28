"""Turn engine coordinating the daily simulation phases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal

from ..events.event_queue import EventQueue, QueuedEvent
from ..time.season_tracker import SeasonProfile, SeasonTracker

CommandPayload = Dict[str, Any]
PhaseName = Literal["command", "travel", "site", "maintenance", "faction"]
PhaseHandler = Callable[["TurnContext"], None]


@dataclass
class TurnContext:
    """Shared state passed to each phase handler."""

    day: int
    season: SeasonProfile
    command: CommandPayload
    events: List[QueuedEvent]
    world_state: Dict[str, Any]
    _schedule_callback: Callable[[int, str, Dict[str, Any] | None], None]
    scheduled_events: List[QueuedEvent] = field(default_factory=list)

    def schedule_event_in(
        self,
        days_from_now: int,
        event_type: str,
        payload: Dict[str, Any] | None = None,
    ) -> None:
        """Queue a new event relative to the current day."""

        if days_from_now < 0:
            raise ValueError("days_from_now must be non-negative")
        target_day = self.day + days_from_now
        payload = payload or {}
        self._schedule_callback(target_day, event_type, payload)
        self.scheduled_events.append(QueuedEvent(day=target_day, event_type=event_type, payload=payload))


class TurnEngine:
    """Coordinates the core daily phases of the simulation."""

    PHASE_ORDER: List[PhaseName] = [
        "command",
        "travel",
        "site",
        "maintenance",
        "faction",
    ]

    def __init__(self, season_tracker: SeasonTracker, event_queue: EventQueue) -> None:
        self.season_tracker = season_tracker
        self.event_queue = event_queue
        self._phase_handlers: Dict[PhaseName, List[PhaseHandler]] = {
            phase: [] for phase in self.PHASE_ORDER
        }
        # Ensure NPC factions act even if the caller does not explicitly
        # register a handler. Additional handlers can still be appended by
        # the embedding game code.
        self.register_handler("faction", self._default_faction_handler)

    def register_handler(self, phase: PhaseName, handler: PhaseHandler) -> None:
        """Register a callback for a specific phase."""

        if phase not in self._phase_handlers:
            raise ValueError(f"Unknown phase '{phase}'")
        self._phase_handlers[phase].append(handler)

    def run_turn(self, command: CommandPayload, *, world_state: Dict[str, Any] | None = None) -> TurnContext:
        """Run all phases for a single day."""

        current_day = self.season_tracker.current_day
        season = self.season_tracker.current_season
        events_today = list(self.event_queue.pop_events_for_day(current_day))

        context = TurnContext(
            day=current_day,
            season=season,
            command=command,
            events=events_today,
            world_state=world_state or {},
            _schedule_callback=self.event_queue.schedule,
        )

        for phase in self.PHASE_ORDER:
            for handler in self._phase_handlers[phase]:
                handler(context)

        self.season_tracker.advance_day()
        return context

    def has_pending_events(self) -> bool:
        return self.event_queue.has_events()

    def _default_faction_handler(self, context: TurnContext) -> None:
        """Drive faction AI stored in the world state if present."""

        controller = context.world_state.get("faction_controller")
        if controller is None:
            return
        run_turn = getattr(controller, "run_turn", None)
        if callable(run_turn):
            run_turn(world_state=context.world_state, day=context.day)

