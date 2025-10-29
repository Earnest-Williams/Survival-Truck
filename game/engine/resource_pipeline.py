"""Resource consumption and production pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Sequence

from numpy.random import Generator

from ..crew import Crew, NeedName, SkillCheckResult
from ..truck import (
    InsufficientInventoryError,
    Inventory,
    InventoryItem,
    ItemCategory,
    Truck,
)
from ..world.stateframes import SiteStateFrame
from .world import CrewComponent, SitesComponent, TruckComponent


@dataclass
class ResourceLogEntry:
    """Record of resource changes applied during a turn."""

    phase: str
    source: str
    consumed: Dict[str, float] = field(default_factory=dict)
    produced: Dict[str, float] = field(default_factory=dict)
    notes: Dict[str, object] = field(default_factory=dict)


class ResourcePipeline:
    """Coordinates resource consumption and production for the campaign."""

    def __init__(
        self,
        *,
        production_catalog: Mapping[str, InventoryItem] | None = None,
        rng: Generator | None = None,
    ) -> None:
        self.production_catalog: Dict[str, InventoryItem] = {
            key: value.clone(quantity=1.0)
            for key, value in (production_catalog or {}).items()
        }
        self.rng = rng

    # ------------------------------------------------------------------
    def process_crew_actions(self, context: "TurnContext") -> None:
        truck_component = context.world.get_singleton(TruckComponent)
        if truck_component is None:
            return
        truck = truck_component.truck
        inventory = truck.inventory if isinstance(truck.inventory, Inventory) else None
        if inventory is None:
            return
        crew_component = context.world.get_singleton(CrewComponent)
        crew = crew_component.crew if crew_component is not None else None
        actions = context.command.get("crew_actions", [])
        if not isinstance(actions, Iterable):
            return

        log: List[ResourceLogEntry] = context.world_state.setdefault("resource_events", [])

        spoiled = list(inventory.advance_time())
        if spoiled:
            log.append(
                ResourceLogEntry(
                    phase="command",
                    source="spoilage",
                    notes={"spoiled": spoiled},
                )
            )

        for raw_action in actions:
            if not isinstance(raw_action, Mapping):
                continue
            action_name = str(raw_action.get("action", "crew_action"))
            participants = self._normalize_participants(raw_action.get("participants"))
            consumption = self._normalize_resource_map(raw_action.get("consume"))
            production = self._normalize_resource_map(raw_action.get("produce"))
            adjustments = raw_action.get("need_adjustments", {})

            consumed: Dict[str, float] = {}
            produced: Dict[str, float] = {}

            try:
                consumed = self._apply_consumption(inventory, consumption)
                produced = self._apply_production(inventory, production)
            except InsufficientInventoryError:
                log.append(
                    ResourceLogEntry(
                        phase="command",
                        source=action_name,
                        notes={"error": "insufficient_resources"},
                    )
                )
                continue

            if isinstance(crew, Crew):
                self._apply_need_adjustments(crew, participants, adjustments)

            log.append(
                ResourceLogEntry(
                    phase="command",
                    source=action_name,
                    consumed=consumed,
                    produced=produced,
                    notes={"participants": participants},
                )
            )

    def process_site_exploitation(self, context: "TurnContext") -> None:
        truck_component = context.world.get_singleton(TruckComponent)
        if truck_component is None:
            return
        truck = truck_component.truck
        inventory = truck.inventory if isinstance(truck.inventory, Inventory) else None
        if inventory is None:
            return

        sites_component = context.world.get_singleton(SitesComponent)
        site_state = (
            sites_component.sites
            if sites_component is not None
            else SiteStateFrame()
        )
        orders = context.command.get("site_exploitation", [])
        if not isinstance(orders, Iterable):
            return

        log: List[ResourceLogEntry] = context.world_state.setdefault("resource_events", [])

        for raw_order in orders:
            if not isinstance(raw_order, Mapping):
                continue
            site_id = raw_order.get("site") or raw_order.get("site_id")
            if not site_id:
                continue
            site_key = str(site_id)
            if not site_state.has_site(site_key):
                continue

            produced: Dict[str, float] = {}
            notes: Dict[str, object] = {"site": site_key}

            result = raw_order.get("scavenge_result")
            if isinstance(result, SkillCheckResult):
                progress = site_state.apply_scavenge_result(site_key, result)
                yield_key = str(raw_order.get("resource", "scavenged_goods"))
                base_amount = max(1.0, progress / 5.0)
                produced.update(self._apply_production(inventory, {yield_key: base_amount}))
                notes["progress"] = progress

            explicit_production = self._normalize_resource_map(raw_order.get("produce"))
            if explicit_production:
                extra = self._apply_production(inventory, explicit_production)
                for key, value in extra.items():
                    produced[key] = produced.get(key, 0.0) + value

            if produced:
                log.append(
                    ResourceLogEntry(
                        phase="site",
                        source=str(raw_order.get("action", "site_exploitation")),
                        produced=produced,
                        notes=notes,
                    )
                )

    # ------------------------------------------------------------------
    def register_production_template(self, item: InventoryItem) -> None:
        self.production_catalog[item.item_id] = item.clone(quantity=1.0)

    def _apply_consumption(
        self, inventory: Inventory, requirements: Mapping[str, float]
    ) -> Dict[str, float]:
        consumed: Dict[str, float] = {}
        for resource, amount in requirements.items():
            if amount <= 0:
                continue
            if resource.startswith("category:"):
                category_name = resource.split(":", 1)[1]
                category = ItemCategory.from_value(category_name)
                taken = inventory.consume_category(category, amount)
                for key, value in taken.items():
                    consumed[key] = consumed.get(key, 0.0) + value
            else:
                inventory.remove_item(resource, amount)
                consumed[resource] = consumed.get(resource, 0.0) + amount
        return consumed

    def _apply_production(
        self, inventory: Inventory, outputs: Mapping[str, float]
    ) -> Dict[str, float]:
        produced: Dict[str, float] = {}
        for resource, amount in outputs.items():
            if amount <= 0:
                continue
            template = self.production_catalog.get(resource)
            if template is None:
                template = InventoryItem(
                    item_id=resource,
                    name=resource.replace("_", " ").title(),
                    category=ItemCategory.OTHER,
                    quantity=1.0,
                    weight_per_unit=1.0,
                    volume_per_unit=1.0,
                )
            inventory.add_item(template.clone(quantity=amount))
            produced[resource] = produced.get(resource, 0.0) + amount
        return produced

    def _apply_need_adjustments(
        self,
        crew: Crew,
        participants: Sequence[str],
        adjustments: Mapping[str, float],
    ) -> None:
        if not adjustments:
            return
        for name in participants:
            if not crew.has_member(name):
                continue
            for key, delta in adjustments.items():
                try:
                    need = NeedName(str(key))
                except ValueError:
                    continue
                crew.adjust_need(name, need, float(delta))

    def _normalize_resource_map(self, payload: object) -> Dict[str, float]:
        if not isinstance(payload, Mapping):
            return {}
        normalized: Dict[str, float] = {}
        for key, value in payload.items():
            try:
                amount = float(value)
            except (TypeError, ValueError):
                continue
            normalized[str(key)] = amount
        return normalized

    def _normalize_participants(self, payload: object) -> List[str]:
        if isinstance(payload, str):
            return [payload]
        if isinstance(payload, Sequence):
            return [str(entry) for entry in payload]
        return []

__all__ = ["ResourceLogEntry", "ResourcePipeline"]
