"""Persistence helpers for Survival Truck.

Two persistence strategies are supported:

* A light-weight JSON based quick-save facility (``save_game_state`` /
  ``load_game_state``) used by prototypes and debug tooling.
* A structured SQLite storage layer for campaign saves.  The SQLite
  layer stores validated :class:`~game.world.config.WorldConfig`
  payloads as well as daily diffs and seasonal snapshots encoded via
  :class:`~game.world.save_models.WorldSnapshot`.

Historically the project only implemented the JSON helpers.  The tests
exercise the richer SQLite flow, so the functions implemented below
initialise the database schema, serialise payloads to JSON, and surface
convenient iterator/loader utilities.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping, Tuple

try:
    # ``platformdirs`` is an optional dependency, but recommended for
    # locating OS‑specific user data directories.  If not available,
    # fall back to the current working directory.
    from platformdirs import user_data_dir
except Exception:
    user_data_dir = None  # type: ignore[assignment]

from .config import WorldConfig
from .save_models import WorldSnapshot, WorldSnapshotMetadata


# ---------------------------------------------------------------------------
# JSON quick-save helpers
# ---------------------------------------------------------------------------


def _get_save_dir(app_name: str = "survival_truck") -> str:
    """Return the directory used to store save files.

    The directory is created if it does not already exist.  If
    ``platformdirs`` is available, a per‑user data directory is used;
    otherwise, the current working directory is returned.

    Args:
        app_name: The name of the application, used when deriving the
            directory via ``platformdirs``.

    Returns:
        A filesystem path string.
    """
    if user_data_dir is not None:
        path = user_data_dir(app_name, appauthor=False)
    else:
        path = os.getcwd()
    os.makedirs(path, exist_ok=True)
    return path


def _json_safe(obj: Any) -> Any:
    """Convert arbitrary Python objects into JSON‑serialisable values.

    Primitive types (None, bool, int, float, str) are returned as
    is.  Mappings and sequences are processed recursively.  All
    other objects are converted to their string representation.

    Args:
        obj: An arbitrary Python object.

    Returns:
        A JSON‑serialisable representation of ``obj``.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, Mapping):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(item) for item in obj]
    # Fallback: convert to string
    return str(obj)


