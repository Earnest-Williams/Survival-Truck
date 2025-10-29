"""Settlement simulation and growth mechanics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, MutableMapping

from numpy.random import Generator

from .sites import Site


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


@dataclass
class Settlement:
    """Represents an autonomous community anchored to a site."""

    identifier: str
    site_id: str
    name: str
    population: int
    morale: float = 55.0
    prosperity: float = 0.1
    security: float = 0.0
    resources: MutableMapping[str, int] = field(default_factory=dict)

    def adjust_resource(self, resource: str, amount: int) -> int:
        """Adjust a tracked resource pool and return the new value."""

        total = self.resources.get(resource, 0) + amount
        total = max(0, total)
        self.resources[resource] = total
        return total

    def advance_day(self) -> None:
        """Update morale, population, and prosperity for a single day."""

        food_available = self.resources.get("food", 0)
        consumption = min(self.population, food_available)
        deficit = self.population - consumption
        self.resources["food"] = food_available - consumption

        morale_delta = 1.2 if deficit == 0 else -0.6 * deficit
        morale_delta += self.prosperity * 2.0
        morale_delta += self.security * 0.5
        self.morale = _clamp(self.morale + morale_delta, 0.0, 100.0)

        growth_factor = (self.morale - 50.0) / 200.0 + self.prosperity * 0.05
        growth = int(self.population * growth_factor)
        if deficit > 0:
            growth -= deficit
        self.population = max(0, self.population + growth)

        if self.population == 0:
            self.morale = 0.0
            return

        prosperity_shift = (self.morale - 50.0) / 500.0
        if deficit > 0:
            prosperity_shift -= deficit * 0.02
        self.prosperity = _clamp(self.prosperity + prosperity_shift, 0.0, 5.0)

    def to_dict(self) -> Dict[str, object]:
        return {
            "identifier": self.identifier,
            "site_id": self.site_id,
            "name": self.name,
            "population": self.population,
            "morale": self.morale,
            "prosperity": self.prosperity,
            "security": self.security,
            "resources": dict(self.resources),
        }

    @staticmethod
    def from_dict(payload: Mapping[str, object]) -> "Settlement":
        resources_payload = payload.get("resources", {})
        resources: Dict[str, int] = {}
        if isinstance(resources_payload, Mapping):
            for key, value in resources_payload.items():
                resources[str(key)] = int(value)
        return Settlement(
            identifier=str(payload.get("identifier")),
            site_id=str(payload.get("site_id")),
            name=str(payload.get("name", "Settlement")),
            population=int(payload.get("population", 0)),
            morale=float(payload.get("morale", 55.0)),
            prosperity=float(payload.get("prosperity", 0.1)),
            security=float(payload.get("security", 0.0)),
            resources=resources,
        )


class SettlementManager:
    """Factory and coordinator for settlements across the world."""

    def __init__(
        self,
        settlements: Iterable[Settlement] | None = None,
        *,
        rng: Generator | None = None,
    ) -> None:
        self._settlements: Dict[str, Settlement] = {
            settlement.identifier: settlement for settlement in (settlements or [])
        }
        self.rng = rng
        self._counter = 0

    @property
    def settlements(self) -> Mapping[str, Settlement]:
        return self._settlements

    def spawn_settlement(
        self,
        site: Site,
        *,
        base_name: str | None = None,
        initial_population: int | None = None,
    ) -> Settlement:
        """Create a new settlement for ``site`` if one does not already exist."""

        if site.settlement_id and site.settlement_id in self._settlements:
            return self._settlements[site.settlement_id]

        self._counter += 1
        identifier = site.settlement_id or f"{site.identifier}-settlement-{self._counter}"
        name = base_name or f"{site.identifier.title()} Haven"
        if initial_population is not None:
            population = initial_population
        elif site.population:
            population = site.population
        elif self.rng is not None:
            population = int(self.rng.integers(15, 31))
        else:
            population = 20
        settlement = Settlement(
            identifier=identifier,
            site_id=site.identifier,
            name=name,
            population=population,
        )
        settlement.adjust_resource("food", population * 3)
        site.population = population
        site.settlement_id = identifier
        if site.controlling_faction is None:
            site.controlling_faction = settlement.name
        self._settlements[identifier] = settlement
        return settlement

    def advance_day(self, sites: Mapping[str, Site]) -> None:
        """Update all settlements and synchronize their host sites."""

        to_remove: List[str] = []
        for settlement in self._settlements.values():
            settlement.advance_day()
            site = sites.get(settlement.site_id)
            if site is None:
                continue
            site.population = settlement.population
            if settlement.population <= 0:
                site.population = 0
                site.controlling_faction = None
                site.settlement_id = None
                to_remove.append(settlement.identifier)
            else:
                if site.controlling_faction is None:
                    site.controlling_faction = settlement.name
        for identifier in to_remove:
            self._settlements.pop(identifier, None)

    def consider_expansion(self, sites: Mapping[str, Site]) -> list[Settlement]:
        """Spawn settlements on explored sites that lack a population."""

        created: list[Settlement] = []
        for site in sites.values():
            if site.settlement_id is not None:
                continue
            if site.population > 0:
                continue
            if site.exploration_percent < 75.0:
                continue
            if site.scavenged_percent > 80.0:
                continue
            created.append(self.spawn_settlement(site))
        return created


__all__ = ["Settlement", "SettlementManager"]
