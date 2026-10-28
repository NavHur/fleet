#!/usr/bin/env python3
"""Check that layer manifests assign every changed file a final layer exactly once.

A manifest directory holds one file per layer, named so that sorting gives the
stack order (01-contract, 02-domain, ...); the format is in lib.sh. A plain
path is the file's final layer, which takes the source version whole. A ~path
is an in-between version that hooks/<layer> writes; it may appear in several
layers, all below the path's final layer. Deleted files belong in the layer
that removes them.

Usage:
  check_manifests.py BASE SOURCE MANIFEST_DIR [--require-hooks]
--require-hooks (build_layers.sh) makes a staged layer without an executable
hook an error; otherwise it is a warning, since fix_layers.sh can 3-way merge.
Exit status 1 on a missing, duplicated, unchanged or misplaced path.
"""

import os
import subprocess
import sys
from collections import defaultdict


def read_manifest(path):
    whole, staged = [], []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("~"):
                staged.append(line[1:].strip())
            else:
                whole.append(line)
    return whole, staged


def main():
    args = [a for a in sys.argv[1:] if a != "--require-hooks"]
    require_hooks = len(args) != len(sys.argv) - 1
    if len(args) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    base, source, directory = args
    changed = set(
        subprocess.run(
            ["git", "diff", "--name-only", "--no-renames", base, source],
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
    )
    layers = sorted(
        f for f in os.listdir(directory)
        if not f.startswith(".") and os.path.isfile(os.path.join(directory, f))
    )
    final = defaultdict(list)  # path -> layers taking it whole
    staged = defaultdict(list)  # path -> layers staging it
    staged_layers = []
    for index, layer in enumerate(layers):
        whole_paths, staged_paths = read_manifest(os.path.join(directory, layer))
        for path in whole_paths:
            final[path].append(index)
        for path in staged_paths:
            staged[path].append(index)
        if staged_paths:
            staged_layers.append(layer)

    errors = []
    for path, idx in sorted(final.items()):
        if len(idx) > 1:
            errors.append(f"duplicated: {path} in {', '.join(layers[i] for i in idx)} (stage the earlier ones as ~{path})")
    for path in sorted(changed - set(final)):
        errors.append(f"missing: {path}" + (" (staged, but no final layer)" if path in staged else ""))
    for path in sorted(set(final) - changed):
        if path not in staged:  # a staged file may end where it started
            errors.append(f"not changed: {path}")
    for path, idx in sorted(staged.items()):
        if path in final and max(idx) >= min(final[path]):
            errors.append(f"staged at or after its final layer: {path} in {layers[max(idx)]}")
        if path not in final and path not in changed:
            errors.append(f"staged but no final layer: {path}")
    for layer in staged_layers:
        hook = os.path.join(directory, "hooks", layer)
        if not os.access(hook, os.X_OK):
            message = f"no executable hooks/{layer} for its ~paths"
            if require_hooks:
                errors.append(message)
            else:
                print(f"warning: {message}; fix_layers.sh will 3-way merge them")

    for error in errors:
        print(error)
    print(
        f"{len(layers)} layers, {len(changed)} changed files, {len(final)} final,"
        f" {len(staged)} staged in {len(staged_layers)} layers"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
