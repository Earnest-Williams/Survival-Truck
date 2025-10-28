"""Command line entry point for launching the Textual UI."""

from __future__ import annotations

from .ui.app import SurvivalTruckApp


def main() -> None:
    """Launch the Survival Truck Textual dashboard."""

    SurvivalTruckApp().run()


if __name__ == "__main__":  # pragma: no cover - module entry point
    main()
