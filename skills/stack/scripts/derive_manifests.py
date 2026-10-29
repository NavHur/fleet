#!/usr/bin/env python3
"""Write layer manifests for an existing stack, so fix_layers.sh, layer_gates.sh
and refresh_stack.py work on a stack built one layer at a time (gh stack add,
hand-made branches) as well as on one from build_layers.sh.

The layers come from `gh stack view --json` (run from a branch of the stack;
merged layers are skipped), or from --branches bottom to top with --base.
Each manifest lists `git diff --name-only parent...layer`, carries
`# branch:` and `# pr:` headers, and the first one `# base:`. A path changed
by several layers is plain in the highest one and ~staged in the lower ones
(format in lib.sh).

Usage:
  derive_manifests.py --out DIR                       # from gh stack view --json
  derive_manifests.py --out DIR --base REF --branches B1 B2 ...
"""

import argparse
import json
import os
import re
import subprocess
import sys


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def from_gh():
    out = subprocess.run(["gh", "stack", "view", "--json"], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"gh stack view --json failed (run it from a branch of the stack):\n{out.stderr.strip()}")
    data = json.loads(out.stdout)
    layers, base = [], None
    for entry in data["branches"]:
        if entry.get("isMerged"):
            base = entry["name"]  # the next layer sits on the merged one
            continue
        layers.append((entry["name"], (entry.get("pr") or {}).get("number")))
    if not layers:
        sys.exit("every layer of this stack is merged")
    if base is None:
        # The fork point from the trunk; gh's recorded base can be stale.
        first = data["branches"][0]["name"]
        trunk = data.get("trunk") or "main"
        if run_ok("git", "rev-parse", "--verify", "-q", f"origin/{trunk}"):
            trunk = f"origin/{trunk}"
        base = git("merge-base", trunk, first)
        recorded = data["branches"][0].get("base")
        if recorded and run_ok("git", "merge-base", "--is-ancestor", base, recorded) \
                and run_ok("git", "merge-base", "--is-ancestor", recorded, first):
            base = recorded
    return git("rev-parse", base), layers


def run_ok(*args):
    return subprocess.run(args, capture_output=True).returncode == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="manifest directory to create")
    parser.add_argument("--base", help="the stack's base (with --branches)")
    parser.add_argument("--branches", nargs="+", help="layer branches, bottom to top")
    parser.add_argument("--force", action="store_true", help="replace existing manifests in --out")
    args = parser.parse_args()

    if args.branches:
        if not args.base:
            parser.error("--branches needs --base")
        base = git("merge-base", args.base, args.branches[0])
        layers = [(b, None) for b in args.branches]
    else:
        base, layers = from_gh()

    os.makedirs(args.out, exist_ok=True)
    existing = [f for f in os.listdir(args.out) if os.path.isfile(os.path.join(args.out, f)) and not f.startswith(".")]
    if existing and not args.force:
        sys.exit(f"{args.out} already has manifests ({', '.join(sorted(existing))}); pass --force to replace them")
    for f in existing:
        os.remove(os.path.join(args.out, f))

    paths_of, owners = [], {}
    parent = base
    for index, (branch, _) in enumerate(layers):
        paths = git("-c", "core.quotePath=false", "diff", "--name-only", "--no-renames", f"{parent}...{branch}").splitlines()
        paths_of.append(paths)
        for path in paths:
            owners[path] = index  # the highest layer wins
        parent = branch

    width = max(2, len(str(len(layers))))
    for index, (branch, pr) in enumerate(layers):
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", branch.rsplit("/", 1)[-1])
        name = f"{index + 1:0{width}d}-{slug}"
        lines = [f"# branch: {branch}"]
        if pr:
            lines.append(f"# pr: {pr}")
        if index == 0:
            lines.append(f"# base: {base}")
        staged = 0
        for path in paths_of[index]:
            if owners[path] == index:
                lines.append(path)
            else:
                lines.append(f"~{path}")
                staged += 1
        with open(os.path.join(args.out, name), "w") as fh:
            fh.write("\n".join(lines) + "\n")
        print(f"{name}: {branch} ({len(paths_of[index])} paths, {staged} also changed higher up)" + (f" PR #{pr}" if pr else ""))
    print(f"base {base[:12]}; manifests in {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
