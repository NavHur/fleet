"""Read a Godot repository's godot-guard settings so audits can tag what its lint enforces.

godot-guard (github.com/PedroNavHur/godot-guard) runs complexity and comment
rules in Godot repositories from `.godot-guard.yml`, with a ratchet baseline
in `.godot-guard-baseline.json`. Its configs allow no anchors or aliases, so
the fallback reader below only needs block and one-line flow mappings when
PyYAML is not installed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

CONFIG = ".godot-guard.yml"
BASELINE = ".godot-guard-baseline.json"
DEFAULT_LIMITS = {"cognitive": 8, "cyclomatic": 16, "comment-lines": 2}
SEVERITY = {"error": "error", "warn": "warning"}
SECTION = re.compile(r"^(\w[\w-]*):\s*(.*?)\s*(#.*)?$")
ENTRY = re.compile(r"^\s+(\w[\w-]*):\s*(.*?)\s*(#.*)?$")


@dataclass
class GodotGuard:
    limits: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_LIMITS))
    levels: dict[str, str] = field(default_factory=dict)
    baseline: dict[str, dict[str, int]] = field(default_factory=dict)

    def severity(self, rule: str) -> str | None:
        """'error' or 'warning' while the rule is on, None when it is off."""
        return SEVERITY.get(str(self.levels.get(rule, "error")).lower())

    def allowance(self, rule: str, key: str) -> int:
        return self.baseline.get(rule, {}).get(key, 0)


def scalar(text: str) -> object:
    text = text.strip().strip("'\"")
    if text in ("false", "False", "off"):
        return "off"
    return int(text) if text.isdigit() else text


def flow(text: str) -> dict[str, object]:
    pairs = (item.split(":", 1) for item in text.strip("{} ").split(",") if ":" in item)
    return {key.strip(): scalar(value) for key, value in pairs}


def read_sections(text: str) -> dict[str, dict[str, object]]:
    """The `limits` and `rules` mappings, without PyYAML."""
    sections: dict[str, dict[str, object]] = {}
    current = None
    for line in text.splitlines():
        top, nested = SECTION.match(line), ENTRY.match(line)
        if top:
            current = sections.setdefault(top.group(1), {})
            if top.group(2).startswith("{"):
                current.update(flow(top.group(2)))
        elif nested and current is not None and nested.group(2):
            current[nested.group(1)] = scalar(nested.group(2))
    return sections


def parse(text: str) -> dict[str, dict[str, object]]:
    try:
        import yaml
    except ImportError:
        return read_sections(text)
    data = yaml.safe_load(text) or {}
    return {key: value for key, value in data.items() if isinstance(value, dict)}


def load(read) -> GodotGuard | None:
    """`read(path)` returns a repository file's text or None. None when the repository has no config."""
    text = read(CONFIG)
    if text is None:
        return None
    sections = parse(text)
    guard = GodotGuard()
    for name, value in sections.get("limits", {}).items():
        if isinstance(value, int):
            guard.limits[name] = value
    guard.levels = {name: "off" if value is False else value for name, value in sections.get("rules", {}).items()}
    baseline = json.loads(read(BASELINE) or "{}")
    guard.baseline = {rule: entries for rule, entries in baseline.items() if isinstance(entries, dict)}
    return guard
