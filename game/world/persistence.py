"""Persistence helpers for world map chunks, site state, and save slots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, Sequence, Tuple, Type, TypeVar

import msgpack
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel, create_engine, select

from .config import WorldConfig
from .map import MapChunk
from .save_models import ChunkSnapshot, SiteSnapshot, WorldSnapshot, WorldSnapshotMetadata
from .sites import Site

__all__ = [
    "WorldConfigRecord",
    "WorldDailyDiffRecord",
    "WorldSeasonSnapshotRecord",
    "SeasonSnapshotEntry",
    "create_world_engine",
    "init_world_storage",
    "load_daily_diff",
    "load_season_snapshot",
    "load_world_config",
    "serialize_chunk",
    "serialize_chunks",
    "serialize_site",
    "serialize_sites",
    "store_daily_diff",
    "store_season_snapshot",
    "store_world_config",
    "deserialize_chunk",
    "deserialize_chunks",
    "deserialize_site",
    "deserialize_sites",
    "iter_daily_diffs",
    "iter_season_snapshots",
]

_M = TypeVar("_M", bound=BaseModel)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pack_model(model: BaseModel) -> bytes:
    payload = model.model_dump(mode="json")
    return msgpack.packb(payload, use_bin_type=True)


def _unpack_model(payload: bytes, model_type: Type[_M]) -> _M:
    data = msgpack.unpackb(payload, raw=False)
    return model_type.model_validate(data)


class WorldConfigRecord(SQLModel, table=True):
    """SQLModel table storing configuration payloads."""

    __tablename__ = "world_configs"

    id: int | None = Field(default=None, primary_key=True)
    slot: str = Field(sa_column=Column(String(128), unique=True, index=True, nullable=False))
    payload: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    created_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class WorldDailyDiffRecord(SQLModel, table=True):
    """SQLModel table storing daily snapshot blobs."""

    __tablename__ = "world_daily_diffs"
    __table_args__ = (UniqueConstraint("slot", "day", name="uq_world_daily_slot_day"),)

    id: int | None = Field(default=None, primary_key=True)
    slot: str = Field(sa_column=Column(String(128), index=True, nullable=False))
    day: int = Field(sa_column=Column(Integer, nullable=False))
    metadata_blob: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    snapshot_blob: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    created_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class WorldSeasonSnapshotRecord(SQLModel, table=True):
    """SQLModel table storing seasonal full snapshot blobs."""

    __tablename__ = "world_season_snapshots"
    __table_args__ = (UniqueConstraint("slot", "day", name="uq_world_season_slot_day"),)

    id: int | None = Field(default=None, primary_key=True)
    slot: str = Field(sa_column=Column(String(128), index=True, nullable=False))
    day: int = Field(sa_column=Column(Integer, nullable=False))
    season: str | None = Field(sa_column=Column(String(64), nullable=True))
    metadata_blob: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    snapshot_blob: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    created_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))


@dataclass(frozen=True)
class SeasonSnapshotEntry:
    """Loaded seasonal snapshot tuple."""

    season: str | None
    metadata: WorldSnapshotMetadata
    snapshot: WorldSnapshot


def create_world_engine(path: str | Path, *, echo: bool = False) -> Engine:
    """Return a SQLite engine for the provided ``path``."""

    if isinstance(path, str) and path == ":memory:":
        url = "sqlite:///:memory:"
    else:
        database_path = Path(path)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{database_path.as_posix()}"
    return create_engine(url, echo=echo, connect_args={"check_same_thread": False})


def init_world_storage(engine: Engine) -> None:
    """Ensure all persistence tables exist for ``engine``."""

    SQLModel.metadata.create_all(engine)


def store_world_config(engine: Engine, slot: str, config: WorldConfig) -> None:
    """Persist ``config`` under ``slot``."""

    payload = _pack_model(config)
    now = _now()
    with Session(engine) as session:
        record = session.exec(select(WorldConfigRecord).where(WorldConfigRecord.slot == slot)).first()
        if record is None:
            record = WorldConfigRecord(slot=slot, payload=payload, created_at=now, updated_at=now)
            session.add(record)
        else:
            record.payload = payload
            record.updated_at = now
        session.commit()


def load_world_config(engine: Engine, slot: str) -> WorldConfig | None:
    """Return the stored :class:`WorldConfig` for ``slot`` if present."""

    with Session(engine) as session:
        record = session.exec(select(WorldConfigRecord).where(WorldConfigRecord.slot == slot)).first()
        if record is None:
            return None
        return _unpack_model(record.payload, WorldConfig)


def store_daily_diff(
    engine: Engine,
    slot: str,
    snapshot: WorldSnapshot,
    *,
    metadata: WorldSnapshotMetadata | None = None,
) -> WorldSnapshotMetadata:
    """Persist ``snapshot`` as the diff for ``slot`` and ``snapshot.day``."""

    meta = metadata or snapshot.metadata()
    snapshot_blob = _pack_model(snapshot)
    metadata_blob = _pack_model(meta)
    now = _now()
    with Session(engine) as session:
        statement = select(WorldDailyDiffRecord).where(
            (WorldDailyDiffRecord.slot == slot) & (WorldDailyDiffRecord.day == snapshot.day)
        )
        record = session.exec(statement).first()
        if record is None:
            record = WorldDailyDiffRecord(
                slot=slot,
                day=snapshot.day,
                metadata_blob=metadata_blob,
                snapshot_blob=snapshot_blob,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
        else:
            record.metadata_blob = metadata_blob
            record.snapshot_blob = snapshot_blob
            record.updated_at = now
        session.commit()
    return meta


def store_season_snapshot(
    engine: Engine,
    slot: str,
    snapshot: WorldSnapshot,
    *,
    season: str | None = None,
    metadata: WorldSnapshotMetadata | None = None,
) -> WorldSnapshotMetadata:
    """Persist ``snapshot`` as the seasonal baseline for ``slot`` at ``snapshot.day``."""

    summary: str | None = None
    if metadata is None and season:
        summary = f"{season.title()} season snapshot (day {snapshot.day})"
    meta = metadata or snapshot.metadata(summary=summary)
    snapshot_blob = _pack_model(snapshot)
    metadata_blob = _pack_model(meta)
    now = _now()
    with Session(engine) as session:
        statement = select(WorldSeasonSnapshotRecord).where(
            (WorldSeasonSnapshotRecord.slot == slot) & (WorldSeasonSnapshotRecord.day == snapshot.day)
        )
        record = session.exec(statement).first()
        if record is None:
            record = WorldSeasonSnapshotRecord(
                slot=slot,
                day=snapshot.day,
                season=season,
                metadata_blob=metadata_blob,
                snapshot_blob=snapshot_blob,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
        else:
            record.season = season
            record.metadata_blob = metadata_blob
            record.snapshot_blob = snapshot_blob
            record.updated_at = now
        session.commit()
    return meta


def load_daily_diff(engine: Engine, slot: str, day: int) -> Tuple[WorldSnapshotMetadata, WorldSnapshot] | None:
    """Load the snapshot and metadata for ``slot`` on ``day`` if present."""

    statement = select(WorldDailyDiffRecord).where(
        (WorldDailyDiffRecord.slot == slot) & (WorldDailyDiffRecord.day == day)
    )
    with Session(engine) as session:
        record = session.exec(statement).first()
        if record is None:
            return None
        metadata = _unpack_model(record.metadata_blob, WorldSnapshotMetadata)
        snapshot = _unpack_model(record.snapshot_blob, WorldSnapshot)
        return metadata, snapshot


def load_season_snapshot(
    engine: Engine, slot: str, day: int
) -> SeasonSnapshotEntry | None:
    """Load the seasonal snapshot for ``slot`` on ``day`` if present."""

    statement = select(WorldSeasonSnapshotRecord).where(
        (WorldSeasonSnapshotRecord.slot == slot) & (WorldSeasonSnapshotRecord.day == day)
    )
    with Session(engine) as session:
        record = session.exec(statement).first()
        if record is None:
            return None
        metadata = _unpack_model(record.metadata_blob, WorldSnapshotMetadata)
        snapshot = _unpack_model(record.snapshot_blob, WorldSnapshot)
        return SeasonSnapshotEntry(record.season, metadata, snapshot)


def iter_daily_diffs(engine: Engine, slot: str) -> Iterator[Tuple[WorldSnapshotMetadata, WorldSnapshot]]:
    """Iterate over stored diffs ordered by day for ``slot``."""

    statement = (
        select(WorldDailyDiffRecord)
        .where(WorldDailyDiffRecord.slot == slot)
        .order_by(WorldDailyDiffRecord.day)
    )
    with Session(engine) as session:
        for record in session.exec(statement):
            metadata = _unpack_model(record.metadata_blob, WorldSnapshotMetadata)
            snapshot = _unpack_model(record.snapshot_blob, WorldSnapshot)
            yield metadata, snapshot


def iter_season_snapshots(engine: Engine, slot: str) -> Iterator[SeasonSnapshotEntry]:
    """Iterate over stored seasonal snapshots ordered by day for ``slot``."""

    statement = (
        select(WorldSeasonSnapshotRecord)
        .where(WorldSeasonSnapshotRecord.slot == slot)
        .order_by(WorldSeasonSnapshotRecord.day)
    )
    with Session(engine) as session:
        for record in session.exec(statement):
            metadata = _unpack_model(record.metadata_blob, WorldSnapshotMetadata)
            snapshot = _unpack_model(record.snapshot_blob, WorldSnapshot)
            yield SeasonSnapshotEntry(record.season, metadata, snapshot)


def serialize_chunk(chunk: MapChunk) -> Dict[str, object]:
    """Serialize a :class:`MapChunk` into a JSON-friendly mapping."""

    return ChunkSnapshot.from_chunk(chunk).model_dump(mode="json")


def deserialize_chunk(payload: Mapping[str, object]) -> MapChunk:
    """Reconstruct a :class:`MapChunk` from ``payload``."""

    snapshot = ChunkSnapshot.model_validate(payload)
    return snapshot.to_chunk()


def serialize_chunks(chunks: Iterable[MapChunk]) -> List[Dict[str, object]]:
    """Serialize ``chunks`` into a list of mappings."""

    return [serialize_chunk(chunk) for chunk in chunks]


def deserialize_chunks(payload: Sequence[Mapping[str, object]]) -> List[MapChunk]:
    """Deserialize a sequence of chunk payloads back into :class:`MapChunk` objects."""

    return [deserialize_chunk(item) for item in payload]


def serialize_site(site: Site) -> Dict[str, object]:
    """Serialize a :class:`Site` into a JSON-friendly mapping."""

    return SiteSnapshot.from_site(site).model_dump(mode="json")


def deserialize_site(payload: Mapping[str, object]) -> Site:
    """Reconstruct a :class:`Site` from ``payload``."""

    snapshot = SiteSnapshot.model_validate(payload)
    return snapshot.to_site()


def serialize_sites(sites: Iterable[Site]) -> List[Dict[str, object]]:
    """Serialize a collection of :class:`Site` objects."""

    return [serialize_site(site) for site in sites]


def deserialize_sites(payload: Sequence[Mapping[str, object]]) -> List[Site]:
    """Deserialize serialized site payloads."""

    return [deserialize_site(item) for item in payload]
