"""Text-based user interface components for Survival Truck."""

from .channels import LogEntry, NotificationChannel, NotificationRecord, TurnLogChannel
from .control_panel import ControlPanel, ControlPanelWidget
from .dashboard import DashboardView, TurnLogWidget
from .diplomacy import DiplomacyView
from .hex_map import HexMapView, MapSelection
from .truck_layout import TruckLayoutView

try:  # pragma: no cover - protects against circular import during tests
    from .app import SurvivalTruckApp, AppConfig
except ImportError:  # pragma: no cover - gracefully degrade when UI app is optional
    SurvivalTruckApp = None  # type: ignore[assignment]
    AppConfig = None  # type: ignore[assignment]

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
