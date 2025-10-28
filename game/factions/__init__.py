"""Faction simulation and diplomacy systems."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Mapping, MutableMapping, Optional, Sequence
import random

from ..world.sites import Site


@dataclass
class Caravan:
    """A mobile trading group that moves between sites."""

    identifier: str
    faction_name: str
    location: str
    cargo: MutableMapping[str, int] = field(default_factory=dict)
    route: List[str] = field(default_factory=list)
    days_until_move: int = 0

    def advance_day(self) -> Optional[str]:
        """Advance the caravan along its planned route.

        Returns the identifier of the new site if the caravan moved this day,
        otherwise ``None``.
        """

        if self.days_until_move > 0:
            self.days_until_move -= 1
            return None

        if not self.route:
            return None

        if self.route[0] == self.location:
            # Drop the current location from the route if it is the first step.
            self.route.pop(0)

        if not self.route:
            return None

        next_site = self.route.pop(0)
        previous_location = self.location
        self.location = next_site
        self.days_until_move = 0
        return next_site if next_site != previous_location else None

    def plan_route(self, stops: Sequence[str]) -> None:
        """Assign a new travel route."""

        self.route = list(stops)

    def unload_all_cargo(self) -> int:
        """Remove all cargo and return the total value unloaded."""

        total_value = 0
        for good, amount in list(self.cargo.items()):
            if amount <= 0:
                continue
            total_value += int(amount)
            self.cargo[good] = 0
        return total_value

    def add_cargo(self, good: str, amount: int) -> None:
        """Add ``amount`` of ``good`` to the caravan's manifest."""

        if amount <= 0:
            return
        self.cargo[good] = self.cargo.get(good, 0) + amount


@dataclass
class Faction:
    """A political entity with caravans and resource holdings."""

    name: str
    resources: MutableMapping[str, int] = field(default_factory=dict)
    caravans: Dict[str, Caravan] = field(default_factory=dict)
    known_sites: List[str] = field(default_factory=list)

    def register_caravan(self, caravan: Caravan) -> None:
        if caravan.faction_name != self.name:
            raise ValueError("caravan faction does not match")
        self.caravans[caravan.identifier] = caravan
        if caravan.location not in self.known_sites:
            self.known_sites.append(caravan.location)

    def remove_caravan(self, identifier: str) -> None:
        self.caravans.pop(identifier, None)

    def add_known_site(self, site_id: str) -> None:
        if site_id not in self.known_sites:
            self.known_sites.append(site_id)

    def adjust_resource(self, resource: str, amount: int) -> None:
        self.resources[resource] = self.resources.get(resource, 0) + amount


class FactionDiplomacy:
    """Tracks standing between factions and provides helpers for adjustments."""

    def __init__(
        self,
        *,
        neutral_value: float = 0.0,
        min_value: float = -100.0,
        max_value: float = 100.0,
        daily_decay: float = 0.2,
    ) -> None:
        self._relations: Dict[tuple[str, str], float] = {}
        self.neutral_value = neutral_value
        self.min_value = min_value
        self.max_value = max_value
        self.daily_decay = daily_decay

    def _key(self, faction_a: str, faction_b: str) -> tuple[str, str]:
        if faction_a == faction_b:
            return (faction_a, faction_b)
        return tuple(sorted((faction_a, faction_b)))  # type: ignore[return-value]

    def get_standing(self, faction_a: str, faction_b: str) -> float:
        if faction_a == faction_b:
            return self.max_value
        return self._relations.get(self._key(faction_a, faction_b), self.neutral_value)

    def set_standing(self, faction_a: str, faction_b: str, value: float) -> None:
        key = self._key(faction_a, faction_b)
        if faction_a == faction_b:
            return
        self._relations[key] = float(max(self.min_value, min(self.max_value, value)))

    def adjust_standing(self, faction_a: str, faction_b: str, delta: float) -> float:
        if faction_a == faction_b:
            return self.max_value
        key = self._key(faction_a, faction_b)
        current = self._relations.get(key, self.neutral_value)
        updated = max(self.min_value, min(self.max_value, current + delta))
        self._relations[key] = updated
        return updated

    def decay(self) -> None:
        """Drift all standings towards neutral."""

        to_delete: List[tuple[str, str]] = []
        for key, value in self._relations.items():
            if key[0] == key[1]:
                continue
            if abs(value - self.neutral_value) <= self.daily_decay:
                to_delete.append(key)
            elif value > self.neutral_value:
                self._relations[key] = max(self.neutral_value, value - self.daily_decay)
            else:
                self._relations[key] = min(self.neutral_value, value + self.daily_decay)
        for key in to_delete:
            self._relations.pop(key, None)

    def hostile_pairs(self, threshold: float = -25.0) -> Iterator[tuple[str, str]]:
        for (a, b), value in self._relations.items():
            if a == b:
                continue
            if value <= threshold:
                yield a, b


