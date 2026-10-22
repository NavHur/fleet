"""Diff two complexity analyzers function by function.

Usage:
  python3 complexity_parity.py --reference CMD --candidate CMD [--gdscript-names]
                               (--repo DIR --glob PATTERN... | --files-from LIST | FILE...)

Each CMD is a shell-quoted analyzer command that takes FILE... and prints the
JSON measure_complexity.py reads: {path: [function] or {"error": message}}.
Functions are matched by (path, line, position among the functions starting
on that line), and every field is compared: name, end_line, cognitive, and
cyclomatic. A file one analyzer rejects must be rejected by the other; the
error messages may differ.

It held the Rust analyzers to the Python ones they replaced (complexity_*.py,
in git history); it now holds a changed analyzer to the previous build, e.g.
`--reference "/tmp/old/pbp-complexity python" --candidate "target/release/pbp-complexity python"`.

--gdscript-names accepts godot-guard's more specific names for what the
retired gdtoolkit analyzer called `<lambda>`, `set`, and `get`:
`outer.<lambda#2>`, `outer.named`, `hp.set`. Every other field stays exact.

Exits 0 when the outputs agree, 1 on any difference, printing each one.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

BATCH = 200
FIELDS = ("end_line", "cognitive", "cyclomatic")


def run(command: str, files: list[str]) -> dict[str, object]:
    report: dict[str, object] = {}
    for start in range(0, len(files), BATCH):
        batch = files[start:start + BATCH]
        result = subprocess.run([*shlex.split(command), *batch], capture_output=True, text=True)
        if result.returncode != 0:
            sys.exit(f"{command!r} exited {result.returncode}: {result.stderr.strip()[:500]}")
        report.update(json.loads(result.stdout))
    return report


def keyed(functions: list[dict]) -> dict[tuple[int, int], dict]:
    """(line, position on that line) -> function."""
    seen: dict[int, int] = defaultdict(int)
    out = {}
    for function in functions:
        line = function["line"]
        out[(line, seen[line])] = function
        seen[line] += 1
    return out


def same_name(reference: str, candidate: str, gdscript_names: bool) -> bool:
    if reference == candidate or not gdscript_names:
        return reference == candidate
    if reference == "<lambda>":
        return re.fullmatch(r"(.+\.)?<lambda#\d+>", candidate) is not None
    scope, _, last = reference.rpartition(".")
    prefix = re.escape(f"{scope}.") if scope else ""
    if last in ("set", "get"):  # `Inner.get` is the accessor of some property `p`: `Inner.p.get`
        return re.fullmatch(rf"{prefix}[^.]+\.{last}", candidate) is not None
    return "." in candidate and candidate.rsplit(".", 1)[-1] == reference


def compare_file(path: str, reference: object, candidate: object, gdscript_names: bool) -> list[str]:
    if isinstance(reference, dict) or isinstance(candidate, dict):
        if isinstance(reference, dict) and isinstance(candidate, dict):
            return []
        return [f"{path}: reference {describe(reference)}, candidate {describe(candidate)}"]
    ours, theirs = keyed(reference), keyed(candidate)
    problems = []
    for key in sorted(ours.keys() | theirs.keys()):
        left, right = ours.get(key), theirs.get(key)
        where = f"{path}:{key[0]}"
        if left is None or right is None:
            problems.append(f"{where}: only in {'candidate' if left is None else 'reference'}: {left or right}")
            continue
        if not same_name(left["name"], right["name"], gdscript_names):
            problems.append(f"{where}: name {left['name']!r} != {right['name']!r}")
        for field in FIELDS:
            if left[field] != right[field]:
                problems.append(f"{where} {left['name']}: {field} {left[field]} != {right[field]}")
    return problems


def describe(value: object) -> str:
    return f"error ({value.get('error')})" if isinstance(value, dict) else f"{len(value)} function(s)"


def files_from(args) -> list[str]:
    if args.files_from:
        return [str(Path(f).resolve()) for f in Path(args.files_from).read_text().splitlines() if f]
    if not args.repo:
        return [str(Path(f).resolve()) for f in args.files]
    listed = subprocess.run(["git", "-C", args.repo, "ls-files", "--", *args.glob],
                            capture_output=True, text=True, check=True).stdout.split()
    return [str((Path(args.repo) / f).resolve()) for f in listed]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--gdscript-names", action="store_true")
    parser.add_argument("--repo")
    parser.add_argument("--glob", nargs="+", default=[])
    parser.add_argument("--files-from", help="a file listing one path per line, for corpora outside git")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()
    files = files_from(args)
    if not files:
        sys.exit("no files to compare")
    reference, candidate = run(args.reference, files), run(args.candidate, files)
    problems = []
    for path in files:
        if path not in reference or path not in candidate:
            problems.append(f"{path}: missing from {'reference' if path not in reference else 'candidate'}")
            continue
        problems += compare_file(path, reference[path], candidate[path], args.gdscript_names)
    functions = sum(len(v) for v in reference.values() if isinstance(v, list))
    errors = sum(isinstance(v, dict) for v in reference.values())
    for problem in problems:
        print(problem)
    print(f"{len(files)} file(s), {functions} function(s), {errors} rejected file(s): "
          f"{len(problems)} difference(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
