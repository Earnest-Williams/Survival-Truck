"""Seasonal tracking utilities for daily turn progression."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeasonProfile:
    """Configuration of movement and resource modifiers for a season."""

    name: str
    movement_cost_multiplier: float = 1.0
    resource_cost_multiplier: float = 1.0


class SeasonTracker:
    """Tracks the current season and associated daily modifiers.

    The tracker advances with each turn (day) and exposes helper methods that
    allow subsystems such as travel or maintenance to adjust their costs based
    on the active season.
    """

    def __init__(
        self,
        *,
        seasons: dict[int, SeasonProfile] | None = None,
        days_per_season: int = 30,
        starting_day: int = 0,
    ) -> None:
        if days_per_season <= 0:
            raise ValueError("days_per_season must be positive")

        self._days_per_season = days_per_season
        self._current_day = starting_day
        self._seasons = seasons or self._default_season_cycle()

    @staticmethod
    def _default_season_cycle() -> dict[int, SeasonProfile]:
        return {
            0: SeasonProfile("spring", movement_cost_multiplier=0.95, resource_cost_multiplier=1.0),
            1: SeasonProfile("summer", movement_cost_multiplier=0.9, resource_cost_multiplier=0.95),
            2: SeasonProfile("autumn", movement_cost_multiplier=1.0, resource_cost_multiplier=1.05),
            3: SeasonProfile("winter", movement_cost_multiplier=1.2, resource_cost_multiplier=1.15),
        }

    def advance_day(self) -> None:
        """Advance the tracker to the next day."""

        self._current_day += 1

    @property
    def current_day(self) -> int:
        return self._current_day

    @property
    def season_index(self) -> int:
        return (self._current_day // self._days_per_season) % len(self._seasons)

    @property
    def current_season(self) -> SeasonProfile:
        return self._seasons[self.season_index]

    def movement_cost_for(self, base_cost: float) -> float:
        """Return the movement cost adjusted for the current season."""

        return base_cost * self.current_season.movement_cost_multiplier

    def resource_cost_for(self, base_cost: float) -> float:
        """Return the resource cost adjusted for the current season."""

        return base_cost * self.current_season.resource_cost_multiplier

    def days_until_next_season(self) -> int:
        """Number of days remaining before the season changes."""

        offset = self._current_day % self._days_per_season
        return (
            self._days_per_season - offset if offset != 0 else self._days_per_season
        )
