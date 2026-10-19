#!/usr/bin/env python3
"""Find comments with more than two lines of prose in changed source files.

Usage: long_comments.py BASE [HEAD] [--all] [--repo DIR]

  BASE, HEAD, --repo  as in measure_complexity.py (EMPTY scans every file).
  --all               also list long comments that no changed line touches.

A comment is a block comment or an unbroken run of line comments that each own
their line; a run of ten `//` lines is one comment. Prose lines exclude blank
lines, separator rules, references (a lone URL, `See docs/...`, a ticket such
as ENG-123), and tooling directives (`eslint-disable`, `# noqa`,
`@ts-expect-error`, `# gdlint:`, ...). Doc comments (`/** */`, Python
docstrings, GDScript `##`), comments after code on the same line, and license
headers are exempt. More than 2 prose lines is over the cap.

Each long comment is tagged with the repository rule that caps it, read from
the file's .oxlintrc.json (any `*/no-long-comment` rule that is on), or
`[not lint-checked]`. In a Godot repository with a `.godot-guard.yml`,
godot-guard 0.2+ judges each GDScript comment in the files it checks:
`[lint: godot-guard/long-comment]` when its `check` reports the comment
(`[lint: godot-guard/long-comment, warning]` at warn level), and
`[lint passes: godot-guard/long-comment]` when it does not (a file header,
its `comment-lines` cap, or the ratchet baseline).
Comments above a file's first line of code are marked `(file header)`, since
some repositories exempt them.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import godot_guard
from measure_complexity import is_off, owning_config, strip_jsonc
from revision import changed_files, changed_lines, git, language_of, read_file

CAP = 2
GUARD_RULE = "long-comment"
LINE_MARKERS = {"js": ("//",), "python": ("#",), "gdscript": ("#",), "php": ("//", "#")}
BLOCKS = {"js": (("/*", "*/"),), "php": (("/*", "*/"), ("{{--", "--}}"))}
MARKUP = {".svelte", ".vue", ".astro", ".php"}  # files that can hold <!-- --> comments
NOT_COMMENTS = ("##", "#[")  # GDScript doc comments, PHP attributes
DIRECTIVE = re.compile(
    r"^(!|-\*-|(es|ox|ts|style)lint|biome-|prettier-|istanbul |c8 |svelte-ignore|@ts-|global |"
    r"noqa|type:|pyright:|mypy:|pylint:|fmt:|isort:|ruff:|pragma|phpcs|@?phpstan|@?psalm|@codeCoverage|"
    r"gdlint|warning_ignore|#?(end)?region\b)", re.IGNORECASE)
REFERENCE = re.compile(r"^(see:?\s+)?(https?://\S+|[\w.-]*/[\w./#-]+|[A-Z][A-Z0-9]+-\d+)[.)]?$", re.IGNORECASE)
SEPARATOR = re.compile(r"^[-=*#/_~+]{3,}$")
LICENSE = re.compile(r"SPDX-License-Identifier|Copyright \(c\)|Copyright \d{4}|Licensed under", re.IGNORECASE)


@dataclass
class Comment:
    path: str
    line: int
    end_line: int
    body: list[str]
    header: bool = False

    @property
    def prose(self) -> int:
        return sum(1 for text in self.body if is_prose(text))


def is_prose(text: str) -> bool:
    text = text.strip().lstrip("*").strip()
    return bool(text) and not (DIRECTIVE.match(text) or REFERENCE.match(text) or SEPARATOR.match(text))


def strip_marker(text: str, markers: tuple[str, ...]) -> str | None:
    """Return a line comment's text, or None when the line is not one."""
    if text.startswith(NOT_COMMENTS):
        return None
    marker = next((m for m in markers if text.startswith(m)), None)
    return None if marker is None else text[len(marker):]


