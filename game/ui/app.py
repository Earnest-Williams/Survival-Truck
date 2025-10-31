"""Textual application wiring together the Survival Truck dashboard."""

from __future__ import annotations

from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Footer, Header

from ..crew import Crew
from ..engine.resource_pipeline import ResourcePipeline
from ..engine.turn_engine import TurnContext, TurnEngine
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
from ..world.stateframes import SiteStateFrame
from .channels import NotificationChannel, TurnLogChannel
from .control_panel import ControlPanel, ControlPanelWidget
from .dashboard import DashboardView, TurnLogWidget
from .diplomacy import DiplomacyView
from .hex_map import HexMapView
from .help import HelpScreen, HelpSection, build_help_commands
from .truck_layout import TruckLayoutView


@dataclass
class AppConfig:
    """Configuration payload for the UI bootstrap."""

    map_data: Sequence[Sequence[str]]
    world_state: MutableMapping[str, object]
    world_seed: int = 42


class SurvivalTruckApp(App[Any]):
    """Interactive Textual application for Survival Truck."""

    CSS = """
    /* Minimal dark theme — only supported properties are used */
    * {
        border: none;
        background: #141414;
        color: #c0c0c0;
    }
    Header, Footer {
        background: #1c1c1c;
        color: #7a7a7a;
        text-style: bold;
    }

    Screen { layout: grid; grid-rows: auto 1fr auto; }

    #body {
        layout: grid;
        grid-size: 2 5;
        grid-columns: 3fr 2fr;
        grid-rows: auto auto auto auto 1fr;
        grid-gutter: 1;
        padding: 1;
        height: 1fr;
    }

    /* Placement is by compose() order; spans only */
    HexMapView {
        row-span: 4;
    }

    #status { }
    #diplomacy { }
    #truck { }
    #controls { }

    TurnLogWidget {
        column-span: 2;
        border-top: tall #4db6ac;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("space", "next_turn", "Next Day"),
        Binding("r", "reset_route", "Clear Route"),
        Binding("f1", "toggle_help", "Help"),
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
        self._map_data: list[list[str]] = [list(row) for row in config.map_data]
        self.world_state: dict[str, object] = dict(config.world_state)
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
        self.weather_system = self.turn_engine.weather_system
        if turn_engine is not None:
            self.world = self.turn_engine.world
            self._bootstrap_world_components()

        self.map_view = HexMapView(grid=self._map_data)
        self.dashboard = DashboardView(notification_channel=self.notification_channel)
        self.diplomacy_view = DiplomacyView()
        self.truck_view = TruckLayoutView()
        self.control_widget = ControlPanelWidget(self.control_panel)
        self.log_widget = TurnLogWidget(self.log_channel)
        self._help_visible = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="body"):
            yield self.map_view
            yield self.dashboard
            yield self.diplomacy_view
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
        randomness = self.world_state.get("randomness")
        world_rng = randomness if isinstance(randomness, WorldRandomness) else None
        crew_obj = self.world_state.get("crew")
        if not isinstance(crew_obj, Crew):
            crew_obj = Crew(randomness=world_rng)
            self.world_state["crew"] = crew_obj
        self.world.add_singleton(CrewComponent(crew_obj))

        controller = self.world_state.get("faction_controller")
        if not isinstance(controller, FactionAIController):
            controller = FactionAIController(randomness=world_rng)
            self.world_state["faction_controller"] = controller
        self.world.add_singleton(FactionControllerComponent(controller))

        sites_obj = self.world_state.get("sites")
        if isinstance(sites_obj, SiteStateFrame):
            site_state = sites_obj
        elif isinstance(sites_obj, MutableMapping):
            filtered: dict[str, Site] = {}
            for key, value in sites_obj.items():
                if isinstance(key, str) and isinstance(value, Site):
                    filtered[key] = value
            site_state = SiteStateFrame.from_sites(filtered)
        else:
            site_state = SiteStateFrame()
        self.world_state["sites"] = site_state
        self.world.add_singleton(SitesComponent(site_state))

    def action_next_turn(self) -> None:
        command = self.control_panel.build_command_payload()
        context = self.turn_engine.run_turn(command, world_state=self.world_state)
        self.control_panel.reset()
        self.control_widget.refresh_from_panel()
        self._refresh_ui(context=context)

    def action_reset_route(self) -> None:
        self.control_panel.clear_route()
        self.control_widget.refresh_from_panel()

    def action_toggle_help(self) -> None:
        if self._help_visible:
            self.pop_screen()
            return

        sections = self._build_help_sections()
        help_screen = HelpScreen(sections, on_close=self._on_help_closed)
        self._help_visible = True
        self.push_screen(help_screen)

    def _on_help_closed(self) -> None:
        self._help_visible = False

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

        faction_controller_component = self.turn_engine.world.get_singleton(
            FactionControllerComponent
        )
        controller = (
            faction_controller_component.controller
            if faction_controller_component is not None
            else None
        )
        if controller is not None:
            graph = controller.diplomacy.as_graph(controller.factions.keys())
            factions = controller.factions
        else:
            graph = None
            factions = {}
        self.diplomacy_view.update_snapshot(factions=factions, graph=graph)

        self.log_widget.refresh_from_channel()
        self.control_widget.refresh_from_panel()

    def _update_map_highlights(self) -> None:
        highlights: dict[tuple[int, int], str] = {}
        for index, waypoint in enumerate(self.control_panel.route_waypoints):
            try:
                row_str, col_str = waypoint.split(",", 1)
                coord = (int(row_str), int(col_str))
            except ValueError:
                continue
            label = f"[yellow]{index + 1:02}[/yellow]"
            highlights[coord] = label
        self.map_view.set_highlights(highlights)

    def _build_stats(self, context: TurnContext | None) -> dict[str, str]:
        stats: dict[str, str] = {
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

    def _build_help_sections(self) -> list[HelpSection]:
        sections: list[HelpSection] = []

        app_bindings = self._bindings_for(self)
        if app_bindings:
            sections.append(HelpSection("Application", build_help_commands(app_bindings)))

        map_bindings = self._bindings_for(self.map_view)
        if map_bindings:
            sections.append(HelpSection("Map", build_help_commands(map_bindings)))

        dashboard_bindings = self._bindings_for(self.dashboard)
        if dashboard_bindings:
            sections.append(HelpSection("Dashboard", build_help_commands(dashboard_bindings)))

        control_bindings = self._bindings_for(self.control_widget)
        if control_bindings:
            sections.append(HelpSection("Control Panel", build_help_commands(control_bindings)))

        return sections

    @staticmethod
    def _bindings_for(target: object) -> list[Binding]:
        bindings: list[Binding] = []
        candidate = getattr(target, "BINDINGS", None)
        if isinstance(candidate, Sequence):
            for binding in candidate:
                if isinstance(binding, Binding):
                    bindings.append(binding)
        return bindings

    # ------------------------------------------------------------------
    @staticmethod
    def _create_demo_config(size: int = 9, seed: int = 42) -> AppConfig:
        randomness = WorldRandomness(seed=seed)
        noise = BiomeNoise(randomness=randomness)
        center = HexCoord(0, 0)
        half = size // 2
        grid: list[list[str]] = []
        for r in range(-half, half + 1):
            row: list[str] = []
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
        truck.inventory = Inventory(
            max_weight=truck.weight_capacity, max_volume=truck.storage_capacity
        )
        truck.inventory.add_item(
            InventoryItem(
                item_id="fuel",
                name="Diesel",
                category=ItemCategory.FUEL,
                quantity=150.0,
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