class FactionAIController:
    """Coordinates AI decision making for NPC factions."""

    def __init__(
        self,
        factions: Iterable[Faction] | None = None,
        *,
        diplomacy: FactionDiplomacy | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._factions: Dict[str, Faction] = {faction.name: faction for faction in (factions or [])}
        self.diplomacy = diplomacy or FactionDiplomacy()
        self.rng = rng or random.Random()

    @property
    def factions(self) -> Mapping[str, Faction]:
        return self._factions

    def get_or_create_faction(self, name: str) -> Faction:
        if name not in self._factions:
            self._factions[name] = Faction(name=name)
        return self._factions[name]

    def run_turn(self, *, world_state: Mapping[str, object], day: int) -> None:
        """Execute faction behaviours for the current day."""

        sites = self._extract_sites(world_state.get("sites"))
        self._sync_known_sites(sites)
        movements = self._advance_caravans(sites)
        self._handle_trade(movements, sites)
        self._resolve_conflicts(sites)
        self.diplomacy.decay()

    def _extract_sites(self, raw_sites: object) -> Dict[str, Site]:
        if raw_sites is None:
            return {}
        if isinstance(raw_sites, dict):
            result: Dict[str, Site] = {}
            for key, value in raw_sites.items():
                if isinstance(value, Site):
                    result[key] = value
            return result
        if isinstance(raw_sites, Iterable):
            result = {}
            for value in raw_sites:
                if isinstance(value, Site):
                    result[value.identifier] = value
            return result
        return {}

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
        return visits

    def _plan_route_for_caravan(self, faction: Faction, caravan: Caravan, sites: Mapping[str, Site]) -> None:
        if not faction.known_sites:
            return
        possible_targets = [site for site in faction.known_sites if site != caravan.location]
        if not possible_targets:
            possible_targets = list(faction.known_sites)
        if not possible_targets:
            return
        destination = self.rng.choice(possible_targets)
        route = [caravan.location, destination]
        caravan.plan_route(route)
        caravan.days_until_move = self.rng.randint(0, 1)

    def _handle_trade(self, visits: Mapping[str, List[Caravan]], sites: Mapping[str, Site]) -> None:
        for site_id, caravans in visits.items():
            site = sites.get(site_id)
            controlling = site.controlling_faction if site else None
            for caravan in caravans:
                trade_value = caravan.unload_all_cargo()
                if trade_value <= 0:
                    caravan.add_cargo("supplies", self.rng.randint(1, 3))
                    continue
                faction = self._factions.get(caravan.faction_name)
                if faction is not None:
                    faction.adjust_resource("wealth", trade_value)
                if controlling and controlling != caravan.faction_name:
                    self.diplomacy.adjust_standing(caravan.faction_name, controlling, 2.0)
                caravan.add_cargo("supplies", max(1, trade_value // 2))

    def _resolve_conflicts(self, sites: Mapping[str, Site]) -> None:
        caravans_by_site: Dict[str, List[Caravan]] = {}
        for faction in self._factions.values():
            for caravan in faction.caravans.values():
                caravans_by_site.setdefault(caravan.location, []).append(caravan)

        for site_id, caravans in caravans_by_site.items():
            if len(caravans) < 2:
                continue
            involved_factions = {caravan.faction_name for caravan in caravans}
            if len(involved_factions) < 2:
                continue
            hostile_pairs = [
                (a, b)
                for a in involved_factions
                for b in involved_factions
                if a < b and self.diplomacy.get_standing(a, b) <= -15.0
            ]
            if not hostile_pairs:
                continue
            self._resolve_site_conflict(site_id, caravans, hostile_pairs)

    def _resolve_site_conflict(
        self,
        site_id: str,
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
    ) -> Optional[Caravan]:
        candidates = [caravan for caravan in caravans if caravan.faction_name == faction_name]
        if not candidates:
            return None
        return self.rng.choice(candidates)


__all__ = [
    "Caravan",
    "Faction",
    "FactionDiplomacy",
    "FactionAIController",
]
