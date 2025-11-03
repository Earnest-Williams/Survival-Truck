"""Trading helpers leveraging faction resource preferences and behavioural traits.

This module wraps the upstream trading logic, adding support for
behavioural traits such as ``greedy`` and ``benevolent``.  These traits
modify the prices a faction is willing to pay or charge for goods.
Greedy factions demand more for their wares and value incoming goods
less, while benevolent factions offer fairer deals and value the
player's offerings more generously.  The trait values are stored on the
``FactionLedger`` and accessed through the ``FactionRecord`` interface.

If no trait data is present for a faction, neutral behaviour is
assumed.  Traits are clamped between 0 and 1; a value of 0.0 exerts no
influence, and a value of 1.0 applies the maximum price adjustment.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

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

    offered: dict[str, float]
    requested: dict[str, float]
    faction_value: float
    player_value: float
    exchange_rate: float


class TradeInterface:
    """Evaluate and execute trades against faction preferences and traits."""

    def __init__(
        self,
        faction: FactionRecord,
        inventory: Inventory,
        *,
        supply_catalog: Mapping[str, InventoryItem] | None = None,
    ) -> None:
        self.faction = faction
        self.inventory = inventory
        self._supply_catalog: dict[str, InventoryItem] = {
            key: value.clone(quantity=1.0) for key, value in (supply_catalog or {}).items()
        }

    # ------------------------------------------------------------------
    def _trait_multiplier(self) -> float:
        """Compute a multiplicative factor based on faction traits.

        Greedy factions inflate prices, while benevolent factions
        discount them.  The multiplier is calculated as

        ``1.0 + greedy * 0.5 - benevolent * 0.3``.

        Clamping ensures the result stays within a reasonable range.
        """
        # Access traits via the ledger.  Missing traits default to 0.0.
        greedy = 0.0
        benevolent = 0.0
        try:
            ledger = self.faction.ledger
            name = self.faction.name
            greedy = ledger.get_trait(name, "greedy", 0.0)
            benevolent = ledger.get_trait(name, "benevolent", 0.0)
        except Exception:
            # Defensive: ignore trait lookup failures
            pass
        # Compute multiplier; greedy increases price, benevolent decreases.
        multiplier = 1.0 + greedy * 0.5 - benevolent * 0.3
        # Ensure the multiplier stays within [0.5, 2.0]
        return max(0.5, min(2.0, float(multiplier)))

    def evaluate_bundle(self, bundle: Mapping[str, float]) -> float:
        """Return the total value a faction assigns to ``bundle``.

        The base evaluation multiplies each item's base value by the
        faction's preference weight.  This implementation adjusts the
        total by a factor derived from the faction's greedy or
        benevolent traits.  Greedy factions value incoming bundles
        less, while benevolent factions value them more.
        """

        total = 0.0
        for resource, amount in bundle.items():
            if amount <= 0:
                continue
            stack = self.inventory.items.get(resource)
            category = stack.category.value if stack else None
            base_value = stack.base_value if stack else 1.0
            preference = self.faction.preference_for(resource, category=category)
            total += base_value * preference * float(amount)
        # Adjust by trait multiplier: greedy factions diminish the perceived
        # value of goods they receive; benevolent factions amplify it.
        multiplier = self._trait_multiplier()
        return total * multiplier

    def propose_trade(
        self,
        requested: Mapping[str, float],
        *,
        fairness: float = 1.0,
    ) -> TradeOffer:
        """Construct a trade offer matching requested goods against inventory.

        The requested bundle's value is computed with trait adjustments.
        The fairness factor still applies as before.
        """

        requested_value = self.evaluate_bundle(requested)
        # Determine desired value from the faction's perspective.  Greedy
        # factions will implicitly raise the price via evaluate_bundle.
        target_value = requested_value * fairness
        offered: dict[str, float] = {}
        remaining_value = target_value

        # Sort stacks by preference weight; traits are handled in evaluate_bundle
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
            preference = self.faction.preference_for(stack.item_id, category=stack.category.value)
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
            raise InsufficientInventoryError("Inventory cannot satisfy the requested trade value")

        # Compute the final values.  The faction's value of its offer
        # incorporates trait adjustments for greedy/benevolent behaviour.
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

        # Build a catalog of template items used to clone requested goods.
        catalog: dict[str, InventoryItem] = {
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