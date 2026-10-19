#!/usr/bin/env python3
"""Count the configuration surface of changed GDScript scripts against the cap of 8.

Usage: godot_interface.py BASE [HEAD] [--all] [--repo DIR]

  BASE, HEAD, --repo  as in measure_complexity.py (EMPTY measures every script).
  --all               list every counted script, not only those over the cap.

A script's configuration surface is what a parent decides when it uses the
script: its top-level `@export` variables (group, subgroup, and category
annotations are not variables), its signals, and the parameters of `_init`
and of a `setup` or `configure` method. Resource scripts are data
definitions and are excluded: a script whose `extends` chain reaches
`Resource` through this repository's `class_name` declarations. Inner classes
are not counted. More than 8 is over the cap; 7 and 8 pass.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from revision import changed_files, git, read_file

CAP = 8
NOT_VARIABLES = {"export_group", "export_subgroup", "export_category"}
SETUP_METHODS = ("_init", "setup", "configure")


@dataclass
class Surface:
    path: str
    extends: str = ""
    class_name: str = ""
    signals: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    parameters: dict[str, list[str]] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.signals) + len(self.exports) + sum(len(p) for p in self.parameters.values())


def split_top_level(text: str) -> list[str]:
    """Split on commas outside brackets and strings."""
    parts, depth, current, quote = [], 0, "", ""
    for ch in text:
        if quote:
            current += ch
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote, current = ch, current + ch
        elif ch in "([{":
            depth, current = depth + 1, current + ch
        elif ch in ")]}":
            depth, current = depth - 1, current + ch
        elif ch == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    return [p.strip() for p in parts if p.strip()]


def parameters_after(source: str, start: int) -> list[str]:
    """Parameter names of the signature whose `(` is at or after `start`."""
    open_at = source.index("(", start)
    depth = 0
    for index in range(open_at, len(source)):
        depth += {"(": 1, ")": -1}.get(source[index], 0)
        if depth == 0:
            return [re.split(r"[:=\s]", p, maxsplit=1)[0] for p in split_top_level(source[open_at + 1: index])]
    return []


def parse(path: str, source: str) -> Surface:
    surface = Surface(path)
    pending: list[str] = []  # annotations on their own lines, waiting for a var
    for match in re.finditer(r"^(?P<line>\S.*)$", source, re.M):
        line = match.group("line")
        if line.startswith("#"):
            continue
        if found := re.match(r"extends\s+([\w.\"/]+)", line):
            surface.extends = found.group(1).strip('"')
        if found := re.match(r"class_name\s+(\w+)(?:\s+extends\s+([\w.]+))?", line):
            surface.class_name = found.group(1)
            surface.extends = found.group(2) or surface.extends
        if found := re.match(r"signal\s+(\w+)", line):
            surface.signals.append(found.group(1))
        annotations = re.findall(r"@(\w+)", line.split("var ", 1)[0]) if line.startswith("@") else []
        if re.search(r"(^|\s)var\s+\w+", line) and not line.startswith(("func", "static func")):
            names = annotations + pending
            if any(a.startswith("export") and a not in NOT_VARIABLES for a in names):
                surface.exports.append(re.search(r"var\s+(\w+)", line).group(1))
            pending = []
        elif annotations and "var " not in line:
            pending += [a for a in annotations if a not in NOT_VARIABLES]
        else:
            pending = []
        if found := re.match(r"(?:static\s+)?func\s+(\w+)\s*\(", line):
            if found.group(1) in SETUP_METHODS:
                surface.parameters[found.group(1)] = parameters_after(source, match.start())
    return surface


def is_resource(surface: Surface, by_class: dict[str, Surface], by_path: dict[str, Surface]) -> bool:
    seen, current = set(), surface.extends
    while current and current not in seen:
        if current == "Resource":
            return True
        seen.add(current)
        parent = by_class.get(current) or by_path.get(current.replace("res://", ""))
        current = parent.extends if parent else ""
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base")
    parser.add_argument("head", nargs="?")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()

    root = Path(git(Path(args.repo), "rev-parse", "--show-toplevel").strip())
    if args.base == "EMPTY":
        merge_base = git(root, "hash-object", "-t", "tree", "/dev/null").strip()
    else:
        merge_base = git(root, "merge-base", args.base, args.head or "HEAD").strip()
    changed = [p for p in changed_files(root, merge_base, args.head) if p.endswith(".gd")]
    listing = git(root, "ls-tree", "-r", "--name-only", "-z", args.head) if args.head else git(root, "ls-files", "-z")
    every = [p for p in listing.split("\0") if p.endswith(".gd")]
    surfaces = {p: parse(p, read_file(root, args.head, p) or "") for p in sorted(set(every) | set(changed))}
    by_class = {s.class_name: s for s in surfaces.values() if s.class_name}

    print(f"Godot configuration surface of {root} {args.base}..{args.head or 'working tree'} (cap {CAP})")
    counted = over = resources = 0
    for path in changed:
        surface = surfaces[path]
        if is_resource(surface, by_class, surfaces):
            resources += 1
            continue
        counted += 1
        if surface.total > CAP:
            over += 1
        if surface.total > CAP or args.all:
            flag = "  OVER" if surface.total > CAP else ""
            print(f"\n{path} (extends {surface.extends or '?'}): {surface.total}{flag}")
            if surface.exports:
                print(f"  @export {len(surface.exports)}: {', '.join(surface.exports)}")
            if surface.signals:
                print(f"  signals {len(surface.signals)}: {', '.join(surface.signals)}")
            for method, names in surface.parameters.items():
                if names:
                    print(f"  {method}() parameters {len(names)}: {', '.join(names)}")
    print(f"\nResult: {over} script{'s' if over != 1 else ''} over the cap among {counted} changed scripts "
          f"({resources} Resource script{'s' if resources != 1 else ''} excluded).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