def python_comment_lines(source: str) -> dict[int, str] | None:
    """Own-line `#` comments, found by the tokenizer so strings are never mistaken for comments."""
    found: dict[int, str] = {}
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT and not token.line[:token.start[1]].strip():
                found[token.start[0]] = token.string[1:]
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return None
    return found


class Scanner:
    def __init__(self, path: str, source: str):
        self.path = path
        self.language = language_of(path)
        self.lines = source.splitlines()
        self.blocks = BLOCKS.get(self.language, ()) + ((("<!--", "-->"),) if PurePosixPath(path).suffix in MARKUP else ())
        self.python = python_comment_lines(source) if self.language == "python" else None
        self.comments: list[Comment] = []
        self.run: Comment | None = None

    def line_comment(self, number: int, stripped: str) -> str | None:
        if self.python is not None:
            return self.python.get(number)
        return strip_marker(stripped, LINE_MARKERS[self.language])

    def scan(self) -> list[Comment]:
        number = 0
        while number < len(self.lines):
            number += 1
            stripped = self.lines[number - 1].strip()
            opener = next((b for b in self.blocks if stripped.startswith(b[0])), None)
            text = None if opener else self.line_comment(number, stripped)
            if text is not None:
                self.extend_run(number, text)
                continue
            self.close_run()
            if opener:
                number = self.block(number, opener)
        self.close_run()
        return self.comments

    def extend_run(self, number: int, text: str) -> None:
        if self.run is None:
            self.run = Comment(self.path, number, number, [])
        self.run.end_line = number
        self.run.body.append(text)

    def close_run(self) -> None:
        if self.run is not None:
            self.comments.append(self.run)
        self.run = None

    def block(self, start: int, opener: tuple[str, str]) -> int:
        """Record the block comment opening on line `start` and return its last line."""
        begin, end = opener
        first = self.lines[start - 1].strip()[len(begin):]
        is_doc = begin == "/*" and first.startswith("*") and not first.startswith("*/")
        body, number, text = [], start, first
        while end not in text and number < len(self.lines):
            body.append(text)
            number += 1
            text = self.lines[number - 1]
        body.append(text.split(end, 1)[0])
        if not is_doc:
            self.comments.append(Comment(self.path, start, number, body))
        return number


def first_code_line(lines: list[str], comments: list[Comment]) -> int:
    commented = {n for c in comments for n in range(c.line, c.end_line + 1)}
    preamble = re.compile(r"^(<\?php|<script\b|---$|extends\b|class_name\b|@tool\b|@icon\b|\"\"\"|'''|$)")
    for number, raw in enumerate(lines, start=1):
        if number not in commented and not preamble.match(raw.strip()):
            return number
    return len(lines) + 1


def long_comments(path: str, source: str) -> list[Comment]:
    scanner = Scanner(path, source)
    comments = scanner.scan()
    first_code = first_code_line(scanner.lines, comments)
    found = []
    for comment in comments:
        if comment.prose > CAP and not LICENSE.search("\n".join(comment.body)):
            comment.header = comment.end_line < first_code
            found.append(comment)
    return found


def tracked(root: Path, head: str | None) -> list[str]:
    if head:
        return git(root, "ls-tree", "-r", "--name-only", "-z", head).split("\0")
    # the working tree, including files not committed yet
    return (git(root, "ls-files", "-z") + git(root, "ls-files", "--others", "--exclude-standard", "-z")).split("\0")


def enabled_rule(settings: dict) -> str | None:
    rules = settings.get("rules", {})
    return next((n for n, v in rules.items() if n.endswith("no-long-comment") and not is_off(v)), None)


def lint_rules(root: Path, head: str | None, files: list[str]) -> dict[str, str]:
    """Map each JS-family file to the enabled `*/no-long-comment` rule of its owning config."""
    configs = [p for p in tracked(root, head) if PurePosixPath(p).name == ".oxlintrc.json" and "node_modules/" not in p]
    owners = {path: owning_config(path, configs) for path in files if language_of(path) == "js"}
    rules = {config: enabled_rule(json.loads(strip_jsonc(read_file(root, head, config) or "{}")))
             for config in set(owners.values()) if config}
    return {path: rules[config] for path, config in owners.items() if rules.get(config)}


