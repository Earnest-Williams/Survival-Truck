# tools/codemods/fix_unions_and_polars.py
from __future__ import annotations

import argparse
import re
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[2]  # repo root

# Tuple → union conversions, tolerate optional trailing comma before the ')'
TRIPLE_NUMERIC_TUPLE = re.compile(
    r"isinstance\s*\(\s*([^)]+?)\s*,\s*\(\s*int\s*,\s*float\s*,\s*str\s*,?\s*\)\s*\)"
)
DOUBLE_INT_STR_TUPLE = re.compile(
    r"isinstance\s*\(\s*([^)]+?)\s*,\s*\(\s*int\s*,\s*str\s*,?\s*\)\s*\)"
)

POLARS_TARGET_FILES = {
    "game/crew/__init__.py",
    "game/world/stateframes.py",
    "game/factions/state.py",
}

SKIP_DIRS = {
    ".venv", "venv", ".mypy_cache", ".ruff_cache", ".pytest_cache",
    "__pycache__", "dist", "build",
}

def replace_unions(src: str) -> str:
    src = TRIPLE_NUMERIC_TUPLE.sub(r"isinstance(\1, int | float | str)", src)
    src = DOUBLE_INT_STR_TUPLE.sub(r"isinstance(\1, int | str)", src)
    return src

def replace_polars_imports(path: Path, src: str) -> str:
    rel = path.as_posix()
    if rel in POLARS_TARGET_FILES:
        src = src.replace(
            "from polars.type_aliases import PolarsDataType",
            "from polars._typing import PolarsDataType",
        )
    return src

def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)

def process_file(path: Path, dry_run: bool = False) -> bool:
    if path.suffix != ".py":
        return False
    original = text = path.read_text(encoding="utf-8")
    text = replace_unions(text)
    text = replace_polars_imports(path, text)
    if text != original:
        if not dry_run:
            path.write_text(text, encoding="utf-8")
        return True
    return False

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Repo root")
    ap.add_argument("--dry-run", action="store_true", help="Do not write changes")
    args = ap.parse_args()

    changed = 0
    for p in args.root.rglob("*.py"):
        if should_skip(p):
            continue
        if process_file(p, dry_run=args.dry_run):
            print(("would update: " if args.dry_run else "updated: ") + str(p))
            changed += 1
    print(f"done. files {'to change' if args.dry_run else 'changed'}: {changed}")

if __name__ == "__main__":
    main()
