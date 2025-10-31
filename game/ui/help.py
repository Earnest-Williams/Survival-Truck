"""Help dialog components for the Survival Truck Textual UI."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from rich.table import Table
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static


@dataclass(frozen=True)
class HelpCommand:
    """Description of a single command binding."""

    key: str
    description: str


@dataclass(frozen=True)
class HelpSection:
    """Collection of related help commands."""

    title: str
    commands: Sequence[HelpCommand]


class HelpScreen(ModalScreen[None]):
    """Modal dialog listing all available key bindings."""

    CSS = """
    HelpScreen {
        align: center middle;
    }

    #help-dialog {
        width: 60%;
        max-width: 80;
        padding: 1 2;
        border: wide #4db6ac;
        background: #111111;
    }

    #help-title {
        text-style: bold;
        content-align: center middle;
        height: auto;
        margin-bottom: 1;
    }

    #help-commands {
        height: auto;
        max-height: 20;
        padding-right: 1;
    }

    .help-section-title {
        text-style: bold;
        margin-top: 1;
        margin-bottom: 1;
    }

    .help-section-title:first-child {
        margin-top: 0;
    }

    .help-table {
        margin-bottom: 1;
    }

    #help-close {
        width: 100%;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
    ]

    def __init__(
        self,
        sections: Sequence[HelpSection],
        *,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.sections: list[HelpSection] = list(sections)
        self._on_close = on_close

    def compose(self):  # type: ignore[override]
        with Container(id="help-dialog"):
            yield Static("Help", id="help-title")
            with VerticalScroll(id="help-commands"):
                for section in self.sections:
                    yield Static(section.title, classes="help-section-title")
                    table = Table.grid(padding=(0, 2), expand=True)
                    table.add_column("Key", justify="right", style="bold")
                    table.add_column("Description", justify="left")
                    for command in section.commands:
                        table.add_row(command.key, command.description)
                    yield Static(table, classes="help-table")
            yield Button("Close", id="help-close")

    def _notify_close(self) -> None:
        if self._on_close is not None:
            self._on_close()

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:  # noqa: D401 - Textual hook
        """Close the dialog when the button is activated."""

        if event.button.id == "help-close":
            self.dismiss(None)

    def dismiss(self, result: None = None) -> None:  # type: ignore[override]
        super().dismiss(result)
        self._notify_close()


def build_help_commands(bindings: Iterable[Binding]) -> list[HelpCommand]:
    """Convert Textual bindings into help command entries."""

    commands: list[HelpCommand] = []
    for binding in bindings:
        description = binding.description or ""
        key = binding.key_display or binding.key
        commands.append(HelpCommand(key=key, description=description))
    return commands

