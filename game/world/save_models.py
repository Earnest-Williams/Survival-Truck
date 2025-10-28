"""Pydantic models describing world snapshot payloads."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Dict, List

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .map import BiomeType, ChunkCoord, MapChunk
from .sites import AttentionCurve, Site, SiteType

_SIMPLE_TYPES = (str, int, float, bool)
_DROP = object()


def _sanitize_value(value: object) -> object:
    """Best-effort conversion of ``value`` into a msgpack-friendly form."""

    if value is None:
        return None
    if isinstance(value, _SIMPLE_TYPES):
        return value
    if isinstance(value, Mapping):
        sanitized: Dict[str, object] = {}
        dropped = False
        for key, item in value.items():
            sanitized_item = _sanitize_value(item)
            if sanitized_item is _DROP:
                dropped = True
                continue
            sanitized[str(key)] = sanitized_item
        if sanitized or not value or not dropped:
            return sanitized
        return _DROP
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        sanitized_list: List[object] = []
        dropped = False
        for item in value:
            sanitized_item = _sanitize_value(item)
            if sanitized_item is _DROP:
                dropped = True
                continue
            sanitized_list.append(sanitized_item)
        if sanitized_list or not value or not dropped:
            return sanitized_list
        return _DROP
    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        return _sanitize_value(value.to_dict())
    if hasattr(value, "__dict__"):
        return _sanitize_value(vars(value))
    return _DROP


class ChunkTileModel(BaseModel):
    """A single biome entry inside a chunk snapshot."""

    model_config = ConfigDict(extra="forbid")

    local_q: int = Field(ge=0)
    local_r: int = Field(ge=0)
    biome: BiomeType


class ChunkSnapshot(BaseModel):
    """Serializable representation of a :class:`~game.world.map.MapChunk`."""

    model_config = ConfigDict(extra="forbid")

    q: int
    r: int
    chunk_size: int = Field(ge=1)
    tiles: List[ChunkTileModel] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_tiles(self) -> "ChunkSnapshot":
        max_index = self.chunk_size - 1
        for tile in self.tiles:
            if tile.local_q < 0 or tile.local_q > max_index:
                raise ValueError("tile local_q outside chunk bounds")
            if tile.local_r < 0 or tile.local_r > max_index:
                raise ValueError("tile local_r outside chunk bounds")
        return self

    @classmethod
    def from_chunk(cls, chunk: MapChunk) -> "ChunkSnapshot":
        tiles = [
            ChunkTileModel(local_q=q, local_r=r, biome=biome)
            for (q, r), biome in sorted(chunk.biomes.items())
        ]
        return cls(q=chunk.coord.q, r=chunk.coord.r, chunk_size=chunk.chunk_size, tiles=tiles)

    def to_chunk(self) -> MapChunk:
        coord = ChunkCoord(self.q, self.r)
        chunk = MapChunk(coord=coord, chunk_size=self.chunk_size)
        for tile in self.tiles:
            chunk.set_biome(tile.local_q, tile.local_r, tile.biome)
        return chunk


class AttentionCurveModel(BaseModel):
    """Serializable representation of :class:`~game.world.sites.AttentionCurve`."""

    model_config = ConfigDict(extra="forbid")

    base: float = 0.0
    growth: float = 0.0
    decay: float = 0.0

    @field_validator("base", "growth", "decay")
    @classmethod
    def _coerce_float(cls, value: float) -> float:
        return float(value)

    @classmethod
    def from_domain(cls, curve: AttentionCurve) -> "AttentionCurveModel":
        return cls(base=curve.base, growth=curve.growth, decay=curve.decay)

    def to_domain(self) -> AttentionCurve:
        return AttentionCurve(base=self.base, growth=self.growth, decay=self.decay)


class SiteSnapshot(BaseModel):
    """Serializable representation of a :class:`~game.world.sites.Site`."""

    model_config = ConfigDict(extra="forbid")

    identifier: str
    site_type: SiteType = Field(default=SiteType.CAMP)
    exploration_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    scavenged_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    population: int = Field(default=0, ge=0)
    controlling_faction: str | None = None
    attention_curve: AttentionCurveModel = Field(default_factory=AttentionCurveModel)
    settlement_id: str | None = None
    connections: Dict[str, float] = Field(default_factory=dict)

    @field_validator("controlling_faction", "settlement_id")
    @classmethod
    def _ensure_str_or_none(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value)

    @field_validator("connections", mode="before")
    @classmethod
    def _normalise_connections(cls, value: object) -> Dict[str, float]:
        if value in (None, {}):
            return {}
        if not isinstance(value, Mapping):
            raise TypeError("connections must be a mapping of site ids to costs")
        normalised: Dict[str, float] = {}
        for key, cost in value.items():
            name = str(key)
            cost_value = float(cost)
            if cost_value < 0:
                raise ValueError("connection cost cannot be negative")
            normalised[name] = cost_value
        return normalised

    @classmethod
    def from_site(cls, site: Site) -> "SiteSnapshot":
        return cls(
            identifier=site.identifier,
            site_type=site.site_type,
            exploration_percent=site.exploration_percent,
            scavenged_percent=site.scavenged_percent,
            population=site.population,
            controlling_faction=site.controlling_faction,
            attention_curve=AttentionCurveModel.from_domain(site.attention_curve),
            settlement_id=site.settlement_id,
            connections=site.connections,
        )

    def to_site(self) -> Site:
        return Site(
            identifier=self.identifier,
            site_type=self.site_type,
            exploration_percent=self.exploration_percent,
            scavenged_percent=self.scavenged_percent,
            population=self.population,
            controlling_faction=self.controlling_faction,
            attention_curve=self.attention_curve.to_domain(),
            settlement_id=self.settlement_id,
            connections=self.connections,
        )


class WorldSnapshot(BaseModel):
    """Complete snapshot of deterministic world state."""

    model_config = ConfigDict(extra="forbid")

    day: int = Field(ge=0)
    chunks: List[ChunkSnapshot] = Field(default_factory=list)
    sites: List[SiteSnapshot] = Field(default_factory=list)
    world_state: Dict[str, object] = Field(default_factory=dict)

    @classmethod
    def from_components(
        cls,
        *,
        day: int,
        chunks: Iterable[MapChunk],
        sites: Mapping[str, Site] | None = None,
        world_state: Mapping[str, object] | None = None,
    ) -> "WorldSnapshot":
        site_map: Mapping[str, Site] = sites or {}
        if not site_map and world_state and isinstance(world_state.get("sites"), Mapping):
            candidate = world_state["sites"]
            if isinstance(candidate, Mapping) and all(isinstance(v, Site) for v in candidate.values()):
                site_map = candidate  # type: ignore[assignment]
        chunk_models = [ChunkSnapshot.from_chunk(chunk) for chunk in chunks]
        site_models = [SiteSnapshot.from_site(site) for _, site in sorted(site_map.items())]
        sanitized_state: Dict[str, object] = {}
        if world_state:
            for key, value in world_state.items():
                sanitized = _sanitize_value(value)
                if sanitized is _DROP:
                    continue
                sanitized_state[str(key)] = sanitized
        sanitized_state.pop("sites", None)
        return cls(day=day, chunks=chunk_models, sites=site_models, world_state=sanitized_state)

    def to_chunks(self) -> List[MapChunk]:
        return [chunk.to_chunk() for chunk in self.chunks]

    def to_site_map(self) -> Dict[str, Site]:
        return {site.identifier: site.to_site() for site in self.sites}

    def to_world_state(self) -> Dict[str, object]:
        state = dict(self.world_state)
        state["sites"] = self.to_site_map()
        return state

    def metadata(self, *, summary: str | None = None, created_at: datetime | None = None) -> "WorldSnapshotMetadata":
        return WorldSnapshotMetadata.from_snapshot(self, summary=summary, created_at=created_at)


class WorldSnapshotMetadata(BaseModel):
    """Lightweight descriptor stored alongside each snapshot payload."""

    model_config = ConfigDict(extra="forbid")

    day: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    site_count: int = Field(ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    summary: str | None = None

    @classmethod
    def from_snapshot(
        cls,
        snapshot: WorldSnapshot,
        *,
        summary: str | None = None,
        created_at: datetime | None = None,
    ) -> "WorldSnapshotMetadata":
        if summary is None:
            summary = f"Day {snapshot.day}: {len(snapshot.chunks)} chunks / {len(snapshot.sites)} sites"
        timestamp = created_at or datetime.now(timezone.utc)
        return cls(
            day=snapshot.day,
            chunk_count=len(snapshot.chunks),
            site_count=len(snapshot.sites),
            created_at=timestamp,
            summary=summary,
        )


__all__ = [
    "AttentionCurveModel",
    "ChunkSnapshot",
    "ChunkTileModel",
    "SiteSnapshot",
    "WorldSnapshot",
    "WorldSnapshotMetadata",
]
