"""Textual application wiring together the Survival Truck dashboard."""

from __future__ import annotations

from collections.abc import MutableMapping, Sequence, Mapping
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
from .config_store import HexLayoutConfig
from .control_panel import ControlPanel, ControlPanelWidget
from .dashboard import DashboardView, TurnLogWidget
from .diplomacy import DiplomacyView
from .hex_canvas import HexCanvas
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
    HexCanvas {
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
        self._terrain_symbols: dict[str, str] = {
            "plains": "Pl",
            "forest": "Fo",
            "tundra": "Tu",
            "mountain": "Mt",
            "coast": "Co",
            "ruin": "Ru",
            "wasteland": "Wa",
            "scrub": "Sc",
            "desert": "De",
            "swamp": "Sw",
        }
        self._terrain_fill_codes: dict[str, str] = {
            "forest": "Fo",
            "swamp": "Fo",
            "plains": "Sc",
            "scrub": "Sc",
            "tundra": "Sc",
            "coast": "Sc",
            "ruin": "Ba",
            "wasteland": "Ba",
            "mountain": "Ba",
            "desert": "Ba",
        }
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

        # ------------------------------------------------------------------
        # Restore persisted simulation state.  The persistence manager
        # stores both world_state entries (events, missions, negotiations)
        # and faction data (ideology weights, traits, reputation) in a
        # single save file.  After world and AI components have been
        # initialised, we merge any saved values into the active state.
        try:
            from ..world.persistence import load_game_state  # type: ignore
        except Exception:
            load_game_state = None  # type: ignore[assignment]
        if load_game_state is not None:
            try:
                saved_state, saved_factions = load_game_state(slot="default")
                if isinstance(saved_state, Mapping):
                    # Update world_state but avoid overwriting randomness or
                    # other non‑persisted keys; saved_state was already
                    # filtered when written.
                    self.world_state.update(saved_state)
                # Restore faction ideology weights, traits and reputation
                fc_comp = self.turn_engine.world.get_singleton(FactionControllerComponent)
                controller = fc_comp.controller if fc_comp is not None else None
                if controller is not None and isinstance(saved_factions, Mapping):
                    for fac_name, fac_data in saved_factions.items():
                        if fac_name not in controller.factions:
                            continue
                        # Ideology weights
                        try:
                            ide_weights = fac_data.get("ideology_weights", None)
                            if isinstance(ide_weights, Mapping):
                                controller.ledger.set_ideology_weights(fac_name, ide_weights)  # type: ignore[attr-defined]
                        except Exception:
                            pass
                        # Traits
                        traits_data = fac_data.get("traits", {})
                        if isinstance(traits_data, Mapping):
                            for t_name, t_val in traits_data.items():
                                try:
                                    controller.ledger.set_trait(fac_name, str(t_name), float(t_val))
                                except Exception:
                                    continue
                        # Reputation
                        try:
                            rep_val = float(fac_data.get("reputation", 0.0))
                            current_rep = float(getattr(controller.factions[fac_name], "reputation", 0.0))
                            delta = rep_val - current_rep
                            if abs(delta) > 1e-6:
                                controller.factions[fac_name].adjust_reputation(delta)
                        except Exception:
                            pass
            except Exception:
                # Ignore failures in loading state; the game will start fresh.
                pass

        rows = len(self._map_data)
        cols = max((len(row) for row in self._map_data), default=0)
        initial_tiles, initial_labels = self._build_canvas_payload(self._map_data)
        self.map_view = HexCanvas(
            cols=cols,
            rows=rows,
            radius=12,
            tiles=initial_tiles,
            labels=initial_labels,
        )
        self.dashboard = DashboardView(notification_channel=self.notification_channel)
        self.diplomacy_view = DiplomacyView()
        self.truck_view = TruckLayoutView()
        self.control_widget = ControlPanelWidget(self.control_panel)
        self.log_widget = TurnLogWidget(self.log_channel)
        self._help_visible = False
        # Summarise the loaded layout and mark it as saved (no unsaved flag).
        initial_cfg = HexLayoutConfig.load()
        self.dashboard.update_layout_config(
            self._summarise_layout_config(initial_cfg), unsaved=initial_cfg.dirty
        )

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

        # Remove any expired active events before generating new ones.  Each
        # event carries an 'expires' day; events with expiry <= current day
        # are pruned from the active list.  This keeps the world_state
        # consistent and prevents stale effects lingering forever.
        try:
            self._update_active_events(context)
        except Exception as err:
            if self.notification_channel is not None:
                self.notification_channel.notify(
                    day=self.season_tracker.current_day,
                    message=f"Active event update failed: {err}",
                    payload={},
                )

        # ------------------------------------------------------------------
        # World events: generate emergent events based on season and weather.
        # These random events add narrative variety (e.g. travelling caravans,
        # bandit ambushes, storms).  The generator uses a seeded RNG to
        # produce deterministic outcomes given the same world seed.  Any
        # errors in event generation are reported via the notification
        # channel but do not halt the turn progression.
        try:
            self._generate_world_events(context)
        except Exception as err:
            # Surface failures but continue processing the turn.
            if self.notification_channel is not None:
                self.notification_channel.notify(
                    day=self.season_tracker.current_day,
                    message=f"World event generation failed: {err}",
                    payload={},
                )

        # Dispatch world events into missions and diplomatic consequences.
        try:
            self._dispatch_events(context)
        except Exception as err:
            if self.notification_channel is not None:
                self.notification_channel.notify(
                    day=self.season_tracker.current_day,
                    message=f"Event dispatch failed: {err}",
                    payload={},
                )

        # After world and events have advanced, process any outstanding
        # negotiations. Negotiation proposals are generated by the faction AI
        # controller and stored in the world_state under the "negotiations"
        # key. Each proposal can be accepted or declined; this helper
        # automatically selects a default response based on the proposal type
        # and applies the resulting reputation adjustments. The proposal is
        # removed from the list once processed. Errors are captured and
        # surfaced via the notification channel.
        try:
            self._process_negotiations(context)
        except Exception as err:
            if self.notification_channel is not None:
                self.notification_channel.notify(
                    day=self.season_tracker.current_day,
                    message=f"Negotiation processing failed: {err}",
                    payload={},
                )

        # After processing negotiations, handle expired missions.  Missions
        # generated from world events expire after a few days; failing
        # to complete them reduces the player's reputation with the
        # issuing faction.
        try:
            self._process_expired_missions(context)
        except Exception as err:
            if self.notification_channel is not None:
                self.notification_channel.notify(
                    day=self.season_tracker.current_day,
                    message=f"Expired mission processing failed: {err}",
                    payload={},
                )

        self.control_panel.reset()
        self.control_widget.refresh_from_panel()
        self._refresh_ui(context=context)

        # Persist simulation state after each turn.  Save the world_state
        # together with faction ideology weights, traits and reputation via
        # the persistence manager.  This ensures that events, missions,
        # negotiations and faction attributes survive across sessions.
        try:
            from ..world.persistence import save_game_state  # type: ignore
        except Exception:
            save_game_state = None  # type: ignore[assignment]
        if save_game_state is not None:
            try:
                fc_comp = self.turn_engine.world.get_singleton(FactionControllerComponent)
                controller = fc_comp.controller if fc_comp is not None else None
                if controller is not None:
                    save_game_state(self.world_state, controller, slot="default")
            except Exception:
                # Ignore persistence errors; state will be saved on next turn.
                pass

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
    def on_hex_canvas_hex_clicked(self, message: HexCanvas.HexClicked) -> None:
        row = int(message.r)
        col = int(message.q)
        waypoint = f"{row},{col}"
        self.control_panel.append_waypoint(waypoint)
        self.control_widget.refresh_from_panel()
        terrain = self._terrain_at(row, col)
        if terrain is not None:
            self.dashboard.set_focus_detail(f"{waypoint} ({terrain})")
        else:
            self.dashboard.set_focus_detail(waypoint)
        # Build site context details: summarise current events, missions and
        # negotiations in the world state.  This gives the player
        # situational awareness when clicking on the map.  We do not yet
        # associate events with specific sites, so we show a flat list.
        lines: list[str] = []
        try:
            # Active events
            events = self.world_state.get("active_events", [])
            if isinstance(events, list):
                for ev in events:
                    try:
                        desc = str(ev.get("description", ""))
                        exp = int(ev.get("expires", 0))
                        lines.append(f"Event: {desc} (expires day {exp})")
                    except Exception:
                        continue
            # Missions
            missions = self.world_state.get("missions", [])
            if isinstance(missions, list):
                for m in missions:
                    try:
                        fac = str(m.get("faction", ""))
                        desc = str(m.get("description", ""))
                        exp = int(m.get("expires", 0))
                        lines.append(f"Mission: {desc} from {fac} (expires day {exp})")
                    except Exception:
                        continue
            # Negotiations
            negotiations = self.world_state.get("negotiations", [])
            if isinstance(negotiations, list):
                for n in negotiations:
                    try:
                        fac = str(n.get("faction", ""))
                        desc = str(n.get("description", ""))
                        exp = int(n.get("expires", 0))
                        lines.append(f"Negotiation: {desc} from {fac} (expires day {exp})")
                    except Exception:
                        continue
        except Exception:
            lines = []
        # Update site context on the dashboard
        try:
            self.dashboard.update_site_context(lines)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _generate_world_events(self, context: TurnContext) -> None:
        """Generate random world events based on season and weather.

        This helper uses the seeded world randomness to emit narrative events
        (travelling caravans, bandit ambushes, storms) that enrich the game
        without breaking determinism.  Events are appended to the
        ``world_state['world_events']`` list and surfaced to the player via
        notifications.

        Args:
            context: The turn context for the current day.
        """
        # Acquire a deterministic RNG stream for event generation.  Each
        # stream name yields its own independent sequence based off the
        # world seed, ensuring that events are reproducible across runs.
        rng = self.world_randomness.generator("events")

        season_name = getattr(context.season, "name", "unknown").lower()
        weather_name = getattr(context.weather, "condition", None)
        if weather_name is None:
            # The weather condition may be a WeatherCondition enum with a name
            # attribute; fall back to its string representation.
            weather_name = str(getattr(context.weather, "name", "unknown")).lower()
        weather_lower = str(weather_name).lower()

        events: list[tuple[str, str]] = []

        # Example random event: a travelling caravan appears in spring and
        # summer with a moderate probability.  Offer trade opportunities.
        if season_name in {"spring", "summer"} and rng.random() < 0.05:
            events.append(("caravan", "A travelling caravan passes nearby, offering trade opportunities."))

        # Bandit ambushes are more likely when the player is carrying heavy
        # cargo; we approximate this by comparing cargo weight to capacity.
        truck_comp = self.turn_engine.world.get_singleton(TruckComponent)
        truck_obj = getattr(truck_comp, "truck", None) if truck_comp is not None else None
        cargo_ratio = 0.0
        if truck_obj is not None:
            try:
                cargo_weight = getattr(truck_obj.inventory, "total_weight", 0.0)
                capacity = float(getattr(truck_obj, "weight_capacity", 1.0))
                cargo_ratio = cargo_weight / max(capacity, 1.0)
            except Exception:
                cargo_ratio = 0.0
        # Higher cargo ratio increases ambush probability.
        ambush_chance = 0.02 + min(0.2, cargo_ratio * 0.3)
        if rng.random() < ambush_chance:
            events.append(("ambush", "Bandits ambush travellers in the area. Travel risk increases."))

        # Storm intensification: if the current weather contains "storm",
        # there is a chance the storm will intensify, increasing travel costs.
        if "storm" in weather_lower and rng.random() < 0.2:
            events.append(("storm", "The storm intensifies, making travel more difficult."))

        # Pandemics or plagues: occur rarely, mostly in autumn and winter.
        if season_name in {"autumn", "winter"} and rng.random() < 0.01:
            events.append(("pandemic", "An illness spreads among local settlements, reducing populations."))

        # Derelict convoy: occasionally a derelict research convoy appears as a new scavenging site.
        if rng.random() < 0.02:
            events.append(("derelict", "A derelict convoy is spotted nearby. It could yield valuable salvage."))

        # Process events: record them and notify the player.
        if not events:
            return
        # Store events in a unified list under the "events" key.  Each
        # entry records the day, type and description.  Active events
        # persist beyond one day and are separately tracked.
        events_list: list[dict[str, object]] = self.world_state.setdefault("events", [])  # type: ignore[assignment]
        for event_type, description in events:
            # Append to the persistent events list.  Consumers may
            # dispatch these events into missions or diplomatic effects.
            events_list.append({
                "day": context.day,
                "type": event_type,
                "description": description,
            })
            # Notify the player.
            context.notify(
                description,
                category="event",
                payload={"type": event_type},
            )
            # Also register the event as active if it persists beyond the
            # current day.  Ambush and caravan events are one-day events,
            # while storms, pandemics and derelict convoys linger.  We
            # compute an expiration day relative to the current day.
            expires_in = 0
            if event_type == "storm":
                expires_in = 1 + int(rng.random() * 2)
            elif event_type == "pandemic":
                expires_in = 3 + int(rng.random() * 3)
            elif event_type == "derelict":
                expires_in = 6
            if expires_in > 0:
                active_list: list[dict[str, object]] = self.world_state.setdefault("active_events", [])  # type: ignore[assignment]
                active_list.append({
                    "type": event_type,
                    "description": description,
                    "expires": context.day + expires_in,
                })

    def _update_active_events(self, context: TurnContext) -> None:
        """Remove expired active events from the world state.

        Active events persist across days until their ``expires`` day has
        passed.  Each call to this method filters out events with
        ``expires <= context.day``.  You could extend this method to
        apply ongoing effects to the simulation (e.g. modify site yields
        or travel modifiers) while the event remains active.

        Args:
            context: The current turn context.
        """
        active_list: list[dict[str, object]] | None = self.world_state.get("active_events")  # type: ignore[assignment]
        if not active_list:
            return
        remaining: list[dict[str, object]] = []
        for record in active_list:
            try:
                expires = int(record.get("expires", 0))
            except Exception:
                expires = 0
            if expires > context.day:
                remaining.append(record)
        # Replace the active events list with remaining events.
        self.world_state["active_events"] = remaining  # type: ignore[assignment]
        self._update_map_highlights()

    # ------------------------------------------------------------------
    def _dispatch_events(self, context: TurnContext) -> None:
        """Process queued world events and produce missions or diplomatic effects.

        World events generated by :meth:`_generate_world_events` are stored
        in ``world_state['events']``.  This dispatcher examines each event
        and, when appropriate, creates missions for the player or
        triggers diplomacy adjustments.  After processing, the events
        list is cleared to avoid re-dispatching in subsequent turns.

        Currently, caravan, pandemic, storm and derelict events create
        escort, aid, weather reconnaissance and salvage missions,
        respectively.  Ambush events do not create missions but could
        modify risk or standing in future expansions.

        Args:
            context: The current turn context providing the day number.
        """
        raw_events = self.world_state.get("events")
        if not isinstance(raw_events, list) or not raw_events:
            return
        events: list[Mapping[str, object]] = list(raw_events)
        # Access the faction controller to choose mission issuers.
        faction_controller_component = self.turn_engine.world.get_singleton(
            FactionControllerComponent
        )
        controller = (
            faction_controller_component.controller
            if faction_controller_component is not None
            else None
        )
        # Prepare a generator for random selection.  Use a dedicated
        # stream to ensure deterministic behaviour.
        event_rng = self.world_randomness.generator("event-dispatch")
        missions = list(self.world_state.get("missions", []))  # type: ignore[list-item]
        if controller is None or not controller.factions:
            # No available factions to assign missions; simply clear events.
            self.world_state["events"] = []  # type: ignore[assignment]
            return
        faction_names = list(controller.factions.keys())
        for ev in events:
            ev_type = str(ev.get("type", ""))
            # Choose a random faction to issue the mission
            try:
                issuer = event_rng.choice(faction_names)
            except Exception:
                issuer = faction_names[0]
            day = int(getattr(context, "day", self.season_tracker.current_day))
            if ev_type == "caravan":
                missions.append({
                    "faction": issuer,
                    "type": "escort_caravan_event",
                    "description": "Escort a travelling caravan spawned by a world event.",
                    "reward": 15.0,
                    "expires": day + 5,
                })
            elif ev_type == "pandemic":
                missions.append({
                    "faction": issuer,
                    "type": "deliver_aid_event",
                    "description": "Deliver aid to settlements affected by a spreading illness.",
                    "reward": 20.0,
                    "expires": day + 5,
                })
            elif ev_type == "storm":
                missions.append({
                    "faction": issuer,
                    "type": "weather_recon_event",
                    "description": "Gather weather data and assist travellers during an intensifying storm.",
                    "reward": 10.0,
                    "expires": day + 4,
                })
            elif ev_type == "derelict":
                missions.append({
                    "faction": issuer,
                    "type": "salvage_event",
                    "description": "Salvage supplies from a derelict convoy spotted nearby.",
                    "reward": 15.0,
                    "expires": day + 6,
                })
            # Ambush and other events currently do not generate missions.
        # Deduplicate missions by (faction, type, expires)
        unique_missions: list[dict[str, object]] = []
        seen_keys: set[tuple[str, str, int]] = set()
        for m in missions:
            fac = str(m.get("faction", ""))
            typ = str(m.get("type", ""))
            exp = int(m.get("expires", 0))
            key = (fac, typ, exp)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            unique_missions.append(m)
        self.world_state["missions"] = unique_missions  # type: ignore[assignment]
        # Clear processed events
        self.world_state["events"] = []  # type: ignore[assignment]

    # ------------------------------------------------------------------
    def _process_expired_missions(self, context: TurnContext) -> None:
        """Handle missions that have expired without being completed.

        Missions generated by world events have an expiry date.  When a
        mission expires, it is considered ignored by the player.  This
        method removes expired missions from the list and adjusts the
        player's reputation with the issuing faction downward.  The
        reputation penalty is modest (–5 points) but can accumulate
        across multiple ignored missions.

        Args:
            context: The current turn context containing the day number.
        """
        raw_missions = self.world_state.get("missions")
        if not isinstance(raw_missions, list) or not raw_missions:
            return
        missions: list[Mapping[str, object]] = list(raw_missions)
        current_day = int(getattr(context, "day", self.season_tracker.current_day))
        # Access faction ledger for reputation adjustments
        faction_controller_component = self.turn_engine.world.get_singleton(
            FactionControllerComponent
        )
        controller = (
            faction_controller_component.controller
            if faction_controller_component is not None
            else None
        )
        remaining: list[dict[str, object]] = []
        for m in missions:
            exp = int(m.get("expires", current_day))
            fac_name = str(m.get("faction", ""))
            m_type = str(m.get("type", ""))
            if exp > current_day:
                # Mission still valid; keep it
                remaining.append(dict(m))
                continue
            # Mission expired: apply penalty if it originated from an event
            # Event-based missions have types ending with "_event"
            if m_type.endswith("_event") and controller is not None and fac_name in controller.factions:
                # Decrease reputation by 5 points
                try:
                    # Decrease player reputation with the issuing faction.
                    controller.ledger.adjust_reputation(fac_name, -5.0)
                    # Record a memory event so future AI decisions can use it.
                    controller.ledger.record_memory(
                        fac_name,
                        event=f"ignored {m_type}",
                        impact=-5.0,
                        day=current_day,
                        decay_rate=0.05,
                    )
                    # Reduce the issuing faction's standing with all other factions.
                    # Ignoring aid erodes trust between factions as well. We apply
                    # a small negative adjustment to the diplomatic standing for
                    # each pair (issuer, other). The adjustment is symmetric.
                    for other_name in controller.factions.keys():
                        if other_name == fac_name:
                            continue
                        try:
                            controller.diplomacy.adjust_standing(fac_name, other_name, -0.05)
                        except Exception:
                            pass
                    # Notify the player about both reputation and inter-faction impact.
                    if self.notification_channel is not None:
                        self.notification_channel.notify(
                            day=current_day,
                            message=(
                                f"You ignored a mission from {fac_name}. Reputation decreased and their relations"
                                " with other factions suffered."
                            ),
                            payload={},
                        )
                except Exception:
                    pass
        # Write back the remaining missions
        self.world_state["missions"] = remaining  # type: ignore[assignment]

    # ------------------------------------------------------------------
    def _process_negotiations(self, context: TurnContext) -> None:
        """Process outstanding negotiation proposals.

        Faction AI controllers may generate negotiation proposals (truces,
        tribute demands, aid requests, coalition invites) and store them
        under the ``"negotiations"`` key in the world state. Each
        negotiation is a mapping with at least ``faction``, ``type``,
        ``demand``, ``reward`` and ``expires`` fields. This method loops
        through all proposals, applies a default decision and then
        adjusts player reputation via the faction ledger. Negotiations
        that have expired are removed silently. After processing, the
        updated list of negotiations is written back into the world
        state.

        Args:
            context: The current turn context containing the day counter.
        """
        negotiations: list[dict[str, object]] = []
        raw = self.world_state.get("negotiations")
        if isinstance(raw, list):
            negotiations = [dict(item) for item in raw]
        current_day = getattr(context, "day", self.season_tracker.current_day)

        # Access the faction controller and ledger to modify reputation.
        faction_controller_component = self.turn_engine.world.get_singleton(
            FactionControllerComponent
        )
        controller = (
            faction_controller_component.controller
            if faction_controller_component is not None
            else None
        )
        if controller is None:
            # No factions to negotiate with.
            self.world_state["negotiations"] = []  # type: ignore[assignment]
            return

        remaining: list[dict[str, object]] = []
        for proposal in negotiations:
            fac_name = str(proposal.get("faction", ""))
            exp = int(proposal.get("expires", current_day))
            # Skip proposals for unknown or missing factions.
            if not fac_name or fac_name not in controller.factions:
                continue
            # Remove expired negotiations.
            if exp <= current_day:
                continue
            # Determine automatic acceptance policy. For demonstration we
            # accept non-negative proposals (net >= 0) and decline
            # negative ones. Net is reward minus demand.
            demand = float(proposal.get("demand", 0.0) or 0.0)
            reward = float(proposal.get("reward", 0.0) or 0.0)
            net = reward - demand
            accepted = net >= 0
            # Apply effects and notify.
            self._apply_negotiation_effect(context=context, proposal=proposal, accepted=accepted)
            # Negotiation is consumed regardless of acceptance.
            # Do not append to remaining.
        # Clear all negotiations after processing.
        self.world_state["negotiations"] = []  # type: ignore[assignment]

    def _apply_negotiation_effect(
        self,
        *,
        context: TurnContext,
        proposal: Mapping[str, object],
        accepted: bool,
    ) -> None:
        """Apply the outcome of a negotiation proposal.

        Adjust the player's reputation with the issuing faction based on
        whether the player accepted or declined the proposal. For now,
        standing is unaffected since the player is not a faction.

        Args:
            context: The current turn context.
            proposal: The negotiation mapping containing details of the
                proposal (faction, type, demand, reward, expires).
            accepted: True if the proposal was accepted, False if declined.
        """
        faction_name = str(proposal.get("faction", ""))
        if not faction_name:
            return
        faction_controller_component = self.turn_engine.world.get_singleton(
            FactionControllerComponent
        )
        controller = (
            faction_controller_component.controller
            if faction_controller_component is not None
            else None
        )
        if controller is None or faction_name not in controller.factions:
            return
        faction = controller.factions[faction_name]
        demand = float(proposal.get("demand", 0.0) or 0.0)
        reward = float(proposal.get("reward", 0.0) or 0.0)
        n_type = str(proposal.get("type", ""))

        # Determine reputation delta based on outcome. Accepting a
        # coalition or aid request yields a positive bonus scaled by reward.
        # Accepting a tribute demand has a minor positive effect, while
        # declining any proposal incurs a penalty scaled by the demand.
        rep_delta: float
        if accepted:
            if n_type == "tribute":
                rep_delta = max(1.0, reward * 0.1)
            else:
                rep_delta = max(1.0, reward * 0.1)
        else:
            # Declining reduces reputation in proportion to the demand.
            rep_delta = -max(1.0, demand * 0.1)
        # Apply reputation change.
        new_rep = faction.adjust_reputation(rep_delta)
        # Record a memory event for this negotiation. We use a modest
        # decay rate so that the effect lingers for some time.
        ledger = controller.ledger
        try:
            ledger.record_memory(
                faction_name,
                event=f"negotiation:{n_type}",
                impact=rep_delta,
                day=getattr(context, "day", self.season_tracker.current_day),
                decay_rate=0.02,
            )
        except Exception:
            pass
        # Notify the player of the outcome.
        if self.notification_channel is not None:
            outcome = "accepted" if accepted else "declined"
            net = reward - demand
            message = (
                f"You {outcome} a {n_type} proposal from {faction_name} (net {net:+.0f})."
                f" Reputation now {new_rep:+.1f}."
            )
            self.notification_channel.notify(
                day=getattr(context, "day", self.season_tracker.current_day),
                message=message,
                payload={"faction": faction_name, "type": n_type, "accepted": accepted},
            )

    def on_control_panel_widget_plan_reset(self, message: ControlPanelWidget.PlanReset) -> None:  # noqa: D401 - Textual hook
        """React to plan resets triggered from the control panel widget."""

        self._update_map_highlights()
        self.dashboard.set_focus_detail(None)

    def on_control_panel_widget_plan_updated(self, message: ControlPanelWidget.PlanUpdated) -> None:  # noqa: D401
        """Refresh map annotations when the control panel changes."""

        self._update_map_highlights()

    # ------------------------------------------------------------------
    def _refresh_ui(self, *, context: TurnContext | None = None) -> None:
        self._refresh_map_view()
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
        # Surface any pending negotiations stored in world_state. Negotiation
        # proposals are generated by the FactionAIController and stored as a list
        # of mapping objects under the "negotiations" key. See diplomacy.py
        # for display details.
        negotiations = self.world_state.get("negotiations", [])
        try:
            seq_negotiations: Sequence[Mapping[str, object]] | None
            if isinstance(negotiations, Sequence):
                # Ensure we only pass sequence types (e.g. list of dicts).
                seq_negotiations = [dict(item) for item in negotiations]  # type: ignore[misc]
            else:
                seq_negotiations = None
        except Exception:
            seq_negotiations = None
        # Determine which factions are currently linked to world events via
        # event-generated missions.  Missions originating from world
        # events have types ending with "_event" and include a
        # ``faction`` field indicating the issuer.  We build a mapping of
        # faction names to True for highlighting in the diplomacy panel.
        event_flags: dict[str, bool] = {}
        try:
            raw_missions = self.world_state.get("missions")
            if isinstance(raw_missions, Sequence):
                for m in raw_missions:
                    try:
                        m_type = str(m.get("type", ""))
                        fac = str(m.get("faction", ""))
                    except Exception:
                        continue
                    if m_type.endswith("_event") and fac:
                        event_flags[fac] = True
        except Exception:
            event_flags = {}
        self.diplomacy_view.update_snapshot(
            factions=factions,
            graph=graph,
            negotiations=seq_negotiations,
            event_flags=event_flags,
        )

        self.log_widget.refresh_from_channel()
        self.control_widget.refresh_from_panel()

    def _refresh_map_view(self) -> None:
        rows = len(self._map_data)
        cols = max((len(row) for row in self._map_data), default=0)
        tiles, labels = self._build_canvas_payload(self._map_data)
        self.map_view.cols = cols
        self.map_view.rows = rows
        self.map_view.set_tiles(tiles)
        self.map_view.set_labels(labels)

    def _update_map_highlights(self) -> None:
        highlights: dict[tuple[int, int], str] = {}
        for index, waypoint in enumerate(self.control_panel.route_waypoints):
            try:
                row_str, col_str = waypoint.split(",", 1)
                row = int(row_str)
                col = int(col_str)
            except ValueError:
                continue
            if not self._in_bounds(row, col):
                continue
            label = f"[yellow]{index + 1:02}[/yellow]"
            highlights[(col, row)] = label
        self.map_view.set_highlights(highlights)

    def _build_canvas_payload(
        self, grid: Sequence[Sequence[str]]
    ) -> tuple[dict[tuple[int, int], str], dict[tuple[int, int], str]]:
        tiles: dict[tuple[int, int], str] = {}
        labels: dict[tuple[int, int], str] = {}
        for row_index, row in enumerate(grid):
            for col_index, terrain in enumerate(row):
                terrain_text = str(terrain)
                tiles[(col_index, row_index)] = self._terrain_code_for(terrain_text)
                labels[(col_index, row_index)] = self._terrain_symbol_for(terrain_text)
        return tiles, labels

    def _terrain_symbol_for(self, terrain: str) -> str:
        trimmed = terrain.strip()
        if not trimmed:
            return "??"
        normalised = trimmed.lower()
        symbol = self._terrain_symbols.get(normalised)
        if symbol:
            return symbol
        if len(trimmed) == 1:
            return trimmed.upper()
        return trimmed[:2].title()

    def _terrain_code_for(self, terrain: str) -> str:
        trimmed = terrain.strip()
        if not trimmed:
            return "Sc"
        normalised = trimmed.lower()
        return self._terrain_fill_codes.get(normalised, "Sc")

    def _terrain_at(self, row: int, col: int) -> str | None:
        if not self._in_bounds(row, col):
            return None
        return str(self._map_data[row][col])

    def _in_bounds(self, row: int, col: int) -> bool:
        if row < 0 or col < 0:
            return False
        if row >= len(self._map_data):
            return False
        row_data = self._map_data[row]
        return col < len(row_data)

    def _build_stats(self, context: TurnContext | None) -> dict[str, str]:
        """Construct a dictionary of campaign statistics for the dashboard.

        In addition to basic information about the day, season and truck
        state, this method surfaces telemetry produced by the `TurnEngine`.
        The engine records the current weather, travel modifiers and recent
        travel costs into ``context.world_state``.  Rendering these values
        helps players understand how external factors like storms and load
        weight affect movement costs and plan routes accordingly.

        Args:
            context: The current turn context, or ``None`` if no turn has
                been processed yet.

        Returns:
            A mapping of statistic names to string representations.
        """
        stats: dict[str, str] = {
            "Day": str(self.season_tracker.current_day),
            "Season": self.season_tracker.current_season.name.title(),
        }
        # Include a countdown to the next season change so players can
        # anticipate upcoming shifts in environmental modifiers.  Use a
        # try/except wrapper to avoid raising within the UI if the season
        # tracker encounters unexpected state.
        try:
            days_left = self.season_tracker.days_until_next_season()
            stats["Days Until Next Season"] = str(days_left)
        except Exception:
            pass

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

        # ------------------------------------------------------------------
        # Telemetry: surface weather and travel cost details if available.
        # The TurnEngine populates ``world_state["weather"]`` with the current
        # weather condition and modifiers, and ``world_state["last_travel_cost"]``
        # with the adjusted and base travel costs.  Present these values on
        # the campaign stats panel so players can see environmental pressures.
        weather_record: Any | None = None
        try:
            weather_record = context.world_state.get("weather")
        except Exception:
            weather_record = None
        if isinstance(weather_record, dict):
            condition = weather_record.get("condition")
            travel_mod = weather_record.get("travel_modifier")
            if condition is not None and travel_mod is not None:
                try:
                    # Format the travel modifier as a multiplier (e.g. x1.20)
                    stats["Weather"] = f"{str(condition).title()} (x{float(travel_mod):.2f})"
                except Exception:
                    stats["Weather"] = str(condition).title()

        last_travel: Any | None = None
        try:
            last_travel = context.world_state.get("last_travel_cost")
        except Exception:
            last_travel = None
        if isinstance(last_travel, dict):
            adjusted = last_travel.get("adjusted_cost")
            base_cost = last_travel.get("base_cost")
            if isinstance(adjusted, (int, float)) and isinstance(base_cost, (int, float)):
                stats["Travel Cost"] = f"{adjusted:.2f} (base {base_cost:.2f})"

            # Expose travel modifier and load factor separately.  These values
            # reflect the impact of weather/season and truck weight/power on
            # movement costs.  Prefix with 'x' to clarify multiplicative effect.
            modifier = last_travel.get("modifier")
            load_factor = last_travel.get("load_factor")
            if isinstance(modifier, (int, float)):
                stats["Travel Modifier"] = f"x{float(modifier):.2f}"
            if isinstance(load_factor, (int, float)):
                stats["Load Factor"] = f"x{float(load_factor):.2f}"

        # ------------------------------------------------------------------

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
    def _summarise_layout_config(config: HexLayoutConfig) -> dict[str, str]:
        return {
            "Orientation": config.orientation.title(),
            "Hex Height": f"{config.hex_height:.1f}",
            "Flatten": f"{config.flatten:.2f}",
            "Origin": f"({config.origin_x:.1f}, {config.origin_y:.1f})",
            "Offset": config.offset_mode,
        }

    def on_hex_canvas_layout_config_changed(
        self, event: HexCanvas.LayoutConfigChanged
    ) -> None:
        summary = self._summarise_layout_config(event.config)
        # Pass through the dirty flag so the dashboard can display an unsaved marker.
        self.dashboard.update_layout_config(summary, unsaved=event.config.dirty)

    def on_hex_canvas_layout_config_saved(self, event: HexCanvas.LayoutConfigSaved) -> None:
        summary = self._summarise_layout_config(event.config)
        # A saved configuration is not dirty; update accordingly.
        self.dashboard.update_layout_config(summary, unsaved=event.config.dirty)
        self.notification_channel.notify(
            day=self.season_tracker.current_day,
            message="Hex layout saved",
            payload=summary,
        )

    def on_hex_canvas_layout_config_save_failed(self, event: HexCanvas.LayoutConfigSaveFailed) -> None:
        """Notify the user when saving the hex layout fails.

        If persisting the configuration raises an exception, display a notification
        explaining that the save failed.  The unsaved flag remains set so the
        dashboard continues to display the star.  The error is logged via the
        notification channel.
        """
        summary = self._summarise_layout_config(event.config)
        # Keep the unsaved indicator since saving did not succeed
        self.dashboard.update_layout_config(summary, unsaved=event.config.dirty)
        err_message = str(event.error)
        self.notification_channel.notify(
            day=self.season_tracker.current_day,
            message=f"Failed to save hex layout: {err_message}",
            payload=summary,
        )

    # ------------------------------------------------------------------
    def on_shutdown(self) -> None:
        """Automatically persist unsaved layout changes on application exit.

        When the application is closing, attempt to save the current hex layout
        configuration if it has been modified since the last save.  A success
        or failure notification is sent to the notification channel.  This
        prevents users from accidentally losing their layout customisations.
        """
        # Attempt to access the hex canvas configuration.  If saving fails we
        # still want to raise a notification so the user knows their changes
        # weren't persisted.
        cfg: HexLayoutConfig | None = None
        try:
            cfg = getattr(self.map_view, "cfg", None)
        except Exception:
            cfg = None
        if cfg is not None and cfg.dirty:
            summary = self._summarise_layout_config(cfg)
            try:
                cfg.save()
                self.notification_channel.notify(
                    day=self.season_tracker.current_day,
                    message="Hex layout auto‑saved on exit",
                    payload=summary,
                )
            except Exception as error:
                err_message = str(error)
                self.notification_channel.notify(
                    day=self.season_tracker.current_day,
                    message=f"Auto‑save of hex layout failed: {err_message}",
                    payload=summary,
                )

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