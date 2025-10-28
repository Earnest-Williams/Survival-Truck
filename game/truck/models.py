"""Truck domain models and maintenance logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from .inventory import Inventory


class ModuleCapacityError(ValueError):
    """Raised when a module cannot fit within the truck's module capacity."""


class CrewOverloadError(ValueError):
    """Raised when equipping a module would exceed crew workload limits."""


class ModuleNotEquippedError(LookupError):
    """Raised when attempting to unequip a module that is not present."""


@dataclass(frozen=True)
class Dimensions:
    """Physical dimensions measured in abstract grid units."""

    length: int
    width: int
    height: int

    def fits_within(self, other: "Dimensions") -> bool:
        """Return True if these dimensions fit within the provided envelope."""

        return (
            self.length <= other.length
            and self.width <= other.width
            and self.height <= other.height
        )

    @property
    def volume(self) -> int:
        """Simple volume calculation for capacity comparison."""

        return self.length * self.width * self.height


@dataclass
class TruckModule:
    """Configurable module that can be attached to the truck."""

    module_id: str
    name: str
    size: Dimensions
    power_output: int = 0
    power_draw: int = 0
    storage_bonus: int = 0
    weight_bonus: float = 0.0
    crew_required: int = 0
    maintenance_load: int = 0
    degradation_rate: float = 0.01
    condition: float = 1.0

    def apply_degradation(self, stress_modifier: float) -> bool:
        """Apply daily degradation adjusted by the provided stress modifier."""

        if self.degradation_rate <= 0:
            return False
        loss = self.degradation_rate * (1.0 + stress_modifier)
        previous_condition = self.condition
        self.condition = max(0.0, self.condition - loss)
        return self.condition != previous_condition

    @property
    def is_operational(self) -> bool:
        """Determine whether the module can still function."""

        return self.condition > 0.0


@dataclass
class TruckStats:
    """Derived aggregate statistics for the truck."""

    power_output: int
    power_draw: int
    storage_capacity: int
    weight_capacity: float
    cargo_weight: float
    cargo_volume: float
    crew_workload: int
    maintenance_load: int

    @property
    def net_power(self) -> int:
        return self.power_output - self.power_draw


@dataclass
class MaintenanceReport:
    """Summary of the maintenance phase for logging or UI consumption."""

    maintenance_applied: int
    maintenance_required: int
    truck_condition: float
    module_conditions: Dict[str, float]
    degraded_modules: List[str] = field(default_factory=list)

    @property
    def shortfall(self) -> int:
        return max(0, self.maintenance_required - self.maintenance_applied)


@dataclass
class Truck:
    """Base survival vehicle with modular expansion."""

    name: str
    module_capacity: Dimensions
    crew_capacity: int
    base_power_output: int
    base_power_draw: int = 0
    base_storage_capacity: int = 0
    base_weight_capacity: float = 0.0
    base_maintenance_load: int = 0
    base_degradation_rate: float = 0.005
    modules: Dict[str, TruckModule] = field(default_factory=dict)
    condition: float = 1.0
    inventory: Inventory = field(default_factory=Inventory)

    def __post_init__(self) -> None:
        self._sync_inventory_capacity()

    def equip_module(self, module: TruckModule) -> None:
        """Attach a module after validating size and crew workload constraints."""

        if module.module_id in self.modules:
            raise ModuleCapacityError(f"Module '{module.module_id}' already equipped")
        if not module.size.fits_within(self.module_capacity):
            raise ModuleCapacityError(
                f"Module '{module.name}' exceeds truck dimensions {self.module_capacity}"
            )
        if self._occupied_volume + module.size.volume > self.module_capacity.volume:
            raise ModuleCapacityError("Insufficient module volume capacity")
        if self.crew_capacity and self.current_crew_workload + module.crew_required > self.crew_capacity:
            raise CrewOverloadError(
                "Equipping module would exceed available crew capacity"
            )
        self.modules[module.module_id] = module
        self._sync_inventory_capacity()

    def unequip_module(self, module_id: str) -> TruckModule:
        """Detach a module from the truck."""

        try:
            module = self.modules.pop(module_id)
        except KeyError as exc:  # pragma: no cover - defensive branch
            raise ModuleNotEquippedError(module_id) from exc
        self._sync_inventory_capacity()
        return module

    def get_module(self, module_id: str) -> TruckModule:
        try:
            return self.modules[module_id]
        except KeyError as exc:  # pragma: no cover - defensive branch
            raise ModuleNotEquippedError(module_id) from exc

    @property
    def current_crew_workload(self) -> int:
        return sum(module.crew_required for module in self.modules.values())

    @property
    def maintenance_load(self) -> int:
        return self.base_maintenance_load + sum(
            module.maintenance_load for module in self.modules.values()
        )

    @property
    def power_output(self) -> int:
        return self.base_power_output + sum(
            module.power_output for module in self.modules.values()
        )

    @property
    def power_draw(self) -> int:
        return self.base_power_draw + sum(module.power_draw for module in self.modules.values())

    @property
    def storage_capacity(self) -> int:
        return self.base_storage_capacity + sum(
            module.storage_bonus for module in self.modules.values()
        )

    @property
    def weight_capacity(self) -> float:
        return self.base_weight_capacity + sum(
            module.weight_bonus for module in self.modules.values()
        )

    def _sync_inventory_capacity(self) -> None:
        if not isinstance(self.inventory, Inventory):
            return
        self.inventory.set_capacity(
            max_weight=self.weight_capacity,
            max_volume=self.storage_capacity,
        )

    @property
    def stats(self) -> TruckStats:
        return TruckStats(
            power_output=self.power_output,
            power_draw=self.power_draw,
            storage_capacity=self.storage_capacity,
            weight_capacity=self.weight_capacity,
            cargo_weight=self.inventory.total_weight if isinstance(self.inventory, Inventory) else 0.0,
            cargo_volume=self.inventory.total_volume if isinstance(self.inventory, Inventory) else 0.0,
            crew_workload=self.current_crew_workload,
            maintenance_load=self.maintenance_load,
        )

    def run_maintenance_cycle(self, maintenance_points: int) -> MaintenanceReport:
        """Apply maintenance effort and degrade modules accordingly."""

        required = self.maintenance_load
        stress = 0.0
        if required > 0:
            stress = max(0.0, (required - maintenance_points) / required)
        degraded_modules: List[str] = []

        base_loss = self.base_degradation_rate * (1.0 + stress)
        previous_condition = self.condition
        self.condition = max(0.0, self.condition - base_loss)
        if self.condition != previous_condition:
            degraded_modules.append("base_vehicle")

        for module in self.modules.values():
            if module.apply_degradation(stress):
                degraded_modules.append(module.module_id)

        report = MaintenanceReport(
            maintenance_applied=maintenance_points,
            maintenance_required=required,
            truck_condition=self.condition,
            module_conditions={mid: mod.condition for mid, mod in self.modules.items()},
            degraded_modules=degraded_modules,
        )
        return report

    @property
    def _occupied_volume(self) -> int:
        return sum(module.size.volume for module in self.modules.values())

    def iter_modules(self) -> Iterable[TruckModule]:
        return self.modules.values()
