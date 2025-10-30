"""Daily weather generation utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Mapping, MutableMapping, Sequence, Tuple

from numpy.random import Generator, default_rng


@dataclass(frozen=True)
class WeatherCondition:
    """Represents a single day's weather and its gameplay modifiers."""

    name: str
    travel_cost_multiplier: float = 1.0
    maintenance_cost_multiplier: float = 1.0
    description: str | None = None


class WeatherSystem:
    """Generates daily weather conditions based on seasonal weighting."""

    def __init__(
        self,
        *,
        seasonal_tables: Mapping[
            str, Sequence[WeatherCondition | Tuple[WeatherCondition, float]]
        ]
        | None = None,
        rng: Generator | None = None,
        starting_day: int = 0,
        starting_season: str | None = None,
    ) -> None:
        if starting_day < 0:
            raise ValueError("starting_day must be non-negative")

        self._rng: Generator = rng or default_rng()
        self._tables: MutableMapping[str, List[Tuple[WeatherCondition, float]]] = {}
        self._totals: MutableMapping[str, float] = {}
        self._current_day = starting_day

        tables = seasonal_tables or self._default_tables()
        for season_name, entries in tables.items():
            normalized = self._normalize_entries(entries)
            self._tables[season_name] = normalized
            self._totals[season_name] = sum(weight for _, weight in normalized)

        if "default" not in self._tables:
            default_entries = self._normalize_entries(self._default_tables()["default"])
            self._tables["default"] = default_entries
            self._totals["default"] = sum(weight for _, weight in default_entries)

        initial_table_key = self._resolve_table_key(starting_season)
        self._current_condition = self._roll_condition(initial_table_key)

    # ------------------------------------------------------------------
    @staticmethod
    def _default_tables() -> Mapping[str, Sequence[Tuple[WeatherCondition, float]]]:
        clear = WeatherCondition(
            "clear", travel_cost_multiplier=1.0, maintenance_cost_multiplier=1.0
        )
        rain = WeatherCondition(
            "rain", travel_cost_multiplier=1.1, maintenance_cost_multiplier=1.05
        )
        storm = WeatherCondition(
            "storm", travel_cost_multiplier=1.25, maintenance_cost_multiplier=1.2
        )
        snow = WeatherCondition(
            "snow", travel_cost_multiplier=1.35, maintenance_cost_multiplier=1.3
        )

        return {
            "default": ((clear, 1.0),),
            "spring": ((clear, 0.6), (rain, 0.3), (storm, 0.1)),
            "summer": ((clear, 0.7), (rain, 0.2), (storm, 0.1)),
            "autumn": ((clear, 0.5), (rain, 0.35), (storm, 0.15)),
            "winter": ((clear, 0.4), (snow, 0.4), (storm, 0.2)),
        }

    def _normalize_entries(
        self, entries: Sequence[WeatherCondition | Tuple[WeatherCondition, float]]
    ) -> List[Tuple[WeatherCondition, float]]:
        normalized: List[Tuple[WeatherCondition, float]] = []
        for entry in entries:
            if isinstance(entry, WeatherCondition):
                condition, weight = entry, 1.0
            else:
                condition, weight = entry
            if weight <= 0:
                continue
            normalized.append((condition, float(weight)))
        if not normalized:
            raise ValueError(
                "weather table must contain at least one positive-weight condition"
            )
        return normalized

    def _resolve_table_key(self, season: str | None) -> str:
        if season and season in self._tables:
            return season
        return "default"

    def _roll_condition(self, table_key: str) -> WeatherCondition:
        table = self._tables[table_key]
        total = self._totals[table_key]
        roll = float(self._rng.uniform(0, total))
        cumulative = 0.0
        for condition, weight in table:
            cumulative += weight
            if roll <= cumulative:
                return condition
        # Numerical stability fallback; shouldn't occur but ensures a result.
        return table[-1][0]

    # ------------------------------------------------------------------
    @property
    def current_day(self) -> int:
        """Return the day index the weather system is aligned with."""

        return self._current_day

    @property
    def current_condition(self) -> WeatherCondition:
        """Return the active weather condition for the day."""

        return self._current_condition

    def advance_day(self, *, season: str | None = None) -> WeatherCondition:
        """Advance to the next day and roll a new condition."""

        self._current_day += 1
        table_key = self._resolve_table_key(season)
        self._current_condition = self._roll_condition(table_key)
        return self._current_condition

    def sync_to_day(self, day: int, *, season: str | None = None) -> WeatherCondition:
        """Ensure the weather system is aligned to ``day``."""

        if day < self._current_day:
            raise ValueError("cannot rewind weather system")
        while self._current_day < day:
            self.advance_day(season=season)
        return self._current_condition

    def condition_history(
        self, *, days: int, season: str | None = None
    ) -> Iterable[WeatherCondition]:  # pragma: no cover - utility method
        """Yield ``days`` future conditions without mutating state."""

        table_key = self._resolve_table_key(season)
        table = self._tables[table_key]
        total = self._totals[table_key]
        temp_rng = default_rng(self._rng.bit_generator.random_raw())
        for _ in range(days):
            roll = float(temp_rng.uniform(0, total))
            cumulative = 0.0
            for condition, weight in table:
                cumulative += weight
                if roll <= cumulative:
                    yield condition
                    break


__all__ = ["WeatherCondition", "WeatherSystem"]
