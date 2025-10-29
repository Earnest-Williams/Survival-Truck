"""AI controllers for factions leveraging movement and diplomacy graphs."""

from __future__ import annotations

import math
import random
from typing import Dict, Iterable, List, Mapping, Sequence

import networkx as nx
from transitions import Machine

from ..world.graph import (
    allied_factions,
    build_site_movement_graph,
    hostile_factions,
    relationship,
    shortest_path_between_sites,
)
from ..world.map import HexCoord
from ..world.sites import Site
from . import Caravan, Faction, FactionDiplomacy


class FactionAIController:
    """Coordinates AI decision making for NPC factions."""

    def __init__(
        self,
        factions: Iterable[Faction] | None = None,
        *,
        diplomacy: FactionDiplomacy | None = None,
        movement_graph: nx.Graph | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._factions: Dict[str, Faction] = {faction.name: faction for faction in (factions or [])}
        self.diplomacy = diplomacy or FactionDiplomacy()
        self._movement_graph: nx.Graph | None = movement_graph
        self._diplomacy_graph: nx.Graph | None = None
        self.rng = rng or random.Random()
        self._current_sites: Mapping[str, Site] = {}
        self._pending_movements: Dict[str, List[Caravan]] = {}
        self._state_path: List[str] = []

        self._fsm = Machine(
            model=self,
            states=["patrol", "trade", "raid", "alliance"],
            initial="patrol",
            auto_transitions=False,
        )
        self._fsm.add_transition(
            "advance_patrol", "patrol", "trade", before="_state_patrol"
        )
        self._fsm.add_transition(
            "process_trade", "trade", "raid", before="_state_trade"
        )
        self._fsm.add_transition(
            "engage_raid", "raid", "alliance", before="_state_raid"
        )
        self._fsm.add_transition(
            "refresh_alliance", "alliance", "patrol", before="_state_alliance"
        )

    @property
    def factions(self) -> Mapping[str, Faction]:
        return self._factions

    @property
    def state_path(self) -> Sequence[str]:
        """Return the last executed state path for debugging/tests."""

        return tuple(self._state_path)

    def get_or_create_faction(self, name: str) -> Faction:
        if name not in self._factions:
            self._factions[name] = Faction(name=name)
        return self._factions[name]

    def set_movement_graph(self, graph: nx.Graph | None) -> None:
        """Assign the graph used for planning overland travel."""

        self._movement_graph = graph

    def run_turn(self, *, world_state: Mapping[str, object], day: int) -> None:
        """Execute faction behaviours for the current day."""

        sites = self._extract_sites(world_state.get("sites"))
        self._movement_graph = self._refresh_movement_graph(world_state, sites)
        self._diplomacy_graph = self.diplomacy.as_graph(self._factions.keys())

        self._current_sites = sites
        self._pending_movements = {}
        self._state_path.clear()

        self.advance_patrol()
        self.process_trade()
        self.engage_raid()
        self.refresh_alliance()

    # ------------------------------------------------------------------
    def _record_state(self, state: str) -> None:
        self._state_path.append(state)

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

    def _state_alliance(self) -> None:
        self._record_state("alliance")
        self.diplomacy.decay()

    # ------------------------------------------------------------------
    def _extract_sites(self, raw_sites: object) -> Dict[str, Site]:
        if raw_sites is None:
            return {}
        if isinstance(raw_sites, Mapping):
            result: Dict[str, Site] = {}
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

    def _extract_site_positions(self, payload: object) -> Dict[str, HexCoord]:
        positions: Dict[str, HexCoord] = {}
        if not isinstance(payload, Mapping):
            return positions
        for key, value in payload.items():
            coord = self._coerce_coord(value)
            if coord is None:
                continue
            positions[str(key)] = coord
        return positions

    def _extract_site_connections(self, payload: object) -> Mapping[str, Sequence[str]]:
        connections: Dict[str, List[str]] = {}
        if not isinstance(payload, Mapping):
            return connections
        for key, value in payload.items():
            if isinstance(value, Sequence):
                connections[str(key)] = [str(item) for item in value]
        return connections

    def _extract_terrain_costs(self, payload: object) -> Mapping[object, float]:
        costs: Dict[object, float] = {}
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
        positions = self._extract_site_positions(world_state.get("site_positions"))
        if not positions:
            return self._movement_graph
        connections = self._extract_site_connections(world_state.get("site_connections"))
        terrain_costs = self._extract_terrain_costs(world_state.get("terrain_costs"))
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
        for faction in self._factions.values():
            for site_id in sites:
                if site_id not in faction.known_sites:
                    faction.known_sites.append(site_id)
            for caravan in faction.caravans.values():
                if caravan.location not in faction.known_sites and caravan.location in sites:
                    faction.known_sites.append(caravan.location)

    def _advance_caravans(self, sites: Mapping[str, Site]) -> Dict[str, List[Caravan]]:
        visits: Dict[str, List[Caravan]] = {}
        for faction in self._factions.values():
            for caravan in faction.caravans.values():
                if not caravan.route:
                    self._plan_route_for_caravan(faction, caravan, sites)
                destination = caravan.advance_day()
                if destination:
                    visits.setdefault(destination, []).append(caravan)
                    self._schedule_next_leg(caravan)
        return visits

    def _plan_route_for_caravan(
        self, faction: Faction, caravan: Caravan, sites: Mapping[str, Site]
    ) -> None:
        if not faction.known_sites:
            return

        hostiles = set()
        if self._diplomacy_graph is not None:
            hostiles.update(hostile_factions(self._diplomacy_graph, faction.name))

        viable_targets: List[str] = []
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
            caravan.days_until_move = self._edge_travel_time(route[0], route[1])
        else:
            caravan.days_until_move = 0

    def _compute_route(self, origin: str, destination: str) -> List[str]:
        if self._movement_graph is None:
            return [origin, destination]
        if origin not in self._movement_graph or destination not in self._movement_graph:
            return [origin, destination]
        try:
            path = list(shortest_path_between_sites(self._movement_graph, origin, destination))
        except nx.NetworkXNoPath:
            return [origin, destination]
        return list(path)

    def _schedule_next_leg(self, caravan: Caravan) -> None:
        if self._movement_graph is None:
            caravan.days_until_move = 0
            return
        if not caravan.route:
            caravan.days_until_move = 0
            return
        next_stop = caravan.route[0]
        caravan.days_until_move = self._edge_travel_time(caravan.location, next_stop)

    def _handle_trade(self, visits: Mapping[str, List[Caravan]], sites: Mapping[str, Site]) -> None:
        for site_id, caravans in visits.items():
            site = sites.get(site_id)
            controlling = site.controlling_faction if site else None
            for caravan in caravans:
                faction = self._factions.get(caravan.faction_name)
                trade_value = caravan.unload_all_cargo()
                if trade_value <= 0:
                    good = faction.preferred_trade_good() if faction else "supplies"
                    caravan.add_cargo(good, self.rng.randint(1, 3))
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

    def _resolve_conflicts(self, sites: Mapping[str, Site]) -> None:
        caravans_by_site: Dict[str, List[Caravan]] = {}
        for faction in self._factions.values():
            for caravan in faction.caravans.values():
                caravans_by_site.setdefault(caravan.location, []).append(caravan)

        for caravans in caravans_by_site.values():
            if len(caravans) < 2:
                continue
            hostile_pairs = self._identify_hostile_pairs(caravans)
            if not hostile_pairs:
                continue
            self._resolve_site_conflict(caravans, hostile_pairs)

    def _identify_hostile_pairs(self, caravans: Sequence[Caravan]) -> List[tuple[str, str]]:
        involved = {caravan.faction_name for caravan in caravans}
        pairs: List[tuple[str, str]] = []
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
        caravans: Sequence[Caravan],
        hostile_pairs: Sequence[tuple[str, str]],
    ) -> None:
        losses: Dict[str, int] = {}
        for faction_a, faction_b in hostile_pairs:
            attacker = self._select_caravan_from_faction(caravans, faction_a)
            defender = self._select_caravan_from_faction(caravans, faction_b)
            if attacker is None or defender is None:
                continue
            if self.rng.random() < 0.5:
                attacker, defender = defender, attacker
                faction_a, faction_b = faction_b, faction_a
            lost_value = defender.unload_all_cargo()
            losses[faction_b] = losses.get(faction_b, 0) + lost_value + 1
            self.diplomacy.adjust_standing(faction_a, faction_b, -3.0)
        for faction_name, loss in losses.items():
            faction = self._factions.get(faction_name)
            if faction is None:
                continue
            faction.adjust_resource("losses", -loss)

    def _select_caravan_from_faction(
        self, caravans: Sequence[Caravan], faction_name: str
    ) -> Caravan | None:
        candidates = [caravan for caravan in caravans if caravan.faction_name == faction_name]
        if not candidates:
            return None
        return self.rng.choice(candidates)

    def _coerce_coord(self, value: object) -> HexCoord | None:
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
