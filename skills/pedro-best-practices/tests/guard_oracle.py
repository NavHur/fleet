"""The real godot-guard, so tests can check that the skill's tags match what `godot-guard check` decides."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import godot_guard  # noqa: E402


def find() -> str | None:
    """A godot-guard with `check --json`: PBP_GODOT_GUARD, a .venv here, or PATH."""
    binary = godot_guard.find(Path.cwd())
    if binary is None or (godot_guard.version_of(binary) or (0, 0)) < godot_guard.MINIMUM:
        return None
    return binary


GODOT_GUARD = find()
MISSING = "no godot-guard 0.2+; set PBP_GODOT_GUARD to one (a godot-guard checkout's .venv/bin/godot-guard)"


def verdict(repo: Path, path: str, line: int, rules: tuple[str, ...]) -> str:
    """'error', 'warning', 'passes', or 'unchecked': what `godot-guard check PATH` reports for `rules` on that line."""
    result = subprocess.run([GODOT_GUARD, "check", path], cwd=repo, capture_output=True, text=True)
    if result.stdout.rstrip().endswith(" 0 files"):
        return "unchecked"
    rows = [row for row in result.stdout.splitlines()
            if row.startswith(f"{path}:{line}: ") and row.endswith(tuple(f"({rule})" for rule in rules))]
    if any(not row.startswith(f"{path}:{line}: warning: ") for row in rows):
        return "error"
    if rows:
        return "warning"
    return "passes"