def lint_tags(root: Path, head: str | None, found: list[Comment], notes: list[str]) -> dict[tuple[str, int], str]:
    """Tags by (path, line) for comments under a repository lint rule; the rest are not lint-checked."""
    rules = lint_rules(root, head, sorted({c.path for c in found}))
    tags = {(c.path, c.line): f"[lint: {rules[c.path]}]" for c in found if c.path in rules}
    tags.update(guard_tags(root, head, found, notes))
    return tags


def guard_tags(root: Path, head: str | None, found: list[Comment], notes: list[str]) -> dict[tuple[str, int], str]:
    """godot-guard's verdict on each GDScript comment in a file it checks with `long-comment` on."""
    paths = sorted({c.path for c in found if language_of(c.path) == "gdscript"})
    guard = godot_guard.check(root, head, paths, notes)
    if guard is None or guard.severity(GUARD_RULE) is None:
        return {}
    return {(c.path, c.line): guard_tag(guard, c) for c in found if c.path in guard.files}


def guard_tag(guard: godot_guard.Verdicts, comment: Comment) -> str:
    severity = guard.at(GUARD_RULE, comment.path, comment.line)
    if severity is None:
        return f"[lint passes: godot-guard/{GUARD_RULE}]"
    suffix = ", warning" if severity == "warning" else ""
    return f"[lint: godot-guard/{GUARD_RULE}{suffix}]"


def touches(comment: Comment, lines: dict[str, set[int] | None]) -> bool:
    touched = lines.get(comment.path)
    return touched is None or any(comment.line <= n <= comment.end_line for n in touched)


def report(found: list[Comment], tags: dict[tuple[str, int], str], file_count: int, notes: list[str]) -> None:
    shown = [tags.get((c.path, c.line), "[not lint-checked]") for c in found]
    for comment, tag in zip(found, shown):
        header = " (file header)" if comment.header else ""
        print(f"{comment.path}:{comment.line}-{comment.end_line}: {comment.prose} prose lines{header} {tag}")
    if notes:
        print("\nCoverage notes:")
        for note in notes:
            print(f"  {note}")
    enforced = sum(tag.startswith("[lint:") for tag in shown)
    passing = sum(tag.startswith("[lint passes") for tag in shown)
    print(f"\nResult: {len(found)} comment{'s' if len(found) != 1 else ''} over the cap in {file_count} changed "
          f"source files: {enforced} under a repository lint rule, {passing} that lint passes, "
          f"{len(found) - enforced - passing} not lint-checked.")


def resolve_base(root: Path, base: str, head: str | None) -> str:
    if base == "EMPTY":  # whole-repository scope: diff from the empty tree
        return git(root, "hash-object", "-t", "tree", "/dev/null").strip()
    return git(root, "merge-base", base, head or "HEAD").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base")
    parser.add_argument("head", nargs="?")
    parser.add_argument("--all", action="store_true", help="list long comments on unchanged lines too")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()

    root = Path(git(Path(args.repo), "rev-parse", "--show-toplevel").strip())
    merge_base = resolve_base(root, args.base, args.head)
    files = changed_files(root, merge_base, args.head)
    lines = changed_lines(root, merge_base, args.head, files) if files else {}
    print(f"Long comments in {root} {args.base}..{args.head or 'working tree'} (merge-base {merge_base[:10]})")
    print(f"Pedro's cap: {CAP} lines of prose per comment\n")
    found = [comment for path in files for comment in long_comments(path, read_file(root, args.head, path) or "")
             if args.all or touches(comment, lines)]
    notes: list[str] = []
    report(found, lint_tags(root, args.head, found, notes), len(files), notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
