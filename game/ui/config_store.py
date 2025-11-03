from __future__ import annotations

"""Helpers for loading and saving the hex layout configuration.

This module centralises persistence of the hex grid layout.  Rather than
writing directly into the project tree (which can cause permission
problems when the game is packaged or installed system‑wide), the
configuration is stored in a user‑specific directory.  The location is
determined via ``platformdirs.user_config_dir``, falling back to a
relative ``./config`` folder if the user directory cannot be created.
Files are written atomically to minimise the risk of corruption on
application crash or power failure.
"""

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any

from platformdirs import user_config_dir


def _compute_config_path() -> Path:
    """Compute the path used to persist the hex layout configuration.

    When possible the per‑user configuration directory is used (via
    :func:`platformdirs.user_config_dir`), otherwise a local ``config``
    directory is created as a fallback.  This helper ensures the
    directory exists before returning.

    Returns:
        Path: The resolved configuration file path.
    """
    # Name the subdirectory after the project; avoid spaces to keep
    # platform conventions consistent across operating systems.
    config_filename = "hex_layout.json"
    try:
        base = Path(user_config_dir("survival_truck"))
        base.mkdir(parents=True, exist_ok=True)
        return base / config_filename
    except Exception:
        # If anything goes wrong (e.g. environment issues or permissions),
        # fall back to a local relative directory.
        fallback_dir = Path("config")
        fallback_dir.mkdir(parents=True, exist_ok=True)
        return fallback_dir / config_filename


# Compute the configuration path at import time.  Other modules may
# import CONFIG_PATH to refer to the resolved file location.
CONFIG_PATH: Path = _compute_config_path()


@dataclass
class HexLayoutConfig:
    """Dataclass representing the adjustable parameters of the hex grid.

    A ``HexLayoutConfig`` instance holds the current layout settings for
    the map (orientation, size, flattening ratio, origin offset and
    offset mode).  It also tracks whether changes have been made since
    the last save via the ``dirty`` attribute.  When loading from disk
    the configuration is marked clean; any modifications performed by the
    UI should set ``dirty`` to ``True``.  The ``save`` method will
    reset the flag back to ``False`` on success.
    """

    # Layout parameters.  Default values match the original config.
    orientation: str = "pointy"  # "pointy" | "flat"
    hex_height: float = 36.0
    # Adjust the default flatten ratio to compensate for the aspect ratio of
    # terminal characters.  Monospace fonts are typically taller than
    # they are wide, so a smaller flatten value compresses the hex vertically
    # and yields a more regular shape.  The range of allowable values is
    # controlled by HexCanvas (see flatten_increase/decrease actions).
    flatten: float = 0.55
    origin_x: float = 8.0
    origin_y: float = 8.0
    offset_mode: str = "odd-r"

    # Track unsaved changes.  This field is not persisted to disk.
    dirty: bool = False

    @classmethod
    def load(cls) -> "HexLayoutConfig":
        """Load the configuration from disk, creating it if necessary.

        Returns:
            HexLayoutConfig: The loaded (or default) configuration.  The
                returned instance will have ``dirty`` set to ``False``.
        """
        path = CONFIG_PATH
        if path.exists():
            try:
                data = json.loads(path.read_text())
                # Merge defaults with persisted values so any new
                # attributes are initialised to sensible defaults.  Do
                # not pass through private attributes like ``dirty``.
                merged: Dict[str, Any] = {**cls().__dict__}
                merged.update(data)
                # Load persisted values, clamping flatten into the allowed range.
                flatten_val = float(merged.get("flatten", 0.55))
                flatten_val = min(max(flatten_val, 0.30), 1.10)
                inst = cls(
                    orientation=merged.get("orientation", "pointy"),
                    hex_height=float(merged.get("hex_height", 36.0)),
                    flatten=flatten_val,
                    origin_x=float(merged.get("origin_x", 8.0)),
                    origin_y=float(merged.get("origin_y", 8.0)),
                    offset_mode=str(merged.get("offset_mode", "odd-r")),
                )
                inst.dirty = False
                return inst
            except Exception:
                # Invalid JSON or other error – fall back to defaults.
                pass
        inst = cls()
        # Attempt to write the new config file.  Use a temporary file and
        # rename to minimise the chance of partial writes.
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_suffix(path.suffix + ".tmp")
            temp_path.write_text(json.dumps(inst.to_dict(), indent=2))
            temp_path.replace(path)
        except Exception:
            # If writing fails, swallow the error – the in‑memory
            # configuration can still be used.
            pass
        inst.dirty = False
        return inst

    def save(self) -> None:
        """Persist the current configuration to disk.

        Writes the configuration to a temporary file before replacing
        the existing file on disk.  On success the ``dirty`` flag is
        cleared.  The ``dirty`` attribute itself is not written to the
        file.
        """
        path = CONFIG_PATH
        data = json.dumps(self.to_dict(), indent=2)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_suffix(path.suffix + ".tmp")
            temp_path.write_text(data)
            temp_path.replace(path)
            self.dirty = False
        except Exception:
            # Fall back to a direct write if atomic rename fails.
            try:
                path.write_text(data)
                self.dirty = False
            except Exception:
                # If we still can't write, leave dirty flag unchanged
                pass

    def to_dict(self) -> dict[str, Any]:
        """Return a serialisable representation of the layout.

        The ``dirty`` attribute is intentionally omitted so that it is
        never persisted to disk.
        """
        return {
            "orientation": self.orientation,
            "hex_height": self.hex_height,
            "flatten": self.flatten,
            "origin_x": self.origin_x,
            "origin_y": self.origin_y,
            "offset_mode": self.offset_mode,
        }

    def reset(self) -> None:
        """Revert all settings to their default values.

        This method replaces the current values with those defined in
        the class defaults and marks the configuration as dirty so that
        the UI can prompt the user to save changes.
        """
        default = type(self)()
        # Copy each field explicitly to avoid overwriting unexpected
        # attributes such as ``dirty``.
        self.orientation = default.orientation
        self.hex_height = default.hex_height
        self.flatten = default.flatten
        self.origin_x = default.origin_x
        self.origin_y = default.origin_y
        self.offset_mode = default.offset_mode
        self.dirty = True