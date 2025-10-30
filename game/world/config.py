"""Validated configuration models for world generation and persistence."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .rng import WorldRandomness


class DifficultyLevel(str, Enum):
    """Enumerates broad difficulty tiers for the simulation."""

    STORY = "story"
    STANDARD = "standard"
    HARDCORE = "hardcore"


class BiomeWeighting(BaseModel):
    """Relative weighting for biome selection during generation."""

    model_config = ConfigDict(extra="forbid")

    barren: float = Field(default=1.0, ge=0.0)
    scrubland: float = Field(default=1.0, ge=0.0)
    forest: float = Field(default=1.0, ge=0.0)
    highland: float = Field(default=1.0, ge=0.0)
    water: float = Field(default=1.0, ge=0.0)

    @field_validator("barren", "scrubland", "forest", "highland", "water")
    @classmethod
    def _coerce_float(cls, value: float) -> float:
        return float(value)

    @property
    def normalised(self) -> dict[str, float]:
        """Return weights normalised to sum to one."""

        totals = {
            "barren": self.barren,
            "scrubland": self.scrubland,
            "forest": self.forest,
            "highland": self.highland,
            "water": self.water,
        }
        total = sum(totals.values())
        if total <= 0:
            return {key: 0.0 for key in totals}
        return {key: value / total for key, value in totals.items()}


class WorldMapSettings(BaseModel):
    """Static map parameters shared between generation and streaming."""

    model_config = ConfigDict(extra="forbid")

    chunk_size: int = Field(default=12, ge=1)
    view_radius: int = Field(default=3, ge=0)
    biome_frequency: float = Field(default=0.1, gt=0.0)
    max_cached_chunks: int = Field(default=64, ge=1)

    @property
    def visible_chunk_count(self) -> int:
        """Number of chunks maintained around the focal point."""

        diameter = self.view_radius * 2 + 1
        return diameter * diameter


class WorldRandomnessSettings(BaseModel):
    """Configuration for deterministic RNG streams."""

    model_config = ConfigDict(extra="forbid")

    seed: int = Field(default=0, ge=0)
    salt: str = Field(default="world")

    def factory(self) -> WorldRandomness:
        """Instantiate a :class:`~game.world.rng.WorldRandomness` helper."""

        from .rng import WorldRandomness

        return WorldRandomness(seed=self.seed)


class WorldConfig(BaseModel):
    """Top-level configuration payload describing a world."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Survival Truck World")
    description: str | None = Field(default=None)
    difficulty: DifficultyLevel = Field(default=DifficultyLevel.STANDARD)
    day_zero: int = Field(default=0, ge=0)
    map: WorldMapSettings = Field(default_factory=WorldMapSettings)
    randomness: WorldRandomnessSettings = Field(default_factory=WorldRandomnessSettings)
    biome_weights: BiomeWeighting = Field(default_factory=BiomeWeighting)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def _ensure_metadata_mapping(cls, value: object) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise TypeError("metadata must be a mapping")
        return {str(key): item for key, item in value.items()}

    @property
    def seed(self) -> int:
        """Expose the configured world seed."""

        return self.randomness.seed

    def randomness_factory(self) -> WorldRandomness:
        """Return a new :class:`~game.world.rng.WorldRandomness` instance."""

        return self.randomness.factory()


__all__ = [
    "BiomeWeighting",
    "DifficultyLevel",
    "WorldConfig",
    "WorldMapSettings",
    "WorldRandomnessSettings",
]
