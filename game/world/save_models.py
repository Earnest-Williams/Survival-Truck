"""Pydantic models describing world snapshot payloads."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Dict, List

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .map import BiomeType, ChunkCoord, MapChunk
from .sites import AttentionCurve, Site, SiteType

_SIMPLE_TYPES = (str, int, float, bool)
_DROP = object()


def _coerce_json(value: object) -> object:
    """Convert ``value`` into a msgpack-friendly structure or ``_DROP``."""

    if value is None or isinstance(value, _SIMPLE_TYPES):
        return value
    if isinstance(value, Mapping):
        result: Dict[str, object] = {}
        dropped = False
        for key, item in value.items():
            coerced = _coerce_json(item)
            if coerced is _DROP:
                dropped = True
                continue
            result[str(key)] = coerced
        if result or not value or not dropped:
            return result
        return _DROP
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result_list: List[object] = []
        dropped = False
        for item in value:
            coerced = _coerce_json(item)
            if coerced is _DROP:
                dropped = True
                continue
            result_list.append(coerced)
        if result_list or not value or not dropped:
            return result_list
        return _DROP
    if is_dataclass(value):
        return _coerce_json(asdict(value))
    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        return _coerce_json(value.to_dict())
    if hasattr(value, "__dict__"):
        return _coerce_json(vars(value))
    return _DROP


class HexPointModel(BaseModel):
    """Serializable axial coordinate used in world-state payloads."""

    model_config = ConfigDict(extra="forbid")

    q: int
    r: int

    @model_validator(mode="before")
    @classmethod
    def _coerce_tuple(cls, value: object) -> Mapping[str, object] | object:
        if isinstance(value, Mapping):
            return value
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            sequence = list(value)
            if len(sequence) >= 2:
                return {"q": int(sequence[0]), "r": int(sequence[1])}
        return value


class TravelReportModel(BaseModel):
    """Serializable travel cost record stored in ``world_state``."""

    model_config = ConfigDict(extra="ignore")

    day: int = Field(ge=0)
    base_cost: float
    modifier: float
    load_factor: float
    adjusted_cost: float

    @field_validator("base_cost", "modifier", "load_factor", "adjusted_cost")
    @classmethod
    def _ensure_float(cls, value: object) -> float:
        return float(value)


class WeatherRecordModel(BaseModel):
    """Serializable daily weather snapshot."""

    model_config = ConfigDict(extra="ignore")

    day: int = Field(ge=0)
    condition: str
    travel_modifier: float
    maintenance_modifier: float

    @field_validator("travel_modifier", "maintenance_modifier")
    @classmethod
    def _ensure_float(cls, value: object) -> float:
        return float(value)


class ResourceLogEntryModel(BaseModel):
    """Serializable representation of :class:`ResourceLogEntry`."""

    model_config = ConfigDict(extra="ignore")

    phase: str
    source: str
    consumed: Dict[str, float] = Field(default_factory=dict)
    produced: Dict[str, float] = Field(default_factory=dict)
    notes: Dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _from_object(cls, value: object) -> Mapping[str, object] | object:
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return value
        if is_dataclass(value):
            return asdict(value)
        if hasattr(value, "__dict__"):
            return vars(value)
        return value

    @field_validator("consumed", "produced", mode="before")
    @classmethod
    def _normalise_resource_map(cls, value: object) -> Dict[str, float]:
        if value in (None, {}):
            return {}
        if not isinstance(value, Mapping):
            raise TypeError("resource map must be a mapping of resource ids to quantities")
        normalised: Dict[str, float] = {}
        for key, amount in value.items():
            normalised[str(key)] = float(amount)
        return normalised

    @field_validator("notes", mode="before")
    @classmethod
    def _normalise_notes(cls, value: object) -> Dict[str, object]:
        if value in (None, {}):
            return {}
        if not isinstance(value, Mapping):
            coerced = _coerce_json(value)
            return {} if coerced is _DROP or not isinstance(coerced, Mapping) else coerced
        result: Dict[str, object] = {}
        for key, entry in value.items():
            coerced = _coerce_json(entry)
            if coerced is _DROP:
                continue
            result[str(key)] = coerced
        return result


class SiteGraphModel(BaseModel):
    """Serializable site connectivity information."""

    model_config = ConfigDict(extra="ignore")

    positions: Dict[str, HexPointModel] = Field(default_factory=dict)
    connections: Dict[str, Dict[str, float]] = Field(default_factory=dict)

    @field_validator("connections", mode="before")
    @classmethod
    def _coerce_connections(cls, value: object) -> Dict[str, Dict[str, float]]:
        if value in (None, {}):
            return {}
        if not isinstance(value, Mapping):
            raise TypeError("site graph connections must be a mapping")
        result: Dict[str, Dict[str, float]] = {}
        for key, mapping in value.items():
            if not isinstance(mapping, Mapping):
                continue
            inner: Dict[str, float] = {}
            for neighbour, cost in mapping.items():
                inner[str(neighbour)] = float(cost)
            result[str(key)] = inner
        return result


class WorldStatePayload(BaseModel):
    """Structured payload capturing persisted ``world_state`` entries."""

    model_config = ConfigDict(extra="forbid")

    notes: List[str] = Field(default_factory=list)
    progress: Dict[str, float] = Field(default_factory=dict)
    season_state: str | None = None
    site_graph: SiteGraphModel | None = None
    planned_route: List[str] = Field(default_factory=list)
    module_orders: List[str] = Field(default_factory=list)
    crew_assignments: List[str] = Field(default_factory=list)
    travel_reports: List[TravelReportModel] = Field(default_factory=list)
    last_travel_cost: TravelReportModel | None = None
    resource_events: List[ResourceLogEntryModel] = Field(default_factory=list)
    weather: WeatherRecordModel | None = None
    weather_history: List[WeatherRecordModel] = Field(default_factory=list)
    other_state: Dict[str, object] = Field(default_factory=dict)

    @field_validator("notes", mode="before")
    @classmethod
    def _normalise_notes(cls, value: object) -> List[str]:
        if value in (None, []):
            return []
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            return [str(value)]
        return [str(entry) for entry in value]

    @field_validator("progress", mode="before")
    @classmethod
    def _normalise_progress(cls, value: object) -> Dict[str, float]:
        if value in (None, {}):
            return {}
        if not isinstance(value, Mapping):
            raise TypeError("progress must be a mapping of task names to values")
        normalised: Dict[str, float] = {}
        for key, amount in value.items():
            normalised[str(key)] = float(amount)
        return normalised

    @field_validator("planned_route", "module_orders", "crew_assignments", mode="before")
    @classmethod
    def _normalise_strings(cls, value: object) -> List[str]:
        if value in (None, []):
            return []
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            return [str(value)]
        return [str(entry) for entry in value]

    @field_validator("other_state", mode="before")
    @classmethod
    def _ensure_mapping(cls, value: object) -> Dict[str, object]:
        if value in (None, {}):
            return {}
        if not isinstance(value, Mapping):
            raise TypeError("other_state must be a mapping")
        result: Dict[str, object] = {}
        for key, entry in value.items():
            coerced = _coerce_json(entry)
            if coerced is _DROP:
                continue
            result[str(key)] = coerced
        return result

    @classmethod
    def from_mapping(cls, state: Mapping[str, object] | None) -> "WorldStatePayload":
        if not state:
            return cls()
        field_names = set(cls.model_fields)
        field_names.discard("other_state")
        payload: Dict[str, object] = {}
        extras: Dict[str, object] = {}
        for key, value in state.items():
            if key == "sites":
                continue
            if key in field_names:
                payload[key] = value
            else:
                coerced = _coerce_json(value)
                if coerced is _DROP:
                    continue
                extras[str(key)] = coerced
        payload["other_state"] = extras
        return cls.model_validate(payload)

    def to_serializable_dict(self) -> Dict[str, object]:
        data = self.model_dump(
            mode="json",
            exclude={"other_state"},
            exclude_none=True,
        )
        serializable: Dict[str, object] = dict(self.other_state)
        for key, value in data.items():
            if value in (None, [], {}):
                continue
            serializable[key] = value
        return serializable

    def to_state_dict(self) -> Dict[str, object]:
        base = self.to_serializable_dict()
        return base


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

    peak: float = 1.0
    mu: float = 50.0
    sigma: float = Field(default=15.0, gt=0.0)

    @field_validator("peak", "mu", "sigma")
    @classmethod
    def _coerce_float(cls, value: float) -> float:
        return float(value)

    @classmethod
    def from_domain(cls, curve: AttentionCurve) -> "AttentionCurveModel":
        return cls(peak=curve.peak, mu=curve.mu, sigma=curve.sigma)

    def to_domain(self) -> AttentionCurve:
        return AttentionCurve(peak=self.peak, mu=self.mu, sigma=self.sigma)


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
        payload = WorldStatePayload.from_mapping(world_state)
        sanitized_state = payload.to_serializable_dict()
        return cls(day=day, chunks=chunk_models, sites=site_models, world_state=sanitized_state)

    def to_chunks(self) -> List[MapChunk]:
        return [chunk.to_chunk() for chunk in self.chunks]

    def to_site_map(self) -> Dict[str, Site]:
        return {site.identifier: site.to_site() for site in self.sites}

    def to_world_state(self) -> Dict[str, object]:
        payload = WorldStatePayload.from_mapping(self.world_state)
        state = payload.to_state_dict()
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
    "ResourceLogEntryModel",
    "SiteGraphModel",
    "SiteSnapshot",
    "TravelReportModel",
    "WorldSnapshot",
    "WorldSnapshotMetadata",
    "WorldStatePayload",
    "WeatherRecordModel",
]
