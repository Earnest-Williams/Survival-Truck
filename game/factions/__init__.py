"""Faction state management backed by Polars DataFrames."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, Tuple

from .state import CaravanRecord, FactionLedger, FactionRecord

# Backwards-compatible handles used in tests and docs.
Caravan = CaravanRecord
Faction = FactionRecord


@dataclass(slots=True)
class FactionDiplomacy:
    """Tracks standing between factions and provides helpers for adjustments."""

    neutral_value: float = 0.0
    min_value: float = -100.0
    max_value: float = 100.0
    daily_decay: float = 0.2
    _relations: Dict[Tuple[str, str], float] = field(init=False, default_factory=dict)

    def _key(self, faction_a: str, faction_b: str) -> Tuple[str, str]:
        if faction_a == faction_b:
            return (faction_a, faction_b)
        return tuple(sorted((faction_a, faction_b)))

    def get_standing(self, faction_a: str, faction_b: str) -> float:
        if faction_a == faction_b:
            return self.max_value
        return self._relations.get(self._key(faction_a, faction_b), self.neutral_value)

    def set_standing(self, faction_a: str, faction_b: str, value: float) -> None:
        if faction_a == faction_b:
            return
        key = self._key(faction_a, faction_b)
        bounded = max(self.min_value, min(self.max_value, float(value)))
        self._relations[key] = bounded

    def adjust_standing(self, faction_a: str, faction_b: str, delta: float) -> float:
        if faction_a == faction_b:
            return self.max_value
        key = self._key(faction_a, faction_b)
        current = self._relations.get(key, self.neutral_value)
        updated = max(self.min_value, min(self.max_value, current + float(delta)))
        self._relations[key] = updated
        return updated

    def decay(self) -> None:
        """Drift all standings towards neutral."""

        to_remove: list[Tuple[str, str]] = []
        for key, value in list(self._relations.items()):
            if key[0] == key[1]:
                continue
            if abs(value - self.neutral_value) <= self.daily_decay:
                to_remove.append(key)
            elif value > self.neutral_value:
                self._relations[key] = max(self.neutral_value, value - self.daily_decay)
            else:
                self._relations[key] = min(self.neutral_value, value + self.daily_decay)
        for key in to_remove:
            self._relations.pop(key, None)

    def hostile_pairs(self, threshold: float = -25.0) -> Iterator[Tuple[str, str]]:
        for (a, b), value in self._relations.items():
            if a == b:
                continue
            if value <= threshold:
                yield a, b

    def as_graph(self, factions: Iterable[str]) -> "nx.Graph":
        """Return a NetworkX graph capturing current standings."""

        import networkx as nx

        from ..world.graph import build_diplomacy_graph

        return build_diplomacy_graph(
            factions, self._relations, neutral_value=self.neutral_value
        )


from .ai import FactionAIController

__all__ = [
    "CaravanRecord",
    "Caravan",
    "Faction",
    "FactionAIController",
    "FactionDiplomacy",
    "FactionLedger",
    "FactionRecord",
]
