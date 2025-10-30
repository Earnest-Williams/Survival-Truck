"""Text-based user interface components for Survival Truck."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - imported only for type checkers
    from .app import AppConfig, SurvivalTruckApp
    from .channels import LogEntry, NotificationChannel, NotificationRecord, TurnLogChannel
    from .control_panel import ControlPanel, ControlPanelWidget
    from .dashboard import DashboardView, TurnLogWidget
    from .diplomacy import DiplomacyView
    from .hex_map import HexMapView, MapSelection
    from .truck_layout import TruckLayoutView

__all__ = [
    "AppConfig",
    "ControlPanel",
    "ControlPanelWidget",
    "DashboardView",
    "DiplomacyView",
    "HexMapView",
    "LogEntry",
    "MapSelection",
    "NotificationChannel",
    "NotificationRecord",
    "SurvivalTruckApp",
    "TurnLogChannel",
    "TurnLogWidget",
    "TruckLayoutView",
]

_EAGER_EXPORTS = {
    "LogEntry": "game.ui.channels",
    "NotificationChannel": "game.ui.channels",
    "NotificationRecord": "game.ui.channels",
    "TurnLogChannel": "game.ui.channels",
    "ControlPanel": "game.ui.control_panel",
    "ControlPanelWidget": "game.ui.control_panel",
    "DashboardView": "game.ui.dashboard",
    "TurnLogWidget": "game.ui.dashboard",
    "DiplomacyView": "game.ui.diplomacy",
    "HexMapView": "game.ui.hex_map",
    "MapSelection": "game.ui.hex_map",
    "TruckLayoutView": "game.ui.truck_layout",
}

_OPTIONAL_EXPORTS = {
    "AppConfig": "game.ui.app",
    "SurvivalTruckApp": "game.ui.app",
}


def __getattr__(name: str) -> Any:
    if name in _EAGER_EXPORTS:
        module = import_module(_EAGER_EXPORTS[name])
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name in _OPTIONAL_EXPORTS:
        try:
            module = import_module(_OPTIONAL_EXPORTS[name])
        except ImportError:  # pragma: no cover - optional dependency not installed
            globals()[name] = None
            return None
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
