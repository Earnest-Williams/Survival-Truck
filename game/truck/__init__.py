"""Domain models for the modular survival truck."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - imported only for type checkers
    from .inventory import (
        InsufficientInventoryError,
        Inventory,
        InventoryCapacityError,
        InventoryItem,
        InventoryItemNotFoundError,
        ItemCategory,
        SpoilageState,
    )
    from .models import (
        CrewOverloadError,
        Dimensions,
        MaintenanceReport,
        ModuleCapacityError,
        ModuleNotEquippedError,
        Truck,
        TruckModule,
        TruckStats,
    )

__all__ = [
    "CrewOverloadError",
    "Dimensions",
    "MaintenanceReport",
    "ModuleCapacityError",
    "ModuleNotEquippedError",
    "Truck",
    "TruckModule",
    "TruckStats",
    "InsufficientInventoryError",
    "Inventory",
    "InventoryCapacityError",
    "InventoryItem",
    "InventoryItemNotFoundError",
    "ItemCategory",
    "SpoilageState",
]

_EXPORTS = {
    "InsufficientInventoryError": "game.truck.inventory",
    "Inventory": "game.truck.inventory",
    "InventoryCapacityError": "game.truck.inventory",
    "InventoryItem": "game.truck.inventory",
    "InventoryItemNotFoundError": "game.truck.inventory",
    "ItemCategory": "game.truck.inventory",
    "SpoilageState": "game.truck.inventory",
    "CrewOverloadError": "game.truck.models",
    "Dimensions": "game.truck.models",
    "MaintenanceReport": "game.truck.models",
    "ModuleCapacityError": "game.truck.models",
    "ModuleNotEquippedError": "game.truck.models",
    "Truck": "game.truck.models",
    "TruckModule": "game.truck.models",
    "TruckStats": "game.truck.models",
}


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        module = import_module(_EXPORTS[name])
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
