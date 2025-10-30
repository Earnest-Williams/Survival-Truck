"""Truck layout rendering helpers."""

from __future__ import annotations

from rich.console import RenderableType
from textual.reactive import reactive
from textual.widget import Widget

from ..truck import Truck


def _render_truck_panel(truck: Truck, *, title: str) -> RenderableType:
    from rich import box
    from rich.panel import Panel
    from rich.table import Table

    table = Table(title=truck.name, expand=True, box=box.SIMPLE_HEAVY)
    table.add_column("Module", style="bold")
    table.add_column("Size", justify="center", no_wrap=True)
    table.add_column("Power", justify="right", no_wrap=True)
    table.add_column("Crew", justify="right", no_wrap=True)
    table.add_column("Condition", justify="right", no_wrap=True)

    for module in truck.iter_modules():
        power_delta = module.power_output - module.power_draw
        table.add_row(
            module.name,
            f"{module.size.length}x{module.size.width}x{module.size.height}",
            f"{power_delta:+d}",
            str(module.crew_required),
            f"{module.condition:.0%}",
        )

    if not truck.modules:
        table.add_row("(no modules equipped)", "-", "0", "0", "100%")

    stats = truck.stats
    footer = (
        f"Power {stats.power_output}/{stats.power_draw} | "
        f"Storage {stats.cargo_volume:.1f}/{stats.storage_capacity} | "
        f"Weight {stats.cargo_weight:.1f}/{stats.weight_capacity:.1f} | "
        f"Crew {stats.crew_workload}/{truck.crew_capacity}"
    )

    return Panel(table, title=title, subtitle=footer, border_style="green")


class TruckLayoutView(Widget):
    """Produce an at-a-glance representation of the truck and modules."""

    truck: Truck | None = reactive(None, layout=True)

    def __init__(
        self, *, title: str = "Truck Layout", truck: Truck | None = None
    ) -> None:
        super().__init__(id="truck")
        self.title = title
        if truck is not None:
            self.truck = truck

    def set_truck(self, truck: Truck | None) -> None:
        self.truck = truck
        self.refresh()

    def render(self):  # type: ignore[override]
        from rich.panel import Panel

        truck = self.truck
        if truck is None:
            return Panel("No truck connected", title=self.title, border_style="green")
        return _render_truck_panel(truck, title=self.title)


__all__ = ["TruckLayoutView"]
