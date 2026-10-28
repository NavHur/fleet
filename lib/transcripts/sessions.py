"""This machine's Claude Code and Codex sessions, each read with its format's reader."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import claude
import codex

HOME = Path.home()
ROOTS = {"claude": HOME / ".claude" / "projects", "codex": HOME / ".codex" / "sessions"}
PATTERNS = {"claude": ("*/*.jsonl", "*/*/subagents/*.jsonl"), "codex": ("*/*/*/rollout-*.jsonl",)}
READERS = {"claude": claude, "codex": codex}
CODEX_ID = re.compile(r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.jsonl$")


class NotFound(Exception):
    """No single session matches what the user gave."""


@dataclass
class Session:
    agent: str  # claude or codex
    path: Path

    @property
    def id(self):
        match = CODEX_ID.search(self.path.name) if self.agent == "codex" else None
        return match.group(1) if match else self.path.stem

    @cached_property
    def mtime(self):
        return self.path.stat().st_mtime

    def lines(self):
        return self.path.open(errors="replace")

    def summary(self):
        with self.lines() as lines:
            return READERS[self.agent].summary(lines)

    def events(self):
        with self.lines() as lines:
            yield from READERS[self.agent].events(lines)


def find(since=0.0, agents=tuple(ROOTS)):
    """The sessions written since `since` (epoch seconds), oldest first."""
    found = (Session(agent, path) for agent in agents for pattern in PATTERNS[agent]
             for path in ROOTS[agent].glob(pattern))
    return sorted((session for session in found if session.mtime >= since), key=lambda session: session.mtime)


def resolve(ref):
    """A session from its file's path, or from the start of its id."""
    path = Path(ref).expanduser()
    if path.is_file():
        return Session("codex" if path.name.startswith("rollout-") else "claude", path)
    matches = [session for session in find() if session.id.startswith(ref)]
    if len(matches) != 1:
        found = "no session" if not matches else f"{len(matches)} sessions"
        raise NotFound(f"{found} with an id starting {ref!r}; give more of the id or the file's path")
    return matches[0]
