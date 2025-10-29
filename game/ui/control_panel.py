"""Interactive command helpers for planning a turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget


@dataclass
class ControlPanel:
    """Collects player intent for a single turn.

    The control panel can be used to stage commands before handing them to
    :meth:`game.engine.turn_engine.TurnEngine.run_turn`. The resulting payload
    adheres to the structures expected by the existing simulation code while
    exposing higher level conveniences for callers.
    """

    _route_waypoints: List[str] = field(default_factory=list)
    _module_orders: Dict[str, str] = field(default_factory=dict)
    _crew_assignments: Dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    def plan_route(self, waypoints: Iterable[str]) -> None:
        """Replace the current route with the provided waypoint sequence."""

        self._route_waypoints = [str(point) for point in waypoints]

    def append_waypoint(self, waypoint: str) -> None:
        self._route_waypoints.append(str(waypoint))

    def clear_route(self) -> None:
        self._route_waypoints.clear()

    @property
    def route_waypoints(self) -> List[str]:
        """Expose a copy of the currently staged route."""

        return list(self._route_waypoints)

    # ------------------------------------------------------------------
    def set_module_state(self, module_id: str, action: str) -> None:
        """Queue an action to apply to a specific module.

        Common actions include ``install``, ``remove``, ``activate`` or
        ``deactivate``. The control panel merely records intent; the actual
        resolution should occur in game systems responsible for module
        management.
        """

        self._module_orders[str(module_id)] = str(action)

    def clear_module_orders(self) -> None:
        self._module_orders.clear()

    # ------------------------------------------------------------------
    def assign_crew(self, member: str, task: str) -> None:
        """Record a lightweight crew assignment for the upcoming turn."""

        key = str(member)
        self._crew_assignments[key] = str(task)

    def clear_crew(self) -> None:
        self._crew_assignments.clear()

    # ------------------------------------------------------------------
    def build_command_payload(self) -> Dict[str, object]:
        """Return a dictionary that can be passed to the turn engine."""

        payload: Dict[str, object] = {}
        if self._route_waypoints:
            payload["route"] = {"waypoints": list(self._route_waypoints)}
        if self._module_orders:
            payload["module_orders"] = [
                {"module_id": module_id, "action": action}
                for module_id, action in self._module_orders.items()
            ]
        if self._crew_assignments:
            payload["crew_actions"] = [
                {
                    "action": task,
                    "task": task,
                    "participants": [member],
                }
                for member, task in self._crew_assignments.items()
            ]
        return payload

    def reset(self) -> None:
        self.clear_route()
        self.clear_module_orders()
        self.clear_crew()

    # ------------------------------------------------------------------
    def render(self, *, title: str | None = None):
        from rich.panel import Panel
        from rich.table import Table

        table = Table.grid(padding=(0, 1), expand=True)
        route = " -> ".join(self._route_waypoints) if self._route_waypoints else "(no route)"
        table.add_row("[bold]Route[/bold]", route)

        if self._module_orders:
            for module_id, action in self._module_orders.items():
                table.add_row("[bold]Module[/bold]", f"{module_id}: {action}")
        else:
            table.add_row("[bold]Module[/bold]", "(no changes)")

        if self._crew_assignments:
            for member, task in self._crew_assignments.items():
                table.add_row("[bold]Crew[/bold]", f"{member} → {task}")
        else:
            table.add_row("[bold]Crew[/bold]", "(no assignments)")

        return Panel(table, title=title or "Turn Controls", border_style="white")


class ControlPanelWidget(Widget):
    """Textual widget wrapper for the turn control panel."""

    BINDINGS = [
        Binding("x", "reset_plan", "Reset Plan", show=False),
    ]

    class PlanUpdated(Message):
        """Notify listeners that the staged plan changed."""

        def __init__(self, control: "ControlPanelWidget") -> None:
            # Textual Message.__init__ takes no sender argument now.
            # Keep a reference if handlers need the widget.
            self.control = control
            super().__init__()

    class PlanReset(Message):
        """Raised when the plan has been cleared via the widget."""

        def __init__(self, control: "ControlPanelWidget") -> None:
            self.control = control
            super().__init__()

    def __init__(self, panel: ControlPanel | None = None, *, title: str | None = None) -> None:
        super().__init__(id="controls")
        self.control_panel = panel or ControlPanel()
        self.title = title

    def render(self):  # type: ignore[override]
        return self.control_panel.render(title=self.title)

    def action_reset_plan(self) -> None:
        self.control_panel.reset()
        self.refresh()
        self.post_message(self.PlanReset(self))

    def refresh_from_panel(self) -> None:
        self.refresh()
        self.post_message(self.PlanUpdated(self))


__all__ = ["ControlPanel", "ControlPanelWidget"]
