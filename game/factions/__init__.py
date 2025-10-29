"""Faction domain models and public exports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Mapping, MutableMapping, Sequence

from .trade import TradeInterface, TradeOffer


@dataclass
class Caravan:
    """A mobile trading group that moves between sites."""

    identifier: str
    faction_name: str
    location: str
    cargo: MutableMapping[str, int] = field(default_factory=dict)
    route: List[str] = field(default_factory=list)
    days_until_move: int = 0

    def advance_day(self) -> str | None:
        """Advance the caravan along its planned route."""

        if self.days_until_move > 0:
            self.days_until_move -= 1
            return None

        if not self.route:
            return None

        if self.route and self.route[0] == self.location:
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
    resource_preferences: MutableMapping[str, float] = field(default_factory=dict)

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

    def set_resource_preference(self, resource: str, weight: float) -> None:
        """Assign a desirability weight for a specific resource or category."""

        self.resource_preferences[str(resource)] = float(weight)

    def preference_for(
        self, resource: str, *, category: str | None = None, default: float = 1.0
    ) -> float:
        """Return the preference weight for ``resource`` or ``category``."""

        if resource in self.resource_preferences:
            return float(self.resource_preferences[resource])
        if category:
            if category in self.resource_preferences:
                return float(self.resource_preferences[category])
            category_key = f"category:{category}"
            if category_key in self.resource_preferences:
                return float(self.resource_preferences[category_key])
        return float(self.resource_preferences.get("default", default))

    def preferred_trade_good(self, fallback: str = "supplies") -> str:
        """Return the most desired explicit resource for trading."""

        best_resource = fallback
        best_weight = float("-inf")
        for resource, weight in self.resource_preferences.items():
            if resource.startswith("category:"):
                continue
            if weight > best_weight:
                best_resource = resource
                best_weight = weight
        if best_weight == float("-inf"):
            return fallback
        return best_resource


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

    def as_graph(self, factions: Iterable[str]) -> "nx.Graph":
        """Return a NetworkX graph capturing current standings."""

        from ..world.graph import build_diplomacy_graph
        import networkx as nx

        graph = build_diplomacy_graph(factions, self._relations, neutral_value=self.neutral_value)
        graph.graph.setdefault("min_value", float(self.min_value))
        graph.graph.setdefault("max_value", float(self.max_value))
        return graph


from .ai import FactionAIController


__all__ = [
    "Caravan",
    "Faction",
    "FactionDiplomacy",
    "FactionAIController",
    "TradeInterface",
    "TradeOffer",
]
