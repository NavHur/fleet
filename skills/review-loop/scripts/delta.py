#!/usr/bin/env python3
"""Write each layer's delta between two review rounds.

    delta.py --prev PREV_HEADS.tsv --heads HEADS.tsv --out DIR [--manifests DIR] [--repo DIR]

Heads files come from `stack_layers.py heads`: one line per PR, bottom to top,
PR<TAB>LAYER<TAB>FORK<TAB>HEAD. With --manifests (split-stacked-prs layout) a
layer's delta is restricted to the files its manifest owns, so fixes carried
up from lower layers stay out of it; without, the delta is the whole
PREV_HEAD..HEAD diff. A rebase shows up as the base's changes merged into
those files, which is what a hand-resolved conflict looks like. Writes
DIR/delta-<KEY>.diff (KEY is the PR, percent-encoded) for every non-empty
delta and prints PR, layer, changed size (bytes of added and deleted lines,
measured by diff_budget.py) and whether it gets an audit: audit=yes when files
pedro-best-practices audits changed and the delta reaches AUDIT_MIN_BYTES.
Below that, the delta reviewer owns Pedro's rules and the orchestrator has
already measured the fixes' complexity and comments.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

SKILLS = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(SKILLS / "split-stacked-prs" / "scripts"), str(SKILLS / "pedro-best-practices" / "scripts")]

from diff_budget import changed_files  # noqa: E402
from loop_state import LoopError, pr_file_key, read_heads  # noqa: E402
from revision import language_of  # noqa: E402
from stack_layers import StackError, read_manifest  # noqa: E402

AUDIT_MIN_BYTES = 3000


def owned_paths(manifests: Path | None, layer: str) -> tuple[str, ...]:
    """The layer's manifest paths, or () for the whole diff."""
    if manifests is None:
        return ()
    path = manifests / layer
    if not path.is_file():
        raise StackError(f"no manifest {path}")
    return read_manifest(path).paths


def layer_delta(pr: str, layer: str, old: str, head: str, paths: tuple[str, ...], out: Path) -> str:
    """Write the layer's delta file and return its report line."""
    result = subprocess.run(["git", "diff", old, head, "--", *paths], capture_output=True)
    if result.returncode != 0:
        raise LoopError(result.stderr.decode().strip() or f"git diff {old} {head} failed")
    diff = result.stdout
    if not diff:
        return f"{pr} {layer}: no delta"
    file = out / f"delta-{pr_file_key(pr)}.diff"
    file.write_bytes(diff)
    changed = changed_files(old, head, paths)
    size = sum((added or 0) + (deleted or 0) for _, _, added, deleted in changed)
    audited = any(language_of(name) for old_path, path, _, _ in changed for name in (old_path, path) if name)
    return f"{pr} {layer}: {size / 1000:.1f} KB, {audit_verdict(audited, size)} -> {file}"


def audit_verdict(audited: bool, size: int) -> str:
    if not audited:
        return "audit=no"
    if size < AUDIT_MIN_BYTES:
        return f"audit=no (under {AUDIT_MIN_BYTES / 1000:.0f} KB)"
    return "audit=yes"


def report(args) -> list[str]:
    previous, current_heads = read_heads(args.prev), read_heads(args.heads)
    out = Path(os.path.abspath(args.out))
    out.mkdir(parents=True, exist_ok=True)
    manifests = Path(os.path.abspath(args.manifests)) if args.manifests else None
    os.chdir(args.repo)
    lines = []
    for pr, current in current_heads.items():
        if pr not in previous:
            lines.append(f"{pr} {current.layer}: new in this round, review it whole")
            continue
        paths = owned_paths(manifests, current.layer)
        lines.append(layer_delta(pr, current.layer, previous[pr].head, current.head, paths, out))
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prev", type=Path, required=True)
    parser.add_argument("--heads", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifests", type=Path)
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args()
    try:
        lines = report(args)
    except (LoopError, StackError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 2
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
