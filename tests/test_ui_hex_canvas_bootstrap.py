from __future__ import annotations

import pytest

from game.ui import config_store
from game.ui import hex_canvas as ui_hex_canvas


def test_hex_canvas_marks_first_run_layout_dirty(tmp_path, monkeypatch):
    """The initial layout adjustment should flag the config as unsaved."""

    config_path = tmp_path / "hex_layout.json"

    # Ensure the UI uses an isolated config path for the test run.
    monkeypatch.setattr(config_store, "CONFIG_PATH", config_path, raising=False)
    monkeypatch.setattr(ui_hex_canvas, "CONFIG_PATH", config_path, raising=False)

    canvas = ui_hex_canvas.HexCanvas(cols=4, rows=3, radius=6)

    posted_messages: list[object] = []

    # ``on_mount`` emits layout change messages; capture them without a live app.
    def _capture_message(message: object) -> object:  # pragma: no cover - trivial wrapper
        posted_messages.append(message)
        return message

    canvas.post_message = _capture_message  # type: ignore[assignment]

    canvas.on_mount()

    cfg = canvas.cfg
    assert cfg is not None
    assert cfg.hex_height == pytest.approx(canvas._initial_hex_height)
    assert cfg.dirty is True

    # The emitted message should also reflect the dirty flag so the dashboard updates.
    assert posted_messages, "HexCanvas.on_mount() should emit a layout change message"
    last_message = posted_messages[-1]
    message_config = getattr(last_message, "config", None)
    assert message_config is cfg
    assert message_config.dirty is True
