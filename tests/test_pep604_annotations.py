from __future__ import annotations

import re
from pathlib import Path


def _iter_python_files() -> list[Path]:
    roots = [Path("game"), Path("tests")]
    files: list[Path] = []
    for root in roots:
        for path in root.rglob("*.py"):
            if path.name == Path(__file__).name:
                continue
            files.append(path)
    return files


def test_no_typing_optional_usage() -> None:
    disallowed_patterns = [
        re.compile(r"\bOptional\["),
        re.compile(r"\btyping\.Optional\b"),
        re.compile(r"\bUnion\[[^\]]*\bNone\b"),
    ]
    offending: dict[str, list[str]] = {}
    for path in _iter_python_files():
        text = path.read_text(encoding="utf-8")
        matches: list[str] = []
        for pattern in disallowed_patterns:
            if pattern.search(text):
                matches.append(pattern.pattern)
        if matches:
            offending[str(path)] = matches
    assert not offending, f"PEP 604 violations detected: {offending}"
