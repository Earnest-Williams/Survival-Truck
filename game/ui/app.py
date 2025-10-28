"""Textual application wiring together the Survival Truck dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, MutableMapping, Sequence

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Footer, Header

from ..crew import Crew
from ..engine.turn_engine import TurnContext, TurnEngine
from ..engine.resource_pipeline import ResourcePipeline
from ..engine.world import (
    CrewComponent,
    FactionControllerComponent,
    GameWorld,
    SitesComponent,
    TruckComponent,
)
from ..events.event_queue import EventQueue
from ..factions import FactionAIController
from ..time.season_tracker import SeasonTracker
from ..truck import Dimensions, Truck, TruckModule
from ..truck.inventory import Inventory, InventoryItem, ItemCategory
from ..world.map import BiomeNoise, HexCoord
from ..world.rng import WorldRandomness
from ..world.sites import Site
from .channels import NotificationChannel, TurnLogChannel
from .control_panel import ControlPanel, ControlPanelWidget
from .dashboard import DashboardView, TurnLogWidget
from .hex_map import HexMapView
from .truck_layout import TruckLayoutView

@dataclass
class AppConfig:
    """Configuration payload for the UI bootstrap."""

    map_data: Sequence[Sequence[str]]
    world_state: MutableMapping[str, object]
    world_seed: int = 42


class SurvivalTruckApp(App):
    """Interactive Textual application for Survival Truck."""

    CSS = """
    Screen {
        layout: grid;
        grid-rows: auto 1fr auto;
    }

    #body {
        grid-row: 2;
        layout: grid;
        grid-columns: 3fr 2fr;
        grid-rows: min-content min-content min-content 1fr;
        grid-gutter: 1;
        height: 1fr;
    }

    HexMapView {
        grid-column: 1;
        grid-row: 1 / span 3;
        height: 1fr;
    }

    #status {
        grid-column: 2;
        grid-row: 1;
    }

    #truck {
        grid-column: 2;
        grid-row: 2;
    }

    #controls {
        grid-column: 2;
        grid-row: 3;
    }

    TurnLogWidget {
        grid-column: 1 / span 2;
        grid-row: 4;
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("space", "next_turn", "Next Day"),
        Binding("r", "reset_route", "Clear Route"),
    ]

    def __init__(
        self,
        *,
        config: AppConfig | None = None,
        control_panel: ControlPanel | None = None,
        turn_engine: TurnEngine | None = None,
        log_channel: TurnLogChannel | None = None,
        notification_channel: NotificationChannel | None = None,
    ) -> None:
        super().__init__()
        self.log_channel = log_channel or TurnLogChannel()
        self.notification_channel = notification_channel or NotificationChannel()
        self.control_panel = control_panel or ControlPanel()

        if config is None:
            config = self._create_demo_config()
        self._map_data: List[List[str]] = [list(row) for row in config.map_data]
        self.world_state: MutableMapping[str, object] = config.world_state
        self.world_randomness = WorldRandomness(seed=config.world_seed)
        self.world_state.setdefault("randomness", self.world_randomness)

        self.world = turn_engine.world if turn_engine is not None else GameWorld()
        self._bootstrap_world_components()

        self.event_queue = EventQueue()
        self.season_tracker = SeasonTracker()
        self.turn_engine = turn_engine or TurnEngine(
            season_tracker=self.season_tracker,
            event_queue=self.event_queue,
            resource_pipeline=ResourcePipeline(rng=self.world_randomness.generator("resources")),
            log_channel=self.log_channel,
            notification_channel=self.notification_channel,
            world=self.world,
        )
        if turn_engine is not None:
            self.world = self.turn_engine.world
            self._bootstrap_world_components()

        self.map_view = HexMapView(grid=self._map_data)
        self.dashboard = DashboardView(notification_channel=self.notification_channel)
        self.truck_view = TruckLayoutView()
        self.control_widget = ControlPanelWidget(self.control_panel)
        self.log_widget = TurnLogWidget(self.log_channel)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="body"):
            yield self.map_view
            yield self.dashboard
            yield self.truck_view
            yield self.control_widget
            yield self.log_widget
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_ui()

    # ------------------------------------------------------------------
    def _bootstrap_world_components(self) -> None:
        truck = self.world_state.get("truck")
        if isinstance(truck, Truck):
            self.world.add_singleton(TruckComponent(truck))
            self.world_state["truck"] = truck
        crew_obj = self.world_state.get("crew")
        if not isinstance(crew_obj, Crew):
            crew_obj = Crew()
            self.world_state["crew"] = crew_obj
        self.world.add_singleton(CrewComponent(crew_obj))

        controller = self.world_state.get("faction_controller")
        if not isinstance(controller, FactionAIController):
            controller = FactionAIController()
            self.world_state["faction_controller"] = controller
        self.world.add_singleton(FactionControllerComponent(controller))

        sites_obj = self.world_state.get("sites")
        sites_map: MutableMapping[str, Site]
        if isinstance(sites_obj, MutableMapping):
            filtered: Dict[str, Site] = {}
            for key, value in sites_obj.items():
                if isinstance(key, str) and isinstance(value, Site):
                    filtered[key] = value
            sites_map = filtered
        else:
            sites_map = {}
        self.world_state["sites"] = sites_map
        self.world.add_singleton(SitesComponent(sites_map))

    def action_next_turn(self) -> None:
        command = self.control_panel.build_command_payload()
        context = self.turn_engine.run_turn(command, world_state=self.world_state)
        self.control_panel.reset()
        self.control_widget.refresh_from_panel()
        self._refresh_ui(context=context)

    def action_reset_route(self) -> None:
        self.control_panel.clear_route()
        self.control_widget.refresh_from_panel()

    # ------------------------------------------------------------------
    def on_hex_map_view_coordinate_selected(self, message: HexMapView.CoordinateSelected) -> None:
        selection = message.selection
        waypoint = f"{selection.coordinate[0]},{selection.coordinate[1]}"
        self.control_panel.append_waypoint(waypoint)
        self.control_widget.refresh_from_panel()
        self.dashboard.set_focus_detail(f"{waypoint} ({selection.terrain})")
        self._update_map_highlights()

    def on_control_panel_widget_plan_reset(self, message: ControlPanelWidget.PlanReset) -> None:  # noqa: D401 - Textual hook
        """React to plan resets triggered from the control panel widget."""

        self._update_map_highlights()
        self.dashboard.set_focus_detail(None)

    def on_control_panel_widget_plan_updated(self, message: ControlPanelWidget.PlanUpdated) -> None:  # noqa: D401
        """Refresh map annotations when the control panel changes."""

        self._update_map_highlights()

    # ------------------------------------------------------------------
    def _refresh_ui(self, *, context: TurnContext | None = None) -> None:
        self.map_view.set_map_data(self._map_data)
        self._update_map_highlights()

        truck_component = self.turn_engine.world.get_singleton(TruckComponent)
        truck = truck_component.truck if truck_component is not None else None
        self.truck_view.set_truck(truck if isinstance(truck, Truck) else None)

        stats = self._build_stats(context)
        self.dashboard.update_stats(stats)
        if context is None:
            self.dashboard.set_focus_detail(None)

        self.log_widget.refresh_from_channel()
        self.control_widget.refresh_from_panel()

    def _update_map_highlights(self) -> None:
        highlights: Dict[tuple[int, int], str] = {}
        for index, waypoint in enumerate(self.control_panel.route_waypoints):
            try:
                row_str, col_str = waypoint.split(",", 1)
                coord = (int(row_str), int(col_str))
            except ValueError:
                continue
            label = f"[yellow]{index + 1:02}[/yellow]"
            highlights[coord] = label
        self.map_view.set_highlights(highlights)

    def _build_stats(self, context: TurnContext | None) -> Dict[str, str]:
        stats: Dict[str, str] = {
            "Day": str(self.season_tracker.current_day),
            "Season": self.season_tracker.current_season.name.title(),
        }
        truck_component = self.turn_engine.world.get_singleton(TruckComponent)
        truck = truck_component.truck if truck_component is not None else None
        if isinstance(truck, Truck):
            stats["Truck"] = f"{truck.condition:.0%} condition"
            stats["Crew"] = f"{truck.current_crew_workload}/{truck.crew_capacity}"
            stats["Cargo"] = (
                f"{truck.inventory.total_weight:.0f}kg / {truck.weight_capacity:.0f}kg"
                if isinstance(truck.inventory, Inventory)
                else "0"
            )
        if context is None:
            return stats

        if context.summary_lines:
            stats["Last Turn"] = " | ".join(context.summary_lines)
        elif context.events:
            stats["Last Turn"] = ", ".join(event.event_type for event in context.events)
        elif context.notifications:
            stats["Last Turn"] = context.notifications[-1].message
        return stats

    # ------------------------------------------------------------------
    @staticmethod
    def _create_demo_config(size: int = 9, seed: int = 42) -> AppConfig:
        randomness = WorldRandomness(seed=seed)
        noise = BiomeNoise(randomness=randomness)
        center = HexCoord(0, 0)
        half = size // 2
        grid: List[List[str]] = []
        for r in range(-half, half + 1):
            row: List[str] = []
            for q in range(-half, half + 1):
                coord = HexCoord(center.q + q, center.r + r)
                biome = noise.biome(coord)
                name = biome.value if hasattr(biome, "value") else str(biome)
                row.append(name)
            grid.append(row)
        world_state: MutableMapping[str, object] = {
            "truck": SurvivalTruckApp._create_demo_truck(),
        }
        return AppConfig(map_data=grid, world_state=world_state, world_seed=seed)

    @staticmethod
    def _create_demo_truck() -> Truck:
        truck = Truck(
            name="Nomad Mk I",
            module_capacity=Dimensions(length=4, width=2, height=2),
            crew_capacity=6,
            base_power_output=12,
            base_power_draw=4,
            base_storage_capacity=150,
            base_weight_capacity=4500.0,
            base_maintenance_load=5,
        )
        modules = [
            TruckModule(
                module_id="cabin",
                name="Command Cabin",
                size=Dimensions(length=2, width=2, height=2),
                power_draw=3,
                crew_required=2,
                storage_bonus=20,
            ),
            TruckModule(
                module_id="workshop",
                name="Mobile Workshop",
                size=Dimensions(length=2, width=1, height=2),
                power_draw=2,
                crew_required=1,
                storage_bonus=30,
                maintenance_load=2,
            ),
        ]
        for module in modules:
            truck.equip_module(module)
        truck.inventory = Inventory(max_weight=truck.weight_capacity, max_volume=truck.storage_capacity)
        truck.inventory.add_item(
            InventoryItem(
                item_id="fuel",
                name="Diesel",
                category=ItemCategory.FUEL,
                quantity=320.0,
                weight_per_unit=1.0,
                volume_per_unit=1.0,
            )
        )
        truck.inventory.add_item(
            InventoryItem(
                item_id="food",
                name="Preserved Meals",
                category=ItemCategory.FOOD,
                quantity=120.0,
                weight_per_unit=0.5,
                volume_per_unit=0.3,
            )
        )
        return truck


__all__ = ["SurvivalTruckApp", "AppConfig"]
