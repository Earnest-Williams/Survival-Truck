"""Trading helpers leveraging faction resource preferences."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, TYPE_CHECKING

from ..truck.inventory import (
    InsufficientInventoryError,
    Inventory,
    InventoryItem,
    ItemCategory,
)

if TYPE_CHECKING:  # pragma: no cover - import guard for type checkers
    from .state import FactionRecord


@dataclass
class TradeOffer:
    """Represents a proposed exchange between the player and a faction."""

    offered: Dict[str, float]
    requested: Dict[str, float]
    faction_value: float
    player_value: float
    exchange_rate: float


class TradeInterface:
    """Evaluate and execute trades against faction preferences."""

    def __init__(
        self,
        faction: "FactionRecord",
        inventory: Inventory,
        *,
        supply_catalog: Mapping[str, InventoryItem] | None = None,
    ) -> None:
        self.faction = faction
        self.inventory = inventory
        self._supply_catalog: Dict[str, InventoryItem] = {
            key: value.clone(quantity=1.0) for key, value in (supply_catalog or {}).items()
        }

    def evaluate_bundle(self, bundle: Mapping[str, float]) -> float:
        """Return the total value a faction assigns to ``bundle``."""

        total = 0.0
        for resource, amount in bundle.items():
            if amount <= 0:
                continue
            stack = self.inventory.items.get(resource)
            category = stack.category.value if stack else None
            base_value = stack.base_value if stack else 1.0
            preference = self.faction.preference_for(resource, category=category)
            total += base_value * preference * float(amount)
        return total

    def propose_trade(
        self,
        requested: Mapping[str, float],
        *,
        fairness: float = 1.0,
    ) -> TradeOffer:
        """Construct a trade offer matching requested goods against inventory."""

        requested_value = self.evaluate_bundle(requested)
        target_value = requested_value * fairness
        offered: Dict[str, float] = {}
        remaining_value = target_value

        stacks = sorted(
            self.inventory.items.values(),
            key=lambda item: self.faction.preference_for(
                item.item_id, category=item.category.value
            ),
            reverse=True,
        )

        for stack in stacks:
            if remaining_value <= 1e-6:
                break
            preference = self.faction.preference_for(
                stack.item_id, category=stack.category.value
            )
            unit_value = stack.base_value * preference
            if unit_value <= 0:
                continue
            available_value = stack.quantity * unit_value
            take_value = min(available_value, remaining_value)
            quantity = take_value / unit_value
            if quantity <= 0:
                continue
            offered[stack.item_id] = offered.get(stack.item_id, 0.0) + quantity
            remaining_value -= take_value

        if remaining_value > 1e-3:
            raise InsufficientInventoryError(
                "Inventory cannot satisfy the requested trade value"
            )

        faction_value = self.evaluate_bundle(offered)
        player_value = requested_value
        exchange_rate = faction_value / player_value if player_value else 0.0
        return TradeOffer(
            offered=offered,
            requested=dict(requested),
            faction_value=faction_value,
            player_value=player_value,
            exchange_rate=exchange_rate,
        )

    def execute_trade(
        self,
        offer: TradeOffer,
        *,
        supply_overrides: Mapping[str, InventoryItem] | None = None,
    ) -> None:
        """Apply ``offer`` to the tracked inventory."""

        for resource, quantity in offer.offered.items():
            self.inventory.remove_item(resource, quantity)

        catalog: Dict[str, InventoryItem] = {
            **self._supply_catalog,
            **{key: value.clone(quantity=1.0) for key, value in (supply_overrides or {}).items()},
        }

        for resource, quantity in offer.requested.items():
            if quantity <= 0:
                continue
            template = catalog.get(resource)
            if template is None:
                template = InventoryItem(
                    item_id=resource,
                    name=resource.replace("_", " ").title(),
                    category=ItemCategory.OTHER,
                    quantity=1.0,
                    weight_per_unit=1.0,
                    volume_per_unit=1.0,
                )
            self.inventory.add_item(template.clone(quantity=quantity))


__all__ = ["TradeInterface", "TradeOffer"]
