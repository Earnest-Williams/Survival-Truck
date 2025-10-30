"""Turn engine coordinating the daily simulation phases."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, cast

from ..events.event_queue import EventQueue, QueuedEvent
from ..time.season_tracker import SeasonProfile, SeasonTracker
from ..time.weather import WeatherCondition, WeatherSystem
from ..ui.channels import (
    NotificationChannel,
    NotificationRecord,
    TurnLogChannel,
)
from .resource_pipeline import ResourcePipeline
from .world import (
    CrewAdvancementSystem,
    CrewComponent,
    DiplomacySystem,
    FactionAISystem,
    FactionControllerComponent,
    GameWorld,
    SitesComponent,
    TruckComponent,
    TruckMaintenanceSystem,
)

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from ..truck.models import TruckStats


def compute_weight_power_factor(truck_stats: TruckStats | None) -> float:
    """Return the travel modifier derived from truck weight and power."""

    if truck_stats is None:
        return 1.0

    cargo_weight = float(getattr(truck_stats, "cargo_weight", 0.0) or 0.0)
    weight_capacity = float(getattr(truck_stats, "weight_capacity", 0.0) or 0.0)
    if weight_capacity > 0.0:
        load_ratio = cargo_weight / weight_capacity
    elif cargo_weight > 0.0:
        load_ratio = cargo_weight / 1000.0
    else:
        load_ratio = 0.0
    load_ratio = max(0.0, load_ratio)
    weight_factor = 1.0 + min(load_ratio, 2.0)

    power_output = float(getattr(truck_stats, "power_output", 0.0) or 0.0)
    power_draw = float(getattr(truck_stats, "power_draw", 0.0) or 0.0)
    base_power = max(power_output, 1.0)
    net_power = power_output - power_draw
    power_ratio = net_power / base_power
    power_factor = max(0.5, 1.0 + power_ratio)

    factor = weight_factor / power_factor
    return max(0.25, min(factor, 4.0))


CommandPayload = dict[str, Any]
PhaseName = Literal["command", "travel", "site", "maintenance", "diplomacy", "faction"]
PhaseHandler = Callable[["TurnContext"], None]


@dataclass
class TurnContext:
    """Shared state passed to each phase handler."""

    day: int
    season: SeasonProfile
    weather: WeatherCondition
    command: CommandPayload
    events: list[QueuedEvent]
    world_state: dict[str, Any]
    world: GameWorld
    _schedule_callback: Callable[[int, str, dict[str, Any] | None], None]
    log_channel: TurnLogChannel | None = None
    notification_channel: NotificationChannel | None = None
    scheduled_events: list[QueuedEvent] = field(default_factory=list)
    summary_lines: list[str] = field(default_factory=list)
    notifications: list[NotificationRecord] = field(default_factory=list)

    def schedule_event_in(
        self,
        days_from_now: int,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Queue a new event relative to the current day."""

        if days_from_now < 0:
            raise ValueError("days_from_now must be non-negative")
        target_day = self.day + days_from_now
        payload = payload or {}
        self._schedule_callback(target_day, event_type, payload)
        self.scheduled_events.append(
            QueuedEvent(day=target_day, event_type=event_type, payload=payload)
        )

    def log(self, message: str) -> None:
        self.summary_lines.append(str(message))

    # ------------------------------------------------------------------
    @property
    def travel_modifier(self) -> float:
        """Combined travel modifier from seasonal and weather effects."""

        return self.season.movement_cost_multiplier * self.weather.travel_cost_multiplier

    @property
    def travel_load_factor(self) -> float:
        """Additional travel modifier derived from truck weight and power."""

        return compute_weight_power_factor(self._truck_stats())

    @property
    def maintenance_modifier(self) -> float:
        """Combined maintenance modifier from seasonal and weather effects."""

        return self.season.resource_cost_multiplier * self.weather.maintenance_cost_multiplier

    def travel_cost_for(self, base_cost: float) -> float:
        """Apply travel modifiers to ``base_cost``."""

        return base_cost * self.travel_modifier * self.travel_load_factor

    def maintenance_cost_for(self, base_cost: float) -> float:
        """Apply maintenance modifiers to ``base_cost``."""

        return base_cost * self.maintenance_modifier

    def notify(
        self,
        message: str,
        *,
        category: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> NotificationRecord:
        record = NotificationRecord(
            day=self.day,
            message=str(message),
            category=category,
            payload=dict(payload or {}),
        )
        self.notifications.append(record)
        if self.notification_channel is not None:
            self.notification_channel.push(record)
        return record

    # ------------------------------------------------------------------
    def _truck_stats(self) -> TruckStats | None:
        component = self.world.get_singleton(TruckComponent)
        truck_obj: Any | None = None
        if component is not None:
            truck_obj = getattr(component, "truck", None)
        if truck_obj is None:
            truck_obj = self.world_state.get("truck")
        stats = getattr(truck_obj, "stats", None)
        if stats is None:
            return None
        required = ("cargo_weight", "weight_capacity", "power_output", "power_draw")
        if all(hasattr(stats, attr) for attr in required):
            return cast("TruckStats", stats)
        return None


class TurnEngine:
    """Coordinates the core daily phases of the simulation."""

    PHASE_ORDER: list[PhaseName] = [
        "command",
        "travel",
        "site",
        "maintenance",
        "diplomacy",
        "faction",
    ]

    def __init__(
        self,
        season_tracker: SeasonTracker,
        event_queue: EventQueue,
        *,
        resource_pipeline: ResourcePipeline | None = None,
        weather_system: WeatherSystem | None = None,
        log_channel: TurnLogChannel | None = None,
        notification_channel: NotificationChannel | None = None,
        world: GameWorld | None = None,
    ) -> None:
        self.season_tracker = season_tracker
        self.event_queue = event_queue
        self._resource_pipeline = resource_pipeline
        self._log_channel = log_channel
        self._notification_channel = notification_channel
        self.world = world or GameWorld()
        season = self.season_tracker.current_season
        self.weather_system = weather_system or WeatherSystem(
            starting_day=self.season_tracker.current_day,
            starting_season=season.name,
        )
        self._phase_handlers: dict[PhaseName, list[PhaseHandler]] = {
            phase: [] for phase in self.PHASE_ORDER
        }
        # Ensure baseline simulation behaviours occur even if the caller does
        # not explicitly register handlers. Additional handlers can still be
        # appended by the embedding game code.
        self.register_handler("command", self._default_command_handler)
        self.register_handler("travel", self._default_travel_handler)
        self._register_default_systems()

    def register_handler(self, phase: PhaseName, handler: PhaseHandler) -> None:
        """Register a callback for a specific phase."""

        if phase not in self._phase_handlers:
            raise ValueError(f"Unknown phase '{phase}'")
        self._phase_handlers[phase].append(handler)

    def run_turn(
        self, command: CommandPayload, *, world_state: dict[str, Any] | None = None
    ) -> TurnContext:
        """Run all phases for a single day."""

        current_day = self.season_tracker.current_day
        season = self.season_tracker.current_season
        events_today = list(self.event_queue.pop_events_for_day(current_day))
        state = world_state if world_state is not None else {}
        self._sync_world_bindings(state)
        weather = self.weather_system.current_condition
        self._record_weather_state(state, weather, current_day)

        context = TurnContext(
            day=current_day,
            season=season,
            weather=weather,
            command=command,
            events=events_today,
            world_state=state,
            world=self.world,
            _schedule_callback=self.event_queue.schedule,
            log_channel=self._log_channel,
            notification_channel=self._notification_channel,
        )

        for phase in self.PHASE_ORDER:
            for handler in self._phase_handlers[phase]:
                handler(context)
            self.world.process_phase(phase, context)

        self.season_tracker.advance_day()
        next_season = self.season_tracker.current_season
        self.weather_system.advance_day(season=next_season.name)
        self._record_turn(context)
        return context

    def has_pending_events(self) -> bool:
        return self.event_queue.has_events()

    def _default_command_handler(self, context: TurnContext) -> None:
        command = context.command

        route = command.get("route") if isinstance(command, Mapping) else None
        if isinstance(route, Mapping):
            waypoints = route.get("waypoints")
            if isinstance(waypoints, Iterable):
                waypoint_list = [str(point) for point in waypoints]
                if waypoint_list:
                    context.world_state["planned_route"] = waypoint_list
                    context.log("Route updated: " + " -> ".join(waypoint_list))
                    context.notify(
                        "Route updated",
                        category="route",
                        payload={"waypoints": waypoint_list},
                    )

        module_orders = command.get("module_orders") if isinstance(command, Mapping) else None
        if isinstance(module_orders, Iterable):
            formatted_orders: list[str] = []
            for raw_order in module_orders:
                if not isinstance(raw_order, Mapping):
                    continue
                module_id = str(raw_order.get("module_id", "unknown"))
                action = str(raw_order.get("action", "inspect"))
                formatted_orders.append(f"{module_id}:{action}")
                context.notify(
                    f"Module order for {module_id}",
                    category="module",
                    payload={"action": action},
                )
            if formatted_orders:
                context.world_state.setdefault("module_orders", []).extend(formatted_orders)
                context.log("Module orders: " + ", ".join(formatted_orders))

        crew_actions = command.get("crew_actions") if isinstance(command, Mapping) else None
        if isinstance(crew_actions, Iterable):
            assignments: list[str] = []
            for raw_action in crew_actions:
                if not isinstance(raw_action, Mapping):
                    continue
                participants_raw = raw_action.get("participants")
                if isinstance(participants_raw, str):
                    participants = [participants_raw]
                elif isinstance(participants_raw, Iterable):
                    participants = [str(entry) for entry in participants_raw]
                else:
                    participants = []
                task = str(raw_action.get("task") or raw_action.get("action") or "duty")
                if participants:
                    assignments.append(f"{', '.join(participants)} → {task}")
                    context.notify(
                        f"Crew assigned to {task}",
                        category="crew",
                        payload={"participants": participants},
                    )
            if assignments:
                context.world_state.setdefault("crew_assignments", []).extend(assignments)
                context.log("Crew assignments: " + "; ".join(assignments))

    def _default_travel_handler(self, context: TurnContext) -> None:
        command = context.command
        route = command.get("route") if isinstance(command, Mapping) else None
        if not isinstance(route, Mapping):
            return

        raw_base_cost = (
            route.get("base_cost")
            or route.get("base_travel_cost")
            or route.get("travel_cost")
            or route.get("cost")
            or route.get("distance")
        )
        if not isinstance(raw_base_cost, (int, float, str)):
            return
        try:
            base_cost = float(raw_base_cost)
        except (TypeError, ValueError):
            return
        if base_cost < 0:
            return

        load_factor = context.travel_load_factor
        adjusted_cost = context.travel_cost_for(base_cost)
        record = {
            "day": context.day,
            "base_cost": base_cost,
            "modifier": context.travel_modifier,
            "load_factor": load_factor,
            "adjusted_cost": adjusted_cost,
        }
        travel_reports = context.world_state.setdefault("travel_reports", [])
        travel_reports.append(record)
        context.world_state["last_travel_cost"] = record
        context.log(
            "Travel cost adjusted to "
            f"{adjusted_cost:.2f} "
            f"(base {base_cost:.2f}, env {context.travel_modifier:.2f}, load {load_factor:.2f})"
        )

    def _record_turn(self, context: TurnContext) -> None:
        summary = self._build_summary(context)
        if self._log_channel is not None:
            self._log_channel.record_context(context, summary=summary)
        elif summary:
            context.log(summary)

        if self._notification_channel is not None:
            self._notification_channel.extend_from_events(context.day, context.events)
            if context.scheduled_events:
                self._notification_channel.extend_from_schedule(context.scheduled_events)

    def _build_summary(self, context: TurnContext) -> str:
        parts: list[str] = []
        if context.summary_lines:
            parts.extend(context.summary_lines)
        if context.events:
            parts.append("Events: " + ", ".join(f"{event.event_type}" for event in context.events))
        if context.scheduled_events:
            parts.append(f"Scheduled {len(context.scheduled_events)} future event(s)")
        return " | ".join(parts)

    # ------------------------------------------------------------------
    def _record_weather_state(
        self, world_state: dict[str, Any], weather: WeatherCondition, day: int
    ) -> None:
        record = {
            "day": day,
            "condition": weather.name,
            "travel_modifier": weather.travel_cost_multiplier,
            "maintenance_modifier": weather.maintenance_cost_multiplier,
        }
        world_state["weather"] = record
        history = world_state.get("weather_history")
        if not isinstance(history, list):
            history = []
        history.append(record.copy())
        world_state["weather_history"] = history[-30:]

    def _register_default_systems(self) -> None:
        if not self.world.has_system_type(CrewAdvancementSystem):
            self.world.register_system(
                "maintenance",
                CrewAdvancementSystem(),
                priority=50,
            )
        if not self.world.has_system_type(TruckMaintenanceSystem):
            self.world.register_system(
                "maintenance",
                TruckMaintenanceSystem(),
                priority=100,
            )
        if not self.world.has_system_type(DiplomacySystem):
            self.world.register_system(
                "diplomacy",
                DiplomacySystem(),
                priority=100,
            )
        if not self.world.has_system_type(FactionAISystem):
            self.world.register_system("faction", FactionAISystem(), priority=100)
        if self._resource_pipeline is not None:
            if not self.world.has_system_type(_CrewActionSystem):
                self.world.register_system(
                    "command",
                    _CrewActionSystem(self._resource_pipeline),
                    priority=150,
                )
            if not self.world.has_system_type(_SiteExploitationSystem):
                self.world.register_system(
                    "site",
                    _SiteExploitationSystem(self._resource_pipeline),
                    priority=100,
                )

    def _sync_world_bindings(self, world_state: dict[str, Any]) -> None:
        bindings: list[tuple[type, str, str]] = [
            (TruckComponent, "truck", "truck"),
            (CrewComponent, "crew", "crew"),
            (FactionControllerComponent, "faction_controller", "controller"),
            (SitesComponent, "sites", "sites"),
        ]
        for component_type, key, attr in bindings:
            component = self.world.get_singleton(component_type)
            if component is None:
                world_state.pop(key, None)
                continue
            world_state[key] = getattr(component, attr)


class _CrewActionSystem:
    """Wrapper system delegating crew resource actions to the pipeline."""

    def __init__(self, pipeline: ResourcePipeline) -> None:
        self._pipeline = pipeline

    def process(self, world: GameWorld, context: TurnContext) -> None:
        self._pipeline.process_crew_actions(context)


class _SiteExploitationSystem:
    """Wrapper system delegating site exploitation to the pipeline."""

    def __init__(self, pipeline: ResourcePipeline) -> None:
        self._pipeline = pipeline

    def process(self, world: GameWorld, context: TurnContext) -> None:
        self._pipeline.process_site_exploitation(context)
