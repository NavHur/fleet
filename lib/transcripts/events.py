"""The shapes both transcript formats read into: events for `show`, a summary for `list` and `usage`."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# Hook and harness context wrapped around a user's words.
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


@dataclass(frozen=True)
class Event:
    kind: str  # user, assistant, tool, result, or compaction
    text: str
    name: str = ""  # the tool, for a tool event
    error: bool = False  # a result the tool reported as failed


@dataclass(frozen=True)
class Tokens:
    fresh: int = 0  # input read without the cache
    write: int = 0  # input written to the cache
    read: int = 0  # input read from the cache
    out: int = 0

    def __add__(self, other):
        return Tokens(self.fresh + other.fresh, self.write + other.write, self.read + other.read, self.out + other.out)

    @property
    def total(self):
        return self.fresh + self.write + self.read + self.out


@dataclass
class Summary:
    cwd: str = ""
    started: str = ""  # ISO timestamp of the first record that has one
    title: str = ""
    prompt: str = ""  # the first thing the user or the delegating task asked
    tokens: dict = field(default_factory=dict)  # model -> Tokens

    def add(self, model, tokens):
        self.tokens[model] = self.tokens.get(model, Tokens()) + tokens


def records(lines):
    """Each line's JSON object, skipping lines that are not one (a write cut short)."""
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            yield record


def as_text(value):
    """Text from a string, a list of content blocks, or anything JSON can show."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(block.get("text", "") for block in value if isinstance(block, dict))
    return json.dumps(value)


def prompt_text(text):
    """The user's words without the reminders wrapped around them."""
    return REMINDER.sub("", text).strip()
