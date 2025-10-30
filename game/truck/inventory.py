"""Inventory management models for the survival truck."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, Iterator, Mapping


class InventoryCapacityError(ValueError):
    """Raised when attempting to exceed cargo capacity limits."""


class InventoryItemNotFoundError(LookupError):
    """Raised when attempting to access an item that is not present."""


class InsufficientInventoryError(RuntimeError):
    """Raised when an inventory request cannot be fulfilled."""


class ItemCategory(str, Enum):
    """High-level classification for cargo items."""

    FOOD = "food"
    FUEL = "fuel"
    MEDICAL = "medical"
    MATERIALS = "materials"
    LUXURY = "luxury"
    COMPONENTS = "components"
    WATER = "water"
    OTHER = "other"

    @staticmethod
    def from_value(value: "ItemCategory | str") -> "ItemCategory":
        """Return the matching category, defaulting to :attr:`OTHER`."""

        if isinstance(value, ItemCategory):
            return value
        try:
            return ItemCategory(str(value))
        except ValueError:
            normalized = str(value).strip().lower()
            for category in ItemCategory:
                if category.value == normalized:
                    return category
            return ItemCategory.OTHER


@dataclass
class SpoilageState:
    """Tracks remaining freshness for perishable goods."""

    total_days: float
    remaining_days: float

    @staticmethod
    def fresh(duration_days: float) -> "SpoilageState":
        if duration_days <= 0:
            return SpoilageState(total_days=float(duration_days), remaining_days=0.0)
        return SpoilageState(
            total_days=float(duration_days), remaining_days=float(duration_days)
        )

    def advance(self, days: float) -> bool:
        """Advance spoilage and return ``True`` if state changed."""

        if days < 0:
            raise ValueError("days must be non-negative")
        previous = self.remaining_days
        if self.remaining_days <= 0:
            return False
        self.remaining_days = max(0.0, self.remaining_days - days)
        return previous != self.remaining_days

    @property
    def spoiled(self) -> bool:
        return self.remaining_days <= 0.0

    def copy(self) -> "SpoilageState":
        return SpoilageState(
            total_days=self.total_days, remaining_days=self.remaining_days
        )


@dataclass
class InventoryItem:
    """A single stack of items stored within the truck."""

    item_id: str
    name: str
    category: ItemCategory
    quantity: float
    weight_per_unit: float
    volume_per_unit: float
    base_value: float = 1.0
    spoilage: SpoilageState | None = None

    def clone(self, *, quantity: float | None = None) -> "InventoryItem":
        """Return a copy optionally overriding the quantity."""

        return InventoryItem(
            item_id=self.item_id,
            name=self.name,
            category=self.category,
            quantity=float(self.quantity if quantity is None else quantity),
            weight_per_unit=self.weight_per_unit,
            volume_per_unit=self.volume_per_unit,
            base_value=self.base_value,
            spoilage=self.spoilage.copy() if self.spoilage else None,
        )

    @property
    def total_weight(self) -> float:
        return self.weight_per_unit * self.quantity

    @property
    def total_volume(self) -> float:
        return self.volume_per_unit * self.quantity


class Inventory:
    """Container tracking weight, volume, and spoilage for cargo."""

    def __init__(
        self,
        *,
        max_weight: float | None = None,
        max_volume: float | None = None,
    ) -> None:
        self.max_weight = float("inf") if max_weight is None else float(max_weight)
        self.max_volume = float("inf") if max_volume is None else float(max_volume)
        self._items: Dict[str, InventoryItem] = {}

    # -- Introspection -------------------------------------------------
    def __iter__(self) -> Iterator[InventoryItem]:
        return iter(self._items.values())

    @property
    def items(self) -> Mapping[str, InventoryItem]:
        return self._items

    @property
    def total_weight(self) -> float:
        return sum(item.total_weight for item in self._items.values())

    @property
    def total_volume(self) -> float:
        return sum(item.total_volume for item in self._items.values())

    def summary_by_category(self) -> Dict[str, float]:
        summary: Dict[ItemCategory, float] = {}
        for item in self._items.values():
            summary[item.category] = summary.get(item.category, 0.0) + item.quantity
        return {category.value: amount for category, amount in summary.items()}

    def get(self, item_id: str) -> InventoryItem:
        try:
            return self._items[item_id]
        except KeyError as exc:  # pragma: no cover - defensive branch
            raise InventoryItemNotFoundError(item_id) from exc

    # -- Capacity management -------------------------------------------
    def set_capacity(
        self,
        *,
        max_weight: float | None = None,
        max_volume: float | None = None,
    ) -> None:
        if max_weight is not None:
            if max_weight < 0:
                raise ValueError("max_weight cannot be negative")
            self.max_weight = float(max_weight)
        if max_volume is not None:
            if max_volume < 0:
                raise ValueError("max_volume cannot be negative")
            self.max_volume = float(max_volume)
        if (
            self.total_weight > self.max_weight + 1e-6
            or self.total_volume > self.max_volume + 1e-6
        ):
            raise InventoryCapacityError(
                "Existing cargo exceeds the new capacity limits"
            )

    def _ensure_capacity(
        self, *, additional_weight: float, additional_volume: float
    ) -> None:
        new_weight = self.total_weight + additional_weight
        if new_weight > self.max_weight + 1e-6:
            raise InventoryCapacityError("Cargo weight would exceed capacity")

    # -- Mutation helpers ----------------------------------------------
    def add_item(self, item: InventoryItem, *, merge: bool = True) -> None:
        if item.quantity <= 0:
            return
        self._ensure_capacity(
            additional_weight=item.total_weight,
            additional_volume=item.total_volume,
        )
        existing = self._items.get(item.item_id)
        if merge and existing is not None:
            if (
                abs(existing.weight_per_unit - item.weight_per_unit) > 1e-6
                or abs(existing.volume_per_unit - item.volume_per_unit) > 1e-6
            ):
                raise ValueError("Cannot merge stacks with different per-unit metrics")
            existing.quantity += item.quantity
            existing.base_value = (existing.base_value + item.base_value) / 2
            if existing.spoilage and item.spoilage:
                # Retain the fresher of the two stacks by keeping the higher remaining days.
                existing.spoilage.remaining_days = max(
                    existing.spoilage.remaining_days,
                    item.spoilage.remaining_days,
                )
            elif item.spoilage and not existing.spoilage:
                existing.spoilage = item.spoilage.copy()
            return
        self._items[item.item_id] = item.clone()

    def remove_item(self, item_id: str, quantity: float) -> InventoryItem:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        item = self._items.get(item_id)
        if item is None:
            raise InventoryItemNotFoundError(item_id)
        if item.quantity + 1e-9 < quantity:
            raise InsufficientInventoryError(f"Insufficient quantity of '{item_id}'")
        removed = item.clone(quantity=quantity)
        item.quantity -= quantity
        if item.quantity <= 1e-6:
            self._items.pop(item_id, None)
        return removed

    def consume_category(
        self, category: ItemCategory, quantity: float
    ) -> Dict[str, float]:
        if quantity <= 0:
            return {}
        stacks = sorted(
            (item for item in self._items.values() if item.category == category),
            key=lambda item: item.spoilage.remaining_days
            if item.spoilage
            else float("inf"),
        )
        remaining = float(quantity)
        consumed: Dict[str, float] = {}
        for stack in stacks:
            if remaining <= 1e-9:
                break
            take = min(stack.quantity, remaining)
            if take <= 0:
                continue
            self.remove_item(stack.item_id, take)
            consumed[stack.item_id] = consumed.get(stack.item_id, 0.0) + take
            remaining -= take
        if remaining > 1e-6:
            raise InsufficientInventoryError(
                f"Unable to consume {quantity} units from category '{category.value}'"
            )
        return consumed

    def available_quantity(self, item_id: str) -> float:
        item = self._items.get(item_id)
        return 0.0 if item is None else float(item.quantity)

    # -- Spoilage -------------------------------------------------------
    def advance_time(
        self, days: float = 1.0, *, remove_spoiled: bool = True
    ) -> Iterable[tuple[str, float]]:
        if days < 0:
            raise ValueError("days must be non-negative")
        spoiled: list[tuple[str, float]] = []
        for item_id, item in list(self._items.items()):
            if not item.spoilage:
                continue
            changed = item.spoilage.advance(days)
            if not changed:
                continue
            if item.spoilage.spoiled and remove_spoiled:
                spoiled.append((item_id, item.quantity))
                self._items.pop(item_id, None)
        return spoiled


__all__ = [
    "InsufficientInventoryError",
    "Inventory",
    "InventoryCapacityError",
    "InventoryItem",
    "InventoryItemNotFoundError",
    "ItemCategory",
    "SpoilageState",
]
