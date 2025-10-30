from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # repo root (adjust if you place elsewhere)

# Patterns for isinstance tuple → union conversions
TRIPLE_NUMERIC_TUPLE = re.compile(r"isinstance\s*\(\s*([^)]+?)\s*,\s*\(\s*int\s*,\s*float\s*,\s*str\s*\)\s*\)")
DOUBLE_INT_STR_TUPLE = re.compile(r"isinstance\s*\(\s*([^)]+?)\s*,\s*\(\s*int\s*,\s*str\s*\)\s*\)")

def replace_unions(source: str) -> str:
    # Replace (int, float, str) → int | float | str
    source = TRIPLE_NUMERIC_TUPLE.sub(r"isinstance(\1, int | float | str)", source)
    # Replace (int, str) → int | str
    source = DOUBLE_INT_STR_TUPLE.sub(r"isinstance(\1, int | str)", source)
    return source

def replace_polars_imports(path: Path, source: str) -> str:
    # Minimal change per deprecation notice
    # from polars.type_aliases import PolarsDataType → from polars._typing import PolarsDataType
    if path.as_posix() in {
        "game/crew/__init__.py",
        "game/world/stateframes.py",
        "game/factions/state.py",
    }:
        source = source.replace(
            "from polars.type_aliases import PolarsDataType",
            "from polars._typing import PolarsDataType",
        )
    return source

def process_file(path: Path) -> bool:
    if path.suffix != ".py":
        return False
    original = text = path.read_text(encoding="utf-8")
    text = replace_unions(text)
    text = replace_polars_imports(path, text)
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False

def main() -> None:
    changed = 0
    for p in ROOT.rglob("*.py"):
        # Skip virtualenvs, build dirs, etc., if present
        if any(part in {".venv", "venv", ".mypy_cache", ".ruff_cache", ".pytest_cache", "dist", "build"} for part in p.parts):
            continue
        if process_file(p):
            print(f"updated: {p}")
            changed += 1
    print(f"done. files changed: {changed}")

if __name__ == "__main__":
    main()
