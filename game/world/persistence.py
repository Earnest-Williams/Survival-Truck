"""Persistence helpers for Survival Truck.

This module provides functions to save and load the game's simulation
state in a consolidated fashion.  Unlike the upstream project, which
stores daily diffs and seasonal snapshots separately, these helpers
persist all relevant data—dynamic world state entries (events,
missions, negotiations), and faction‑specific data (ideology weights,
behavioural traits, reputation)—into a single JSON file per save slot.

On save, a JSON‑serialisable structure is constructed containing the
current ``world_state`` and a mapping of faction names to their
ideology weight distributions, trait values and reputation.  On
load, the structure is read back and returned to the caller for
merging into the active simulation.

The save files are stored in a platform‑appropriate user data
directory using ``platformdirs.user_data_dir``.  Each slot has its
own file named ``<slot>_save.json``.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Mapping, Tuple

try:
    # ``platformdirs`` is an optional dependency, but recommended for
    # locating OS‑specific user data directories.  If not available,
    # fall back to the current working directory.
    from platformdirs import user_data_dir
except Exception:
    user_data_dir = None  # type: ignore[assignment]


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