def save_game_state(
    world_state: Mapping[str, Any],
    faction_controller: Any,
    *,
    slot: str = "default",
    app_name: str = "survival_truck",
) -> None:
    """Persist the current game state to a JSON file.

    The ``world_state`` is filtered through ``_json_safe`` to ensure
    that all values are JSON‑serialisable.  Faction data is collected
    from the provided ``faction_controller`` via its ledger, including
    ideology weights, behavioural traits and reputation for each
    faction.  The resulting structure is written to a file named
    ``<slot>_save.json`` in the user data directory.

    Args:
        world_state: The global state dictionary shared across game
            systems.
        faction_controller: The FactionAIController instance whose
            ledger stores faction information.  It must expose
            ``factions`` (mapping) and ``ledger`` (FactionLedger).
        slot: An identifier for the save slot (default "default").
        app_name: The application name used to compute the save
            directory.  Defaults to "survival_truck".
    """
    try:
        save_dir = _get_save_dir(app_name)
        filepath = os.path.join(save_dir, f"{slot}_save.json")
        # Assemble faction data
        factions_data: Dict[str, Dict[str, Any]] = {}
        if hasattr(faction_controller, "factions") and hasattr(faction_controller, "ledger"):
            ledger = getattr(faction_controller, "ledger")
            factions_map = getattr(faction_controller, "factions")
            try:
                trait_names = list(getattr(ledger, "DEFAULT_TRAITS", []))
            except Exception:
                trait_names = []
            for name, rec in factions_map.items():
                # Ideology weights
                try:
                    ide_weights = ledger.ideology_weights(name)
                except Exception:
                    ide_weights = {}
                # Traits
                traits: Dict[str, float] = {}
                for t_name in trait_names:
                    try:
                        traits[t_name] = float(ledger.get_trait(name, t_name, 0.0))
                    except Exception:
                        traits[t_name] = 0.0
                # Reputation (may be stored on FactionRecord)
                try:
                    rep = float(getattr(rec, "reputation", 0.0))
                except Exception:
                    rep = 0.0
                factions_data[name] = {
                    "ideology_weights": ide_weights,
                    "traits": traits,
                    "reputation": rep,
                }
        # Filter world_state to JSON‑safe content
        safe_state = {}
        for key, val in world_state.items():
            # Skip objects known to be non‑serialisable (e.g. randomness
            # generators).  We persist only those keys relevant to
            # simulation continuity.
            if key in {"randomness", "rng", "_rng"}:
                continue
            safe_state[key] = _json_safe(val)
        data = {
            "world_state": safe_state,
            "factions": factions_data,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        # Fail silently: persistence is best effort.  Errors can be
        # surfaced via the caller's notification channel if desired.
        return


def load_game_state(
    *, slot: str = "default", app_name: str = "survival_truck"
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Load a previously saved game state.

    This function attempts to read ``<slot>_save.json`` from the user
    data directory and return the stored ``world_state`` and
    ``factions`` structures.  If the file is missing or cannot be
    parsed, empty structures are returned.

    Args:
        slot: Identifier for the save slot.
        app_name: Application name used to compute the save directory.

    Returns:
        A tuple ``(world_state, factions)``.  Each entry is a
        dictionary.  Callers should merge ``world_state`` into their
        active state and use the ``factions`` mapping to restore
        ideology weights, traits and reputation on the ledger.
    """
    try:
        save_dir = _get_save_dir(app_name)
        filepath = os.path.join(save_dir, f"{slot}_save.json")
        if not os.path.exists(filepath):
            return {}, {}
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        world_state = data.get("world_state", {})
        factions = data.get("factions", {})
        if not isinstance(world_state, dict):
            world_state = {}
        if not isinstance(factions, dict):
            factions = {}
        return world_state, factions
    except Exception:
        return {}, {}


# ---------------------------------------------------------------------------
# SQLite campaign storage helpers
# ---------------------------------------------------------------------------

ConnectionLike = sqlite3.Connection


@dataclass(frozen=True)
class SeasonalSnapshotRecord:
    """Container returned by :func:`load_season_snapshot` and iterator helpers."""

    season: str
    metadata: WorldSnapshotMetadata
    snapshot: WorldSnapshot


def create_world_engine(path: os.PathLike[str] | str) -> ConnectionLike:
    """Create a SQLite connection for world persistence.

    The parent directory is created automatically.  The connection has
    row access by column name enabled for convenience.
    """

    db_path = Path(path)
    if not db_path.parent.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _require_connection(engine: ConnectionLike) -> ConnectionLike:
    if isinstance(engine, sqlite3.Connection):
        return engine
    raise TypeError("engine must be a sqlite3.Connection produced by create_world_engine")


def init_world_storage(engine: ConnectionLike) -> None:
    """Initialise the SQLite schema used for campaign persistence."""

    connection = _require_connection(engine)
    with connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS world_configs (
                slot TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_diffs (
                slot TEXT NOT NULL,
                day INTEGER NOT NULL,
                metadata TEXT NOT NULL,
                snapshot TEXT NOT NULL,
                PRIMARY KEY (slot, day)
            );

            CREATE TABLE IF NOT EXISTS seasonal_snapshots (
                slot TEXT NOT NULL,
                season TEXT NOT NULL,
                day INTEGER NOT NULL,
                metadata TEXT NOT NULL,
                snapshot TEXT NOT NULL,
                PRIMARY KEY (slot, season, day)
            );
            """
        )


def _dump_json(model: Any) -> str:
    if hasattr(model, "model_dump"):
        return json.dumps(model.model_dump(mode="json"), ensure_ascii=False)
    return json.dumps(model, ensure_ascii=False)


def _load_world_config(payload: str) -> WorldConfig:
    data = json.loads(payload)
    return WorldConfig.model_validate(data)


def _load_snapshot_metadata(payload: str) -> WorldSnapshotMetadata:
    data = json.loads(payload)
    return WorldSnapshotMetadata.model_validate(data)


def _load_snapshot(payload: str) -> WorldSnapshot:
    data = json.loads(payload)
    return WorldSnapshot.model_validate(data)


def store_world_config(engine: ConnectionLike, slot: str, config: WorldConfig) -> None:
    """Persist a :class:`WorldConfig` for the specified slot."""

    connection = _require_connection(engine)
    payload = _dump_json(config)
    with connection:
        connection.execute(
            """
            INSERT INTO world_configs(slot, payload)
            VALUES (?, ?)
            ON CONFLICT(slot) DO UPDATE SET payload = excluded.payload
            """,
            (slot, payload),
        )


def load_world_config(engine: ConnectionLike, slot: str) -> WorldConfig | None:
    """Load the :class:`WorldConfig` for ``slot`` if it exists."""

    connection = _require_connection(engine)
    row = connection.execute(
        "SELECT payload FROM world_configs WHERE slot = ?",
        (slot,),
    ).fetchone()
    if row is None:
        return None
    return _load_world_config(row["payload"])


def store_daily_diff(
    engine: ConnectionLike,
    slot: str,
    snapshot: WorldSnapshot,
) -> WorldSnapshotMetadata:
    """Store a daily diff snapshot and return its metadata."""

    connection = _require_connection(engine)
    metadata = snapshot.metadata()
    with connection:
        connection.execute(
            """
            INSERT INTO daily_diffs(slot, day, metadata, snapshot)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(slot, day) DO UPDATE SET
                metadata = excluded.metadata,
                snapshot = excluded.snapshot
            """,
            (
                slot,
                metadata.day,
                _dump_json(metadata),
                _dump_json(snapshot),
            ),
        )
    return metadata


def load_daily_diff(
    engine: ConnectionLike,
    slot: str,
    day: int,
) -> tuple[WorldSnapshotMetadata, WorldSnapshot] | None:
    """Load a daily diff for ``slot``/``day``."""

    connection = _require_connection(engine)
    row = connection.execute(
        "SELECT metadata, snapshot FROM daily_diffs WHERE slot = ? AND day = ?",
        (slot, day),
    ).fetchone()
    if row is None:
        return None
    metadata = _load_snapshot_metadata(row["metadata"])
    snapshot = _load_snapshot(row["snapshot"])
    return metadata, snapshot


def iter_daily_diffs(engine: ConnectionLike, slot: str) -> Iterator[tuple[WorldSnapshotMetadata, WorldSnapshot]]:
    """Yield all stored daily diffs for ``slot`` ordered by day."""

    connection = _require_connection(engine)
    cursor = connection.execute(
        "SELECT metadata, snapshot FROM daily_diffs WHERE slot = ? ORDER BY day ASC",
        (slot,),
    )
    for row in cursor:
        yield _load_snapshot_metadata(row["metadata"]), _load_snapshot(row["snapshot"])


def store_season_snapshot(
    engine: ConnectionLike,
    slot: str,
    snapshot: WorldSnapshot,
    *,
    season: str,
) -> WorldSnapshotMetadata:
    """Persist a seasonal snapshot for ``slot`` and return its metadata."""

    connection = _require_connection(engine)
    metadata = snapshot.metadata()
    with connection:
        connection.execute(
            """
            INSERT INTO seasonal_snapshots(slot, season, day, metadata, snapshot)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(slot, season, day) DO UPDATE SET
                metadata = excluded.metadata,
                snapshot = excluded.snapshot
            """,
            (
                slot,
                season,
                metadata.day,
                _dump_json(metadata),
                _dump_json(snapshot),
            ),
        )
    return metadata


def load_season_snapshot(
    engine: ConnectionLike,
    slot: str,
    day: int,
) -> SeasonalSnapshotRecord | None:
    """Load the seasonal snapshot recorded for ``day`` if present."""

    connection = _require_connection(engine)
    row = connection.execute(
        """
        SELECT season, metadata, snapshot
        FROM seasonal_snapshots
        WHERE slot = ? AND day = ?
        ORDER BY rowid DESC
        LIMIT 1
        """,
        (slot, day),
    ).fetchone()
    if row is None:
        return None
    return SeasonalSnapshotRecord(
        season=row["season"],
        metadata=_load_snapshot_metadata(row["metadata"]),
        snapshot=_load_snapshot(row["snapshot"]),
    )


def iter_season_snapshots(engine: ConnectionLike, slot: str) -> Iterator[SeasonalSnapshotRecord]:
    """Yield all seasonal snapshots stored for ``slot`` ordered by day."""

    connection = _require_connection(engine)
    cursor = connection.execute(
        """
        SELECT season, metadata, snapshot
        FROM seasonal_snapshots
        WHERE slot = ?
        ORDER BY day ASC
        """,
        (slot,),
    )
    for row in cursor:
        yield SeasonalSnapshotRecord(
            season=row["season"],
            metadata=_load_snapshot_metadata(row["metadata"]),
            snapshot=_load_snapshot(row["snapshot"]),
        )
