"""The command walk: each command a shell string runs, as a Leaf with the
directory it runs in.

    leaves(command, cwd) -> Iterator[Leaf]

Every shell-command judge reads leaves: guard.py, jobclass.py,
merge_method.py, commit_guard.py, the pre-commit skill's ci_covers.py, and
the workbox hooks. The walk follows `cd` and expands a command word stored in
a variable. Not a shell implementation: it recognizes the common spellings
(docs/adr/0001-command-walk-recognizes-spellings.md).
"""
from __future__ import annotations

import dataclasses
import os
import re
import shlex

from shell import ASSIGNMENT, PREFIXES, commands


@dataclasses.dataclass(frozen=True)
class Leaf:
    """A command a shell string runs.

    words: the command and its arguments, past keywords and assignments.
    cwd: the directory it runs in.
    subshell: it runs inside `$(...)`.
    background: a lone `&` ends it.
    env: the assignments it sees: its prefixes and those made before it.
    """
    words: list
    cwd: str
    subshell: bool = False
    background: bool = False
    env: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class Frame:
    """What the leaves of one walk inherit from the command that started it."""
    env: tuple = ()
    subshell: bool = False
    background: bool = False

    def inside(self, segment, variables):
        """The frame of one simple command, with the variables set before it."""
        return dataclasses.replace(self, env=self.env + tuple(variables.items()),
                                   subshell=self.subshell or segment.subshell,
                                   background=self.background or segment.background)

    def leaf(self, words, cwd, assigned):
        return Leaf(list(words), cwd, self.subshell, self.background, {**dict(self.env), **assigned})


def leaves(command, cwd):
    """Each command a shell string runs, in order. Raises ValueError for a string shlex cannot parse."""
    return walk_text(command, cwd, Frame())


def walk_text(text, cwd, frame):
    for segment, words, here, variables in sequence(text, cwd):
        yield from follow(words, here, frame.inside(segment, variables))


def follow(words, cwd, frame):
    words, assigned = command_part(words)
    if words:
        yield frame.leaf(words, cwd, assigned)


def command_part(words):
    """The words from the command itself, past keywords such as `then` and `!`, and the assignments before it."""
    assigned, start = {}, 0
    while start < len(words) and (ASSIGNMENT.match(words[start]) or words[start] in PREFIXES):
        name, eq, value = words[start].partition("=")
        if eq:
            assigned[name.rstrip("+")] = value
        start += 1
    return words[start:], assigned


# --- Sequence -------------------------------------------------------------------

VARIABLE = re.compile(r"^\$\{?([A-Za-z_][A-Za-z_0-9]*)\}?(.*)$")
NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
DECLARATIONS = {"export", "local", "declare", "readonly"}


def sequence(text, cwd):
    """Each simple command as (segment, words, directory, variables set before it).

    Follows `cd DIR`, and expands a command word set earlier by a plain
    assignment (`H=/path/host-check; "$H" pnpm lint`, `G="git -C dir"; $G log`).
    """
    variables = {}
    for segment in commands(text):
        remember(segment.words, variables)
        words = expand_command_word(segment.words, variables)
        yield segment, words, cwd, dict(variables)
        if words[:1] in (["cd"], ["pushd"]) and not segment.subshell:
            cwd = moved(cwd, words)


def remember(words, variables):
    """Record the variables a command made only of assignments sets."""
    lead = 1 if words[:1] and words[0] in DECLARATIONS else 0
    if not words[lead:] or not all(ASSIGNMENT.match(word) for word in words[lead:]):
        return
    for word in words[lead:]:
        name, _, value = word.partition("=")
        if NAME.fullmatch(name):
            variables[name] = value


def expand_command_word(words, variables):
    start = next((i for i, word in enumerate(words) if not (ASSIGNMENT.match(word) or word in PREFIXES)), len(words))
    found = VARIABLE.match(words[start]) if start < len(words) else None
    if not found or found.group(1) not in variables:
        return words
    try:
        return words[:start] + shlex.split(variables[found.group(1)] + found.group(2)) + words[start + 1:]
    except ValueError:
        return words


def moved(cwd, words):
    """The directory after `cd TARGET`; a target built from `$` leaves it unchanged."""
    target = next((word for word in words[1:] if not word.startswith("-")), "~")
    return cwd if "$" in target else os.path.normpath(os.path.join(cwd, os.path.expanduser(target)))
