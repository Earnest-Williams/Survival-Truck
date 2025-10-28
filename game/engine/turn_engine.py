"""Turn engine coordinating the daily simulation phases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Literal, Mapping, Optional

from ..events.event_queue import EventQueue, QueuedEvent
from ..time.season_tracker import SeasonProfile, SeasonTracker
from ..truck import MaintenanceReport, Truck
from ..ui.channels import (
    NotificationChannel,
    NotificationRecord,
    TurnLogChannel,
)

from .resource_pipeline import ResourcePipeline

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
    log_channel: TurnLogChannel | None = None
    notification_channel: NotificationChannel | None = None
    scheduled_events: List[QueuedEvent] = field(default_factory=list)
    summary_lines: List[str] = field(default_factory=list)
    notifications: List[NotificationRecord] = field(default_factory=list)

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

    def log(self, message: str) -> None:
        self.summary_lines.append(str(message))

    def notify(
        self,
        message: str,
        *,
        category: str = "info",
        payload: Dict[str, Any] | None = None,
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


class TurnEngine:
    """Coordinates the core daily phases of the simulation."""

    PHASE_ORDER: List[PhaseName] = [
        "command",
        "travel",
        "site",
        "maintenance",
        "faction",
    ]

    def __init__(
        self,
        season_tracker: SeasonTracker,
        event_queue: EventQueue,
        *,
        resource_pipeline: Optional[ResourcePipeline] = None,
        log_channel: Optional[TurnLogChannel] = None,
        notification_channel: Optional[NotificationChannel] = None,
    ) -> None:
        self.season_tracker = season_tracker
        self.event_queue = event_queue
        self._resource_pipeline = resource_pipeline
        self._log_channel = log_channel
        self._notification_channel = notification_channel
        self._phase_handlers: Dict[PhaseName, List[PhaseHandler]] = {
            phase: [] for phase in self.PHASE_ORDER
        }
        # Ensure baseline simulation behaviours occur even if the caller does
        # not explicitly register handlers. Additional handlers can still be
        # appended by the embedding game code.
        self.register_handler("command", self._default_command_handler)
        self.register_handler("maintenance", self._default_maintenance_handler)
        self.register_handler("faction", self._default_faction_handler)
        if self._resource_pipeline is not None:
            self.register_handler("command", self._resource_command_handler)
            self.register_handler("site", self._resource_site_handler)

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
            log_channel=self._log_channel,
            notification_channel=self._notification_channel,
        )

        for phase in self.PHASE_ORDER:
            for handler in self._phase_handlers[phase]:
                handler(context)

        self.season_tracker.advance_day()
        self._record_turn(context)
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

    def _default_maintenance_handler(self, context: TurnContext) -> None:
        """Apply daily maintenance to the player's truck if present."""

        truck = context.world_state.get("truck")
        if not isinstance(truck, Truck):
            return

        maintenance_points = int(context.command.get("maintenance_points", 0) or 0)
        report: MaintenanceReport = truck.run_maintenance_cycle(maintenance_points)
        reports: List[MaintenanceReport] = context.world_state.setdefault(
            "maintenance_reports", []
        )
        reports.append(report)

    def _resource_command_handler(self, context: TurnContext) -> None:
        if self._resource_pipeline is None:
            return
        self._resource_pipeline.process_crew_actions(context)

    def _resource_site_handler(self, context: TurnContext) -> None:
        if self._resource_pipeline is None:
            return
        self._resource_pipeline.process_site_exploitation(context)

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
                    context.notify("Route updated", category="route", payload={"waypoints": waypoint_list})

        module_orders = command.get("module_orders") if isinstance(command, Mapping) else None
        if isinstance(module_orders, Iterable):
            formatted_orders: List[str] = []
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
            assignments: List[str] = []
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
        parts: List[str] = []
        if context.summary_lines:
            parts.extend(context.summary_lines)
        if context.events:
            parts.append(
                "Events: "
                + ", ".join(f"{event.event_type}" for event in context.events)
            )
        if context.scheduled_events:
            parts.append(f"Scheduled {len(context.scheduled_events)} future event(s)")
        return " | ".join(parts)

