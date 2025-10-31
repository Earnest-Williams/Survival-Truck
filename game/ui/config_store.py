from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path("config/hex_layout.json")


@dataclass
class HexLayoutConfig:
    orientation: str = "pointy"   # "pointy" | "flat"
    hex_height: float = 36.0
    flatten: float = 0.88
    origin_x: float = 8.0
    origin_y: float = 8.0
    offset_mode: str = "odd-r"

    @classmethod
    def load(cls) -> "HexLayoutConfig":
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text())
            return cls(**{**cls().__dict__, **data})
        inst = cls()
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(inst.__dict__, indent=2))
        return inst

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(self.__dict__, indent=2))
