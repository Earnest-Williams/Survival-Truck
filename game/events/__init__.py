"""Event system utilities."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - imported only for type checkers
    from .event_queue import EventQueue, QueuedEvent

__all__ = ["EventQueue", "QueuedEvent"]

_EXPORTS = {
    "EventQueue": "game.events.event_queue",
    "QueuedEvent": "game.events.event_queue",
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
