import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.truck.inventory import (
    Inventory,
    InventoryCapacityError,
    InventoryItem,
    ItemCategory,
)


def test_add_item_raises_when_volume_capacity_exceeded():
    inventory = Inventory(max_weight=100, max_volume=10)
    oversized_item = InventoryItem(
        item_id="water-barrel",
        name="Water Barrel",
        category=ItemCategory.WATER,
        quantity=1,
        weight_per_unit=1,
        volume_per_unit=11,
    )

    with pytest.raises(InventoryCapacityError, match="volume"):
        inventory.add_item(oversized_item)
