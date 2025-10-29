"""ECS world abstraction for the Survival Truck simulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Protocol,
    Tuple,
    Type,
    TypeVar,
)

import esper

if hasattr(esper, "World"):
    EsperWorld = esper.World
else:  # pragma: no cover - fallback for stripped-down esper installs
    class EsperWorld:
        """Minimal stand-in for :class:`esper.World` used in tests."""

        def __init__(self) -> None:
            self._next_entity = 0
            self._components: Dict[int, Dict[Type[object], object]] = {}

        def create_entity(self, *components: object) -> int:
            entity = self._next_entity
            self._next_entity += 1
            self._components[entity] = {}
            for component in components:
                self.add_component(entity, component)
            return entity

        def add_component(self, entity: int, component: object) -> None:
            self._components.setdefault(entity, {})[type(component)] = component

        def has_component(self, entity: int, component_type: Type[object]) -> bool:
            return component_type in self._components.get(entity, {})

        def remove_component(self, entity: int, component_type: Type[object]) -> None:
            if entity in self._components:
                self._components[entity].pop(component_type, None)

        def component_for_entity(self, entity: int, component_type: Type[T]) -> T:
            try:
                return self._components[entity][component_type]  # type: ignore[return-value]
            except KeyError as exc:  # pragma: no cover - defensive branch
                raise KeyError(component_type) from exc

from ..crew import Crew
from ..factions import FactionAIController
from ..truck import Truck
from ..world.stateframes import SiteStateFrame

if TYPE_CHECKING:  # pragma: no cover - imported only for typing
    from .turn_engine import TurnContext

PhaseName = str

T = TypeVar("T")


@dataclass(slots=True)
class TruckComponent:
    """Singleton component exposing the player's truck."""

    truck: Truck


@dataclass(slots=True)
class CrewComponent:
    """Singleton component containing the travelling crew."""

    crew: Crew


@dataclass(slots=True)
class FactionControllerComponent:
    """Singleton component providing access to the faction AI controller."""

    controller: FactionAIController


@dataclass(slots=True)
class SitesComponent:
    """Collection of known world sites backed by a :class:`SiteStateFrame`."""

    sites: SiteStateFrame


class SystemCallback(Protocol):
    """Callable protocol describing a world system."""

    def __call__(self, world: "GameWorld", context: "TurnContext") -> None:  # noqa: D401
        ...


@dataclass(slots=True)
class _SystemEntry:
    priority: int
    order: int
    callback: SystemCallback


