"""Tests for ensuring project packaging metadata stays consistent."""

from __future__ import annotations

import tomllib
from pathlib import Path

import game

meta: dict[str, str] = {}


def _load_pyproject() -> dict:
    with Path("pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_pyproject_declares_expected_metadata() -> None:
    pyproject = _load_pyproject()
    poetry = pyproject["tool"]["poetry"]

    assert poetry["name"] == "survival-truck"
    assert poetry["version"] == game.__version__
    assert poetry["scripts"]["survival-truck"] == "game.__main__:main"

    dependencies = poetry["dependencies"]
    for dependency in ("textual", "networkx", "sqlmodel"):
        assert dependency in dependencies, f"missing dependency declaration for {dependency}"
