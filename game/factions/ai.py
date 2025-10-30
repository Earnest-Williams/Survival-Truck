"""Faction AI operating on DataFrame-backed state."""

from __future__ import annotations

import math
from collections.abc import Hashable, Iterable, Mapping, Sequence
from typing import TypeAlias, TypedDict, cast

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


CoordLike: TypeAlias = HexCoord | Mapping[str, int | str] | Sequence[int | str] | str
SiteCollectionInput = Mapping[str, Site] | Iterable[Site]
SitePositionPayload = Mapping[str, CoordLike]
SiteConnectionsPayload = Mapping[str, Sequence[str | int]]
TerrainCostPayload = Mapping[Hashable, float | int | str]


class FactionAIController:
    """Coordinates AI decision making for NPC factions."""

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
            self.rng = randomness.generator("faction-ai")
        else:
            self.rng = rng or default_rng()
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
        destination = self.rng.choice(viable_targets)
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
        for faction_a, faction_b in hostile_pairs:
            attacker = self._select_caravan_from_faction(caravans, faction_a)
            defender = self._select_caravan_from_faction(caravans, faction_b)
            if attacker is None or defender is None:
                continue
            if float(self.rng.random()) < 0.5:
                attacker, defender = defender, attacker
                faction_a, faction_b = faction_b, faction_a
            lost_value = defender.unload_all_cargo()
            losses[faction_b] = losses.get(faction_b, 0) + lost_value + 1
            self.diplomacy.adjust_standing(faction_a, faction_b, -3.0)
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
        return self.rng.choice(candidates)

    def _coerce_coord(self, value: CoordLike) -> HexCoord | None:
        if isinstance(value, HexCoord):
            return value
        if isinstance(value, Mapping):
            q = value.get("q")
            r = value.get("r")
            try:
                return HexCoord(int(q), int(r))
            except (TypeError, ValueError):
                return None
        if isinstance(value, Sequence) and len(value) == 2:
            try:
                return HexCoord(int(value[0]), int(value[1]))
            except (TypeError, ValueError):
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


__all__ = ["FactionAIController"]