class GameWorld:
    """Wrapper around :class:`esper.World` providing ordered system execution."""

    def __init__(self) -> None:
        self._world = EsperWorld()
        self._singletons: Dict[Type[Any], int] = {}
        self._systems: Dict[PhaseName, List[_SystemEntry]] = {}
        self._system_counter = 0

    # ------------------------------------------------------------------
    def create_entity(self, *components: object) -> int:
        """Create an entity with the provided components."""

        return self._world.create_entity(*components)

    def add_component(self, entity: int, component: object) -> None:
        """Attach ``component`` to ``entity`` inside the world."""

        self._world.add_component(entity, component)

    def add_singleton(self, component: object) -> int:
        """Register ``component`` as the singleton instance for its type."""

        component_type = type(component)
        entity = self._singletons.get(component_type)
        if entity is None:
            entity = self._world.create_entity(component)
            self._singletons[component_type] = entity
        else:
            # Replace the component instance on the existing entity.
            if self._world.has_component(entity, component_type):
                self._world.remove_component(entity, component_type)
            self._world.add_component(entity, component)
        return entity

    def get_singleton(self, component_type: Type[T]) -> T | None:
        """Retrieve the singleton component for ``component_type`` if registered."""

        entity = self._singletons.get(component_type)
        if entity is None:
            return None
        try:
            return self._world.component_for_entity(entity, component_type)
        except KeyError:
            self._singletons.pop(component_type, None)
            return None

    def has_system_type(self, system_type: Type[object]) -> bool:
        """Return ``True`` if any registered system is an instance of ``system_type``."""

        for entries in self._systems.values():
            for entry in entries:
                if isinstance(getattr(entry.callback, "__self__", entry.callback), system_type):
                    return True
                if isinstance(entry.callback, system_type):
                    return True
        return False

    # ------------------------------------------------------------------
    def register_system(
        self,
        phase: PhaseName,
        system: SystemCallback | object,
        *,
        priority: int = 100,
    ) -> None:
        """Register ``system`` to execute during ``phase`` with ``priority`` ordering."""

        if hasattr(system, "process") and callable(getattr(system, "process")):
            callback = getattr(system, "process")  # type: ignore[assignment]
        elif callable(system):
            callback = system  # type: ignore[assignment]
        else:  # pragma: no cover - defensive branch
            raise TypeError("system must be callable or expose a process() method")

        self._system_counter += 1
        entry = _SystemEntry(priority=priority, order=self._system_counter, callback=callback)
        phase_systems = self._systems.setdefault(phase, [])
        phase_systems.append(entry)
        phase_systems.sort(key=lambda item: (item.priority, item.order))

    def process_phase(self, phase: PhaseName, context: "TurnContext") -> None:
        """Execute all systems registered for ``phase`` in priority order."""

        for entry in self._systems.get(phase, []):
            entry.callback(self, context)

    # ------------------------------------------------------------------
    @property
    def raw(self) -> EsperWorld:
        """Expose the underlying :class:`esper.World` instance."""

        return self._world


class TruckMaintenanceSystem:
    """Apply daily maintenance actions to the truck component."""

    def process(self, world: GameWorld, context: "TurnContext") -> None:  # pragma: no cover - runtime behaviour
        truck_component = world.get_singleton(TruckComponent)
        if truck_component is None:
            return
        raw_points = context.command.get("maintenance_points", 0) or 0
        try:
            maintenance_points = float(raw_points)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            maintenance_points = 0.0
        report = truck_component.truck.run_maintenance_cycle(
            maintenance_points,
            maintenance_cost_multiplier=context.maintenance_modifier,
        )
        reports = context.world_state.setdefault("maintenance_reports", [])
        reports.append(report)


class CrewAdvancementSystem:
    """Resolve daily need decay and morale adjustments for the crew."""

    def __init__(self, *, decay_modifier: float = 1.0) -> None:
        self.decay_modifier = decay_modifier

    def process(self, world: GameWorld, context: "TurnContext") -> None:  # pragma: no cover - runtime behaviour
        crew_component = world.get_singleton(CrewComponent)
        if crew_component is None:
            return
        crew_component.crew.advance_day(decay_modifier=self.decay_modifier)


class FactionAISystem:
    """Delegate faction behaviour to the registered AI controller."""

    def process(self, world: GameWorld, context: "TurnContext") -> None:  # pragma: no cover - runtime behaviour
        faction_component = world.get_singleton(FactionControllerComponent)
        if faction_component is None:
            return
        faction_component.controller.run_turn(world_state=context.world_state, day=context.day)


class DiplomacySystem:
    """Apply global diplomacy updates separate from faction AI turns."""

    def process(self, world: GameWorld, context: "TurnContext") -> None:  # pragma: no cover - runtime behaviour
        faction_component = world.get_singleton(FactionControllerComponent)
        if faction_component is None:
            return
        diplomacy = getattr(faction_component.controller, "diplomacy", None)
        if diplomacy is None:
            return
        decay = getattr(diplomacy, "decay", None)
        if callable(decay):
            decay()


__all__ = [
    "CrewAdvancementSystem",
    "CrewComponent",
    "DiplomacySystem",
    "FactionAISystem",
    "FactionControllerComponent",
    "GameWorld",
    "SitesComponent",
    "TruckComponent",
    "TruckMaintenanceSystem",
]
