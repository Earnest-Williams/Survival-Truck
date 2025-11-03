"""Faction AI operating on DataFrame-backed state.

This local copy mirrors the upstream AI controller while adding hooks for
generating faction missions. Missions are requests issued by non-player
factions that the player can choose to complete for reputation or
resource rewards. They are stored in the world state under the
``"missions"`` key as simple dictionaries.  The mission generation is
seeded from the world randomness generator so that missions are
deterministic relative to the world seed.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Iterable, Mapping, Sequence
from typing import TypedDict, cast

import networkx as nx
import polars as pl
from numpy.random import Generator, default_rng

from ..world.graph import (
    allied_factions,
    build_site_movement_graph,
    hostile_factions,
    relationship,
    shortest_path_between_sites,
)
from ..world.map import HexCoord
from ..world.rng import WorldRandomness
from ..world.sites import Site
from ..world.stateframes import SiteStateFrame
from . import FactionDiplomacy
from .state import CaravanRecord, FactionLedger, FactionRecord


class SitePositionRecord(TypedDict, total=False):
    q: int | str
    r: int | str


# NOTE: Python <3.12 does not support the ``type`` alias syntax. Replace it
# with a standard assignment for forward compatibility.
CoordLike = HexCoord | Mapping[str, int | str] | Sequence[int | str] | str
SiteCollectionInput = Mapping[str, Site] | Iterable[Site]
SitePositionPayload = Mapping[str, CoordLike]
SiteConnectionsPayload = Mapping[str, Sequence[str | int]]
TerrainCostPayload = Mapping[Hashable, float | int | str]


class FactionAIController:
    """Coordinates AI decision making for NPC factions.

    In addition to the original patrol/trade/raid cycle, this
    implementation periodically generates missions for the player. The
    probability of issuing a mission is intentionally low to avoid
    overwhelming the player. Missions are deterministic given the
    world's seed and day number.
    """

    def __init__(
        self,
        factions: Iterable[Mapping[str, object]] | None = None,
        *,
        diplomacy: FactionDiplomacy | None = None,
        movement_graph: nx.Graph | None = None,
        rng: Generator | None = None,
        randomness: WorldRandomness | None = None,
    ) -> None:
        self.ledger = FactionLedger.from_payload(factions)
        self.diplomacy = diplomacy or FactionDiplomacy()
        self._movement_graph: nx.Graph | None = movement_graph
        self._diplomacy_graph: nx.Graph | None = None
        if randomness is not None:
            # Use a dedicated generator for AI and missions to ensure
            # reproducible sequences across runs.
            self.rng = randomness.generator("faction-ai")
            self._mission_rng = randomness.generator("faction-missions")
        else:
            base_rng = rng or default_rng()
            self.rng = base_rng
            # Use a separate generator for mission generation when no
            # world randomness is provided.
            self._mission_rng = base_rng
        self._current_sites: dict[str, Site] = {}
        self._pending_movements: dict[str, list[CaravanRecord]] = {}
        self._state_path: list[str] = []

        self._state_transitions = pl.DataFrame(
            [
                {
                    "trigger": "advance_patrol",
                    "source": "patrol",
                    "target": "trade",
                    "handler": "_state_patrol",
                    "follow": "",
                    "record": True,
                },
                {
                    "trigger": "fallback_patrol",
                    "source": "trade",
                    "target": "patrol",
                    "handler": "_state_trade",
                    "follow": "",
                    "record": True,
                },
                {
                    "trigger": "process_trade",
                    "source": "trade",
                    "target": "raid",
                    "handler": "_state_trade",
                    "follow": "",
                    "record": True,
                },
                {
                    "trigger": "deescalate_trade",
                    "source": "raid",
                    "target": "trade",
                    "handler": "_state_raid",
                    "follow": "",
                    "record": True,
                },
                {
                    "trigger": "engage_raid",
                    "source": "raid",
                    "target": "consolidate",
                    "handler": "_state_raid",
                    "follow": "stabilize_consolidate",
                    "record": True,
                },
                {
                    "trigger": "stabilize_consolidate",
                    "source": "consolidate",
                    "target": "alliance",
                    "handler": "_state_consolidate",
                    "follow": "",
                    "record": False,
                },
                {
                    "trigger": "cool_alliance",
                    "source": "alliance",
                    "target": "consolidate",
                    "handler": "_state_alliance",
                    "follow": "",
                    "record": True,
                },
                {
                    "trigger": "refresh_alliance",
                    "source": "alliance",
                    "target": "patrol",
                    "handler": "_state_alliance",
                    "follow": "",
                    "record": True,
                },
            ],
            schema={
                "trigger": pl.String,
                "source": pl.String,
                "target": pl.String,
                "handler": pl.String,
                "follow": pl.String,
                "record": pl.Boolean,
            },
        )
        self._state_df = pl.DataFrame({"state": ["patrol"]})
        self._suppress_state_record = False

    # ------------------------------------------------------------------
    @property
    def factions(self) -> Mapping[str, FactionRecord]:
        return {record.name: record for record in self.ledger.iterate_factions()}

    @property
    def state_path(self) -> Sequence[str]:
        return tuple(self._state_path)

    @property
    def state(self) -> str:
        return cast(str, self._state_df.get_column("state")[0])

    def get_or_create_faction(self, name: str) -> FactionRecord:
        return self.ledger.faction_record(name)

    def set_movement_graph(self, graph: nx.Graph | None) -> None:
        self._movement_graph = graph

    # ------------------------------------------------------------------
    def run_turn(self, *, world_state: Mapping[str, object], day: int) -> None:
        raw_sites = cast(SiteCollectionInput | None, world_state.get("sites"))
        sites = self._extract_sites(raw_sites)
        self._movement_graph = self._refresh_movement_graph(world_state, sites)
        self._diplomacy_graph = self.diplomacy.as_graph(self.factions.keys())

        self._current_sites = sites
        self._pending_movements = {}
        self._state_path.clear()

        self.advance_patrol()
        self.process_trade()
        self.engage_raid()
        self.stabilize_consolidate()
        self.refresh_alliance()

        # After completing all state transitions, give factions an opportunity
        # to issue missions to the player. Missions are stored in the
        # provided world_state under the key "missions". The day number
        # ensures that mission expiry times are meaningful relative to game
        # progression.
        try:
            self._generate_missions(world_state, day)
        except Exception:
            # Swallow mission generation errors; AI behaviour should
            # continue even if mission generation fails.
            pass

        # Also generate diplomatic negotiations (truces, tribute, aid) based on
        # the player's standing and reputation. These negotiations are stored
        # under the "negotiations" key in the world state. The format of
        # negotiations is similar to missions: a list of mapping objects
        # describing each proposal. No effects are applied automatically; it
        # is up to the game UI to present the negotiation and update the
        # standing/reputation based on the player's choice.
        try:
            self._generate_negotiations(world_state, day)
        except Exception:
            pass

        # Apply ideological drift to faction standings. Factions with
        # differing ideologies gradually become more hostile, while those
        # sharing an ideology grow slightly friendlier. This is a small
        # incremental adjustment to the standing matrix and is intended to
        # operate alongside the daily decay. The magnitude is small to
        # prevent sudden swings.
        try:
            self._apply_ideological_drift()
        except Exception:
            pass

        # After drift, allow factions to shift their ideology based on
        # strong positive relations.  This influence step examines
        # standings between factions and may cause one faction to adopt
        # another's ideology if the accumulated goodwill is sufficiently
        # high.  We wrap this in a try/except to prevent failures from
        # disrupting the AI loop.
        try:
            self._apply_ideological_influence()
        except Exception:
            pass

        # After adjusting ideology drift, check whether any factions are
        # experiencing severe stress (e.g. depleted wealth and significant
        # losses). Such stress can cause a faction to fragment into a
        # splinter group with the same ideology. Splinter factions inherit
        # half of the parent's resources and preferences. We perform this
        # check once per turn so splits do not occur repeatedly in a single
        # day.
        try:
            self._check_for_schisms(day=day)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _record_state(self, state: str) -> None:
        if not self._suppress_state_record:
            self._state_path.append(state)

    def _set_state(self, state: str) -> None:
        self._state_df = self._state_df.with_columns(pl.lit(str(state)).alias("state"))

    def _apply_transition(self, trigger: str) -> None:
        matches = self._state_transitions.filter(
            (pl.col("trigger") == trigger) & (pl.col("source") == self.state)
        )
        if matches.is_empty():
            return
        row = matches.row(0, named=True)
        handler_name = cast(str, row.get("handler", ""))
        record_state = bool(row.get("record", True))
        follow_up = cast(str, row.get("follow", ""))
        if handler_name:
            handler = getattr(self, handler_name, None)
            if callable(handler):
                original = self._suppress_state_record
                if not record_state:
                    self._suppress_state_record = True
                try:
                    handler()
                finally:
                    self._suppress_state_record = original
        self._set_state(cast(str, row["target"]))
        if follow_up:
            self._apply_transition(follow_up)

    def advance_patrol(self) -> None:
        self._apply_transition("advance_patrol")

    def fallback_patrol(self) -> None:
        self._apply_transition("fallback_patrol")

    def process_trade(self) -> None:
        self._apply_transition("process_trade")

    def deescalate_trade(self) -> None:
        self._apply_transition("deescalate_trade")

    def engage_raid(self) -> None:
        self._apply_transition("engage_raid")

    def stabilize_consolidate(self) -> None:
        self._apply_transition("stabilize_consolidate")

    def cool_alliance(self) -> None:
        self._apply_transition("cool_alliance")

    def refresh_alliance(self) -> None:
        self._apply_transition("refresh_alliance")

    def _state_patrol(self) -> None:
        self._record_state("patrol")
        sites = self._current_sites
        self._sync_known_sites(sites)
        self._pending_movements = self._advance_caravans(sites)

    def _state_trade(self) -> None:
        self._record_state("trade")
        self._handle_trade(self._pending_movements, self._current_sites)

    def _state_raid(self) -> None:
        self._record_state("raid")
        self._resolve_conflicts(self._current_sites)

    def _state_consolidate(self) -> None:
        self._record_state("consolidate")
        self._rebuild_after_losses()

    def _state_alliance(self) -> None:
        self._record_state("alliance")

    # ------------------------------------------------------------------
    def _rebuild_after_losses(self) -> None:
        for faction in self.ledger.iterate_factions():
            losses = faction.resource_amount("losses", 0.0)
            if losses >= 0:
                continue
            wealth = faction.resource_amount("wealth", 0.0)
            if wealth <= 0:
                continue
            recoverable = min(wealth // 2, abs(losses))
            if recoverable <= 0:
                continue
            faction.adjust_resource("wealth", -recoverable)
            faction.adjust_resource("losses", recoverable)

    # ------------------------------------------------------------------
    def _extract_sites(self, raw_sites: SiteCollectionInput | None) -> dict[str, Site]:
        if raw_sites is None:
            return {}
        if isinstance(raw_sites, SiteStateFrame):
            return raw_sites.as_mapping()
        if isinstance(raw_sites, Mapping):
            result: dict[str, Site] = {}
            for key, value in raw_sites.items():
                if isinstance(value, Site):
                    result[str(key)] = value
            return result
        if isinstance(raw_sites, Iterable):
            result = {}
            for value in raw_sites:
                if isinstance(value, Site):
                    result[value.identifier] = value
            return result
        return {}

    def _extract_site_positions(self, payload: SitePositionPayload | None) -> dict[str, HexCoord]:
        positions: dict[str, HexCoord] = {}
        if not isinstance(payload, Mapping):
            return positions
        for key, value in payload.items():
            coord = self._coerce_coord(value)
            if coord is None:
                continue
            positions[str(key)] = coord
        return positions

    def _extract_site_connections(
        self, payload: SiteConnectionsPayload | None
    ) -> dict[str, list[str]]:
        connections: dict[str, list[str]] = {}
        if not isinstance(payload, Mapping):
            return connections
        for key, value in payload.items():
            if isinstance(value, Sequence):
                connections[str(key)] = [str(item) for item in value]
        return connections

    def _extract_terrain_costs(self, payload: TerrainCostPayload | None) -> dict[Hashable, float]:
        costs: dict[Hashable, float] = {}
        if not isinstance(payload, Mapping):
            return costs
        for key, value in payload.items():
            try:
                costs[key] = float(value)
            except (TypeError, ValueError):
                continue
        return costs

    def _refresh_movement_graph(
        self, world_state: Mapping[str, object], sites: Mapping[str, Site]
    ) -> nx.Graph | None:
        positions = self._extract_site_positions(
            cast(SitePositionPayload | None, world_state.get("site_positions"))
        )
        if not positions:
            return self._movement_graph
        connections = self._extract_site_connections(
            cast(SiteConnectionsPayload | None, world_state.get("site_connections"))
        )
        terrain_costs = self._extract_terrain_costs(
            cast(TerrainCostPayload | None, world_state.get("terrain_costs"))
        )
        graph = build_site_movement_graph(
            positions,
            connections=connections if connections else None,
            terrain_costs=terrain_costs if terrain_costs else None,
        )
        for site_id in sites:
            if site_id not in graph:
                graph.add_node(site_id)
        return graph

    def _sync_known_sites(self, sites: Mapping[str, Site]) -> None:
        if not sites:
            return
        for faction in self.ledger.iterate_factions():
            for site_id in sites:
                faction.add_known_site(site_id)
            for caravan in faction.caravans.values():
                if caravan.location in sites:
                    faction.add_known_site(caravan.location)

    def _advance_caravans(self, sites: Mapping[str, Site]) -> dict[str, list[CaravanRecord]]:
        visits: dict[str, list[CaravanRecord]] = {}
        for faction in self.ledger.iterate_factions():
            for caravan in faction.caravans.values():
                if not caravan.route:
                    self._plan_route_for_caravan(faction, caravan, sites)
                destination = caravan.advance_day()
                if destination:
                    visits.setdefault(destination, []).append(caravan)
                    self._schedule_next_leg(caravan)
        return visits

    def _plan_route_for_caravan(
        self, faction: FactionRecord, caravan: CaravanRecord, sites: Mapping[str, Site]
    ) -> None:
        if not faction.known_sites:
            return
        hostiles = set()
        if self._diplomacy_graph is not None:
            hostiles.update(hostile_factions(self._diplomacy_graph, faction.name))
        viable_targets: list[str] = []
        for site_id in faction.known_sites:
            if site_id == caravan.location:
                continue
            if self._movement_graph is not None and site_id not in self._movement_graph:
                continue
            site = sites.get(site_id)
            if site and site.controlling_faction and site.controlling_faction in hostiles:
                continue
            viable_targets.append(site_id)
        if not viable_targets:
            viable_targets = list(faction.known_sites)
        if not viable_targets:
            return
        # Ideological preference: select sites whose type matches the
        # faction's ideology. If there are any preferred targets, choose
        # among them; otherwise fall back to any viable target. This
        # encourages caravans to visit sites aligned with their faction's
        # worldview (e.g. militaristic factions favour military ruins).
        preferred_targets: list[str] = []
        try:
            ideology = getattr(faction, "ideology", "neutral")
            # Map ideology to preferred site types
            if ideology == "militaristic":
                pref_types = {"military_ruins", "outpost", "power_plant"}
            elif ideology == "technocratic":
                pref_types = {"power_plant", "city", "outpost"}
            elif ideology == "tribalist":
                pref_types = {"farm", "camp", "outpost"}
            elif ideology == "mercantile":
                # Merchants gravitate toward markets and trade hubs
                pref_types = {"city", "outpost", "camp"}
            elif ideology == "religious":
                # Religious factions favour rural and camp-like sites
                pref_types = {"camp", "farm", "outpost"}
            elif ideology == "scientific":
                # Scientific factions head to ruins and research facilities
                pref_types = {"military_ruins", "power_plant", "city"}
            elif ideology == "nomadic":
                # Nomadic factions prefer mobility hubs and open camps
                pref_types = {"camp", "outpost", "farm"}
            else:
                pref_types = set()
            for site_id in viable_targets:
                site = sites.get(site_id)
                # Some Site objects expose their type as ``site.site_type``
                # (enum) or ``site.site_type.value``. We attempt both.
                stype: str | None = None
                if site is not None:
                    try:
                        stype = getattr(site, "site_type", None)
                        # If site_type is an Enum, take its value
                        if hasattr(stype, "value"):
                            stype_val = str(getattr(stype, "value"))
                        else:
                            stype_val = str(stype) if stype is not None else None
                    except Exception:
                        stype_val = None
                    if stype_val and stype_val in pref_types:
                        preferred_targets.append(site_id)
        except Exception:
            preferred_targets = []
        target_pool = preferred_targets if preferred_targets else viable_targets
        destination = self.rng.choice(target_pool)
        route = self._compute_route(caravan.location, destination)
        caravan.plan_route(route)
        if len(route) > 1:
            edge_cost = self._edge_travel_time(route[0], route[1])
            caravan.schedule_next_leg(edge_cost)
        else:
            caravan.schedule_next_leg(0)

    def _compute_route(self, origin: str, destination: str) -> list[str]:
        if self._movement_graph is None:
            return [origin, destination]
        if origin not in self._movement_graph or destination not in self._movement_graph:
            return [origin, destination]
        try:
            path = shortest_path_between_sites(self._movement_graph, origin, destination)
        except nx.NetworkXNoPath:
            return [origin, destination]
        if not path:
            return [origin, destination]
        return path

    def _schedule_next_leg(self, caravan: CaravanRecord) -> None:
        if self._movement_graph is None:
            caravan.schedule_next_leg(0)
            return
        route = caravan.route
        if not route:
            caravan.schedule_next_leg(0)
            return
        next_stop = route[0]
        caravan.schedule_next_leg(self._edge_travel_time(caravan.location, next_stop))

    def _handle_trade(
        self, visits: Mapping[str, list[CaravanRecord]], sites: Mapping[str, Site]
    ) -> None:
        for site_id, caravans in visits.items():
            site = sites.get(site_id)
            controlling = site.controlling_faction if site else None
            for caravan in caravans:
                faction = self.factions.get(caravan.faction_name)
                trade_value = caravan.unload_all_cargo()
                if trade_value <= 0:
                    good = faction.preferred_trade_good() if faction else "supplies"
                    caravan.add_cargo(good, int(self.rng.integers(1, 3, endpoint=True)))
                    continue
                if faction is not None:
                    faction.adjust_resource("wealth", trade_value)
                if controlling and controlling != caravan.faction_name:
                    self.diplomacy.adjust_standing(caravan.faction_name, controlling, 2.0)
                elif controlling and self._diplomacy_graph is not None:
                    allies = allied_factions(self._diplomacy_graph, caravan.faction_name)
                    if controlling in allies:
                        self.diplomacy.adjust_standing(caravan.faction_name, controlling, 1.0)
                restock_type = faction.preferred_trade_good() if faction else "supplies"
                caravan.add_cargo(restock_type, max(1, trade_value // 2))

    def _resolve_conflicts(self, sites: Mapping[str, Site]) -> None:  # noqa: ARG002 - sites used for parity
        caravans_by_site: dict[str, list[CaravanRecord]] = {}
        for faction in self.ledger.iterate_factions():
            for caravan in faction.caravans.values():
                caravans_by_site.setdefault(caravan.location, []).append(caravan)
        for caravans in caravans_by_site.values():
            if len(caravans) < 2:
                continue
            hostile_pairs = self._identify_hostile_pairs(caravans)
            if not hostile_pairs:
                continue
            self._resolve_site_conflict(caravans, hostile_pairs)

    def _identify_hostile_pairs(self, caravans: Sequence[CaravanRecord]) -> list[tuple[str, str]]:
        involved = {caravan.faction_name for caravan in caravans}
        pairs: list[tuple[str, str]] = []
        for faction_a in involved:
            for faction_b in involved:
                if faction_a >= faction_b:
                    continue
                standing = self.diplomacy.get_standing(faction_a, faction_b)
                if self._diplomacy_graph is not None:
                    standing = relationship(self._diplomacy_graph, faction_a, faction_b)
                if standing <= -15.0:
                    pairs.append((faction_a, faction_b))
        return pairs

    def _resolve_site_conflict(
        self,
        caravans: Sequence[CaravanRecord],
        hostile_pairs: Sequence[tuple[str, str]],
    ) -> None:
        losses: dict[str, int] = {}
        for primary_faction, rival_faction in hostile_pairs:
            attacker = self._select_caravan_from_faction(caravans, primary_faction)
            defender = self._select_caravan_from_faction(caravans, rival_faction)
            if attacker is None or defender is None:
                continue
            attacker_name = primary_faction
            defender_name = rival_faction
            if float(self.rng.random()) < 0.5:
                attacker, defender = defender, attacker
                attacker_name, defender_name = defender_name, attacker_name
            lost_value = defender.unload_all_cargo()
            losses[defender_name] = losses.get(defender_name, 0) + lost_value + 1
            self.diplomacy.adjust_standing(attacker_name, defender_name, -3.0)
        for faction_name, loss in losses.items():
            faction = self.factions.get(faction_name)
            if faction is None:
                continue
            faction.adjust_resource("losses", -loss)

    def _select_caravan_from_faction(
        self, caravans: Sequence[CaravanRecord], faction_name: str
    ) -> CaravanRecord | None:
        candidates = [caravan for caravan in caravans if caravan.faction_name == faction_name]
        if not candidates:
            return None
        index = int(self.rng.integers(0, len(candidates)))
        return candidates[index]

    def _coerce_coord(self, value: CoordLike) -> HexCoord | None:  # noqa: PLR0911
        if isinstance(value, HexCoord):
            return value
        if isinstance(value, Mapping):
            q = value.get("q")
            r = value.get("r")
            if isinstance(q, int | str) and isinstance(r, int | str):
                try:
                    return HexCoord(int(q), int(r))
                except ValueError:
                    return None
            return None
        if isinstance(value, Sequence) and len(value) == 2:
            left, right = value[0], value[1]
            if isinstance(left, int | str) and isinstance(right, int | str):
                try:
                    return HexCoord(int(left), int(right))
                except ValueError:
                    return None
            return None
        if isinstance(value, str) and "," in value:
            left, right = value.split(",", 1)
            try:
                return HexCoord(int(left), int(right))
            except ValueError:
                return None
        return None

    def _edge_travel_time(self, origin: str, destination: str) -> int:
        if self._movement_graph is None:
            return 0
        data = self._movement_graph.get_edge_data(origin, destination) or {}
        weight = float(data.get("weight", 0.0))
        return max(0, math.ceil(weight) - 1)

    # ------------------------------------------------------------------
    def _generate_missions(self, world_state: Mapping[str, object], day: int) -> None:
        """Randomly generate missions for the player.

        For each faction there is a small chance per day (currently 5%) of
        creating a mission. The mission expiry is relative to the day
        number so that older missions naturally expire. Missions are
        deterministic for a given world seed because they draw from a
        dedicated random generator seeded from :class:`WorldRandomness`.

        The ``world_state`` dictionary will be updated in place. A list of
        missions is stored under the ``"missions"`` key, which the game
        layer can consume to present to the player. Each mission is a
        simple mapping containing at minimum: ``faction`` (the issuing
        faction), ``type`` (mission kind), ``description``, ``reward`` (an
        abstract numeric value), and ``expires`` (absolute day when the
        mission is no longer available).
        """
        # Ensure world_state is mutable
        if not isinstance(world_state, Mapping):
            return
        mission_list = list(world_state.get("missions", []))
        for faction in self.ledger.iterate_factions():
            # Skip unnamed factions
            if not faction.name:
                continue
            # 5% chance per day to issue a mission
            if float(self._mission_rng.random()) < 0.05:
                # For now we only implement a single escort mission type
                mission = {
                    "faction": faction.name,
                    "type": "escort_caravan",
                    "description": f"Escort a {faction.name} caravan safely between sites.",
                    # Reward is proportional to the faction's wealth preference; default 10
                    "reward": max(10.0, faction.preference_for("wealth", default=10.0)),
                    "expires": day + 7,  # expire in a week
                }
                mission_list.append(mission)
        # Deduplicate missions by identity (faction + type + expires)
        unique: list[dict[str, object]] = []
        seen: set[tuple[str, str, int]] = set()
        for mission in mission_list:
            fac = str(mission.get("faction", ""))
            typ = str(mission.get("type", ""))
            exp = int(mission.get("expires", day))
            key = (fac, typ, exp)
            if key in seen:
                continue
            seen.add(key)
            unique.append(mission)
        world_state["missions"] = unique

    def _generate_negotiations(self, world_state: Mapping[str, object], day: int) -> None:
        """Generate negotiation proposals based on faction sentiment.

        Negotiations are generated using the player's reputation with each
        faction. Factions with strongly negative reputations may offer
        truces or demand tribute; those with neutral or positive
        reputations may request aid or propose coalitions. Each proposal
        contains a ``type`` ("truce", "tribute", "aid", "coalition"), a
        description, optional resource demands or rewards, and an expiry
        day. These proposals are stored in the ``world_state`` under
        ``"negotiations"``. No effects are applied automatically—game
        systems must handle the player's choice and update diplomacy
        accordingly.
        """
        if not isinstance(world_state, Mapping):
            return
        negotiations = list(world_state.get("negotiations", []))
        # Collect types of ongoing world events.  These will influence negotiation
        # frequency and bias. We consider both persistent multi-day events in
        # ``active_events`` and one-off events generated this turn in ``events``.
        event_types: set[str] = set()
        raw_active_events = world_state.get("active_events")
        if isinstance(raw_active_events, Sequence):
            for ev in raw_active_events:
                try:
                    et = str(ev.get("type", ""))
                except Exception:
                    et = ""
                if et:
                    event_types.add(et)
        raw_events_list = world_state.get("events")
        if isinstance(raw_events_list, Sequence):
            for ev in raw_events_list:
                try:
                    et = str(ev.get("type", ""))
                except Exception:
                    et = ""
                if et:
                    event_types.add(et)

        # Before looping over factions, extract travel telemetry from the world state.
        # The travel cost system records the player's most recent movement in
        # ``world_state['last_travel_cost']``, capturing the load factor
        # (weight/power scaling) and travel modifier (seasonal * weather).  We
        # normalise these values to influence negotiation frequency and bias.
        load_factor: float = 1.0
        travel_modifier: float = 1.0
        try:
            last_travel: Mapping[str, object] | None = world_state.get("last_travel_cost")  # type: ignore[index]
            if isinstance(last_travel, Mapping):
                lf = last_travel.get("load_factor")
                if isinstance(lf, (int, float)):
                    load_factor = float(lf)
                tm = last_travel.get("modifier")
                # Some versions store travel modifier under 'modifier' or 'travel_modifier'
                if isinstance(tm, (int, float)):
                    travel_modifier = float(tm)
                else:
                    tm2 = last_travel.get("travel_modifier")
                    if isinstance(tm2, (int, float)):
                        travel_modifier = float(tm2)
        except Exception:
            # Fallback to defaults if keys are missing or malformed
            load_factor = 1.0
            travel_modifier = 1.0

        # Compute modifiers from load factor and travel modifier.  We cap
        # adjustments to avoid extreme behaviours.  A load factor > 1.0
        # increases the chance of negotiation (heavily laden players draw
        # attention), whereas a travel modifier > 1.0 (bad weather/season)
        # nudges factions to negotiate more frequently.  Each contributes
        # up to +50% to the base chance.
        load_chance_mod = 0.0
        if load_factor > 1.0:
            load_chance_mod = min((load_factor - 1.0) * 0.5, 0.5)
        travel_chance_mod = 0.0
        if travel_modifier > 1.0:
            travel_chance_mod = min((travel_modifier - 1.0) * 0.5, 0.5)

        for faction in self.ledger.iterate_factions():
            if not faction.name:
                continue
            rep = getattr(faction, "reputation", 0.0)
            # Retrieve the faction's ideology. Ideology influences both the
            # likelihood and the type of negotiation issued. If none is set,
            # "neutral" is returned.
            ideology = getattr(faction, "ideology", "neutral")
            # Fetch behavioural traits to further modulate negotiation likelihood
            try:
                aggressive = self.ledger.get_trait(faction.name, "aggressive", 0.0)
                cautious = self.ledger.get_trait(faction.name, "cautious", 0.0)
                greedy = self.ledger.get_trait(faction.name, "greedy", 0.0)
                benevolent = self.ledger.get_trait(faction.name, "benevolent", 0.0)
                expansionist = self.ledger.get_trait(faction.name, "expansionist", 0.0)
            except Exception:
                aggressive = cautious = greedy = benevolent = expansionist = 0.0
            # Determine the base chance for a negotiation event. Larger
            # magnitudes of reputation lead to higher probabilities.
            if rep <= -20.0:
                base_chance = 0.10  # very hostile: 10% chance
            elif rep <= -5.0:
                base_chance = 0.05  # slightly hostile: 5% chance
            elif rep >= 20.0:
                base_chance = 0.08  # very friendly: 8% chance
            elif rep >= 5.0:
                base_chance = 0.04  # slightly friendly: 4% chance
            else:
                base_chance = 0.02  # neutral: 2% chance
            # Modify base chance based on ideology. Militaristic factions
            # are more likely to propose negotiations in general, whereas
            # technocratic, tribalist, mercantile and religious factions are
            # slightly more reserved. These modifiers scale the probability.
            if ideology == "militaristic":
                base_chance *= 1.5
            elif ideology == "technocratic":
                base_chance *= 1.2
            elif ideology == "tribalist":
                base_chance *= 1.1
            elif ideology == "mercantile":
                base_chance *= 1.3
            elif ideology == "religious":
                base_chance *= 1.1
            elif ideology == "scientific":
                # Scientists are cautious diplomats
                base_chance *= 1.15
            elif ideology == "nomadic":
                # Nomads are less likely to engage in negotiations
                base_chance *= 0.9

            # Apply travel telemetry modifiers to the base chance.  Heavy
            # player loads and harsh travel conditions make factions more
            # eager to negotiate.  These adjustments are applied once per
            # faction at the start of processing.
            base_chance *= 1.0 + load_chance_mod
            base_chance *= 1.0 + travel_chance_mod

            # Modify base chance based on behavioural traits.  Aggressive and
            # expansionist factions negotiate more frequently, whereas
            # cautious factions do so less.  Greedy and benevolent traits
            # influence the content of proposals rather than frequency.
            base_chance *= 1.0 + 0.5 * aggressive  # up to +50%
            base_chance *= 1.0 - 0.5 * cautious    # up to -50%
            base_chance *= 1.0 + 0.3 * expansionist  # up to +30%
            # Bump negotiation frequency if there are any world events occurring. A
            # turbulent world prompts factions to seek more diplomatic solutions. We
            # increase the base chance by 20% when any events are present. Specific
            # event types further modify the chance: pandemics add +10%, storms
            # +5%. These are multiplicative adjustments.
            if event_types:
                base_chance *= 1.2
                if "pandemic" in event_types:
                    base_chance *= 1.1
                if "storm" in event_types:
                    base_chance *= 1.05
            # Draw random; skip negotiation if not selected.
            if float(self._mission_rng.random()) >= base_chance:
                continue
            # Choose negotiation type based on reputation sign
            if rep < -5.0:
                # Negative reputation: primarily truce or tribute demand. Militaristic
                # factions favour tribute, technocratic factions prefer truce,
                # tribalist factions split evenly.
                bias = float(self._mission_rng.random())
                if ideology == "militaristic":
                    threshold = 0.7
                elif ideology == "technocratic":
                    threshold = 0.3
                elif ideology == "mercantile":
                    # Merchants lean slightly towards demanding tribute when relations
                    # are bad, but not as strongly as militarists
                    threshold = 0.6
                elif ideology == "religious":
                    # Religious factions are more likely to propose truces
                    threshold = 0.4
                elif ideology == "scientific":
                    # Scientific factions prefer truces to preserve resources
                    threshold = 0.3
                elif ideology == "nomadic":
                    # Nomadic factions tend to avoid tribute demands
                    threshold = 0.5
                else:
                    # Tribalists and neutral factions split evenly
                    threshold = 0.5

                # Adjust threshold based on behavioural traits.  Greedy or
                # aggressive factions are more likely to demand tribute, so
                # increase the threshold; benevolent or cautious factions
                # lean towards truce, so decrease it.
                threshold += 0.2 * greedy + 0.2 * aggressive
                threshold -= 0.2 * benevolent + 0.1 * cautious
                # Event-specific modifications: a pandemic makes factions
                # desperate and thus more likely to demand tribute (+0.1),
                # whereas a storm encourages truces (-0.1). These shifts
                # adjust the bias before clamping.
                if "pandemic" in event_types:
                    threshold += 0.1
                if "storm" in event_types:
                    threshold -= 0.1
                # Travel telemetry influence: when the player is heavily
                # laden, factions are more inclined to demand tribute; when
                # travel conditions are poor (high travel modifier), they
                # prefer truces to preserve resources.
                threshold += 0.15 * load_chance_mod
                threshold -= 0.15 * travel_chance_mod
                threshold = min(max(threshold, 0.0), 1.0)
                if bias < threshold:
                    n_type = "tribute"
                    amount = max(10.0, abs(rep))
                    desc = (
                        f"{faction.name} demands tribute of {amount:.0f} units of supplies for safe passage."
                    )
                    payload = {"demand": amount, "reward": 0.0}
                else:
                    n_type = "truce"
                    desc = f"{faction.name} proposes a truce to cease hostilities."
                    payload = {"reward": 0.0, "demand": 0.0}
            elif rep > 5.0:
                # Positive reputation: aid requests or coalition invites. Technocratic
                # factions bias towards aid; militaristic bias towards coalition.
                bias = float(self._mission_rng.random())
                if ideology == "technocratic":
                    threshold = 0.7
                elif ideology == "militaristic":
                    threshold = 0.3
                elif ideology == "mercantile":
                    # Merchants slightly favour aid to increase trade
                    threshold = 0.6
                elif ideology == "religious":
                    # Religious factions lean towards coalitions (e.g. holy wars)
                    threshold = 0.4
                elif ideology == "scientific":
                    # Scientific factions prefer aid (to share knowledge) over coalitions
                    threshold = 0.8
                elif ideology == "nomadic":
                    # Nomadic factions rarely form coalitions; prefer aid
                    threshold = 0.7
                else:
                    threshold = 0.5

                # Adjust threshold based on behavioural traits.  Benevolent
                # factions tilt towards aid; greedy or aggressive factions
                # tilt towards coalition to gain advantage.  Expansionist
                # factions prefer coalition as well.  Cautious factions
                # prefer aid.
                threshold -= 0.2 * benevolent + 0.1 * cautious
                threshold += 0.2 * greedy + 0.2 * aggressive + 0.3 * expansionist
                # Event-specific adjustments: during a pandemic factions are
                # more likely to seek aid (+0.15), whereas storms encourage
                # coalitions (-0.15).
                if "pandemic" in event_types:
                    threshold += 0.15
                if "storm" in event_types:
                    threshold -= 0.15
                # Travel telemetry influence: poor travel conditions make aid
                # requests more appealing, while a heavily loaded player
                # encourages factions to form coalitions to share risks and
                # rewards. Adjust the threshold accordingly.
                threshold -= 0.15 * load_chance_mod
                threshold += 0.15 * travel_chance_mod
                threshold = min(max(threshold, 0.0), 1.0)
                if bias < threshold:
                    n_type = "aid"
                    amount = max(5.0, rep / 2)
                    desc = (
                        f"{faction.name} requests aid of {amount:.0f} units of supplies to support a common cause."
                    )
                    payload = {"demand": amount, "reward": 0.0}
                else:
                    n_type = "coalition"
                    reward = max(10.0, rep)
                    desc = (
                        f"{faction.name} invites you to join a coalition against a common enemy, offering {reward:.0f} reputation reward."
                    )
                    payload = {"reward": reward, "demand": 0.0}
            else:
                # Neutral reputation: minor tribute or aid. Use ideology to
                # nudge preference. Militaristic biases to tribute, technocratic to aid.
                bias = float(self._mission_rng.random())
                if ideology == "militaristic":
                    threshold = 0.7
                elif ideology == "technocratic":
                    threshold = 0.3
                elif ideology == "mercantile":
                    threshold = 0.5
                elif ideology == "religious":
                    # Religious factions tilt towards aid (share resources)
                    threshold = 0.4
                elif ideology == "scientific":
                    # Scientists lean towards aid
                    threshold = 0.6
                elif ideology == "nomadic":
                    # Nomadic factions have no strong preference between tribute and aid
                    threshold = 0.5
                else:
                    threshold = 0.5

                # Adjust threshold based on behavioural traits similar to
                # neutral case: greedy or aggressive factions lean towards
                # tribute; benevolent factions lean towards aid; cautious
                # factions slightly favour aid; expansionist factions
                # slightly favour tribute as preparation for dominance.
                threshold += 0.2 * greedy + 0.2 * aggressive + 0.1 * expansionist
                threshold -= 0.2 * benevolent + 0.1 * cautious
                # Travel telemetry influence: a heavy load pushes factions
                # towards tribute, while difficult travel encourages aid.
                threshold += 0.15 * load_chance_mod
                threshold -= 0.15 * travel_chance_mod
                threshold = min(max(threshold, 0.0), 1.0)
                if bias < threshold:
                    n_type = "tribute"
                    amount = 10.0
                    desc = f"{faction.name} demands a minor tribute of 10 units of supplies."
                    payload = {"demand": amount, "reward": 0.0}
                else:
                    n_type = "aid"
                    amount = 10.0
                    desc = f"{faction.name} requests minor aid of 10 units of supplies."
                    payload = {"demand": amount, "reward": 0.0}
            negotiations.append(
                {
                    "faction": faction.name,
                    "type": n_type,
                    "description": desc,
                    "expires": day + 5,
                    **payload,
                }
            )
        # Deduplicate negotiations
        unique_negotiations: list[dict[str, object]] = []
        seen_keys: set[tuple[str, str, int]] = set()
        for n in negotiations:
            key = (
                str(n.get("faction", "")),
                str(n.get("type", "")),
                int(n.get("expires", day)),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            unique_negotiations.append(n)
        world_state["negotiations"] = unique_negotiations

    # ------------------------------------------------------------------
    def _apply_ideological_drift(self) -> None:
        """Adjust inter-faction standings based on ideological alignment.

        Factions sharing the same ideology become slightly more amicable over
        time, whereas factions with differing ideologies drift apart. The
        adjustment is small to avoid overpowering other diplomatic events.
        """
        # Build a list of faction records for easier iteration.
        factions = list(self.ledger.iterate_factions())
        count = len(factions)
        if count < 2:
            return
        for i in range(count):
            fa = factions[i]
            for j in range(i + 1, count):
                fb = factions[j]
                if fa.ideology == fb.ideology:
                    delta = 0.1
                else:
                    delta = -0.1
                # Use adjust_standing on the diplomacy matrix. The call is
                # symmetric and ensures the updated standing remains within
                # min/max bounds defined by FactionDiplomacy.
                try:
                    self.diplomacy.adjust_standing(fa.name, fb.name, delta)
                except Exception:
                    continue

    # ------------------------------------------------------------------
    def _apply_ideological_influence(self) -> None:
        """Allow factions to adopt a new ideology based on positive relations.

        After adjusting standings via ideological drift, factions may be
        swayed by close allies or trading partners.  For each faction,
        we accumulate positive standing values from all other factions
        grouped by their ideologies.  If a different ideology exerts
        substantial influence, the faction has a chance to adopt that
        ideology.  The probability of adoption increases with the
        summed standing of influencing factions.  Only positive
        standings contribute; hostile relations do not encourage
        ideological alignment.

        This process is intentionally conservative to prevent
        excessive churn: adoption chances are capped at 10%, and the
        current ideology is retained unless another ideology has a
        strictly higher influence score.
        """
        # Build a list of faction records to avoid repeated iteration.
        factions = list(self.ledger.iterate_factions())
        # If fewer than two factions exist, nothing to influence.
        if len(factions) < 2:
            return
        for fa in factions:
            # Skip unnamed factions
            if not fa.name:
                continue
            current_ideology = fa.ideology
            # Gather influence scores by ideology
            influence: dict[str, float] = {}
            for fb in factions:
                if fa.name == fb.name:
                    continue
                other_ideology = fb.ideology
                if not other_ideology:
                    continue
                try:
                    standing = self.diplomacy.get_standing(fa.name, fb.name)
                except Exception:
                    standing = 0.0
                # Only consider positive relations
                if standing <= 0.0:
                    continue
                influence[other_ideology] = influence.get(other_ideology, 0.0) + float(standing)
            # No positive influences means no shift
            if not influence:
                continue
            # Determine the ideology with the highest influence
            best_ideology, best_score = max(influence.items(), key=lambda item: item[1])
            # Do not change if the current ideology already has the highest influence
            # (ties implicitly favour the current ideology)
            # Move the faction's ideology weights toward the best ideology.
            # The amount of adjustment is proportional to the influence
            # score relative to a maximum of 100.  A score of 100 moves
            # 10% of the distance toward the target ideology in a single
            # step.  This creates a smooth ideological spectrum rather
            # than an abrupt switch.
            # If the current ideology already has the highest influence,
            # weights remain unchanged.  Otherwise we adjust the weights.
            delta = min(0.1, best_score / 100.0)
            if delta > 0:
                try:
                    self.ledger.adjust_ideology_weight(fa.name, best_ideology, delta)
                except Exception:
                    continue

    # ------------------------------------------------------------------
    def _check_for_schisms(self, *, day: int) -> None:
        """Identify factions under severe stress and split them.

        A faction is considered stressed if its wealth is very low and its
        recorded losses are high. When such conditions are met, the faction
        is duplicated into a new splinter faction. The parent faction and
        the splinter faction will share resources and preferences evenly and
        start with a positive standing between them. The splinter faction
        inherits the parent's ideology.

        Args:
            day: The current day number, used to ensure unique faction names.
        """
        for faction in list(self.ledger.iterate_factions()):
            try:
                wealth = faction.resource_amount("wealth", 0.0)
                # Losses are stored as negative numbers when damage has been
                # sustained (see ``_rebuild_after_losses``). We use the
                # absolute value for our stress check.
                losses = abs(faction.resource_amount("losses", 0.0))
                # Define stress thresholds. When wealth is depleted and losses
                # are substantial, we trigger a schism.
                if wealth > 5.0 or losses < 10.0:
                    continue
                # Create a unique name for the splinter faction.
                new_name = f"{faction.name}-splinter-{day}"
                # Ensure the new faction does not already exist.
                if new_name in self.factions:
                    continue
                # Register the new faction in the ledger.
                new_faction = self.ledger.faction_record(new_name)
                # Assign the same ideology to the splinter group.
                new_faction_ideology = faction.ideology
                self.ledger.set_ideology(new_name, new_faction_ideology)
                # Copy resource preferences from the parent.
                parent_prefs = self.ledger._preferences.filter(pl.col("faction") == faction.name)
                for row in parent_prefs.iter_rows(named=True):
                    key = row["key"]
                    weight = float(row["weight"])
                    self.ledger.set_resource_preference(new_name, key, weight)
                # Split resources evenly between parent and splinter. We do not
                # split losses to avoid negative values on the splinter.
                parent_resources = self.ledger._resources.filter(pl.col("faction") == faction.name)
                for row in parent_resources.iter_rows(named=True):
                    res = row["resource"]
                    amt = float(row["amount"])
                    if res == "losses":
                        continue
                    half = amt * 0.5
                    # Assign half to the splinter and keep half on the parent.
                    self.ledger.adjust_resource(new_name, res, half)
                    self.ledger.adjust_resource(faction.name, res, -half)
                # Share known sites with the splinter.
                for site_id in faction.known_sites:
                    self.ledger.add_known_site(new_name, site_id)
                # Set a positive standing between parent and splinter due to
                # shared origins. This will decay over time but starts high.
                self.diplomacy.set_standing(faction.name, new_name, 20.0)
            except Exception:
                # Ignore individual split failures.
                continue


__all__ = ["FactionAIController"]