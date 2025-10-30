"""Game engine modules."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - imported only for type checkers
    from .resource_pipeline import ResourceLogEntry, ResourcePipeline
    from .turn_engine import TurnContext, TurnEngine
    from .world import (
        CrewAdvancementSystem,
        CrewComponent,
        FactionAISystem,
        FactionControllerComponent,
        GameWorld,
        SitesComponent,
        TruckComponent,
        TruckMaintenanceSystem,
    )

__all__ = [
    "CrewAdvancementSystem",
    "CrewComponent",
    "FactionAISystem",
    "FactionControllerComponent",
    "GameWorld",
    "ResourceLogEntry",
    "ResourcePipeline",
    "SitesComponent",
    "TruckComponent",
    "TruckMaintenanceSystem",
    "TurnContext",
    "TurnEngine",
]

_EXPORTS = {
    "ResourceLogEntry": "game.engine.resource_pipeline",
    "ResourcePipeline": "game.engine.resource_pipeline",
    "TurnContext": "game.engine.turn_engine",
    "TurnEngine": "game.engine.turn_engine",
    "CrewAdvancementSystem": "game.engine.world",
    "CrewComponent": "game.engine.world",
    "FactionAISystem": "game.engine.world",
    "FactionControllerComponent": "game.engine.world",
    "GameWorld": "game.engine.world",
    "SitesComponent": "game.engine.world",
    "TruckComponent": "game.engine.world",
    "TruckMaintenanceSystem": "game.engine.world",
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
