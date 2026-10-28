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

from stack_layers import StackError, read_manifests


def changed_paths(base, source):
    diff = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", base, source],
        capture_output=True, text=True, check=True,
    )
    return set(diff.stdout.splitlines())


def layer_indexes(manifests):
    """{path: indexes of the layers taking it whole}, {path: indexes of the layers staging it}."""
    final, staged = defaultdict(list), defaultdict(list)
    for index, manifest in enumerate(manifests):
        for path in manifest.whole:
            final[path].append(index)
        for path in manifest.staged:
            staged[path].append(index)
    return final, staged


def final_errors(final, staged, changed, layers):
    errors = [
        f"duplicated: {path} in {', '.join(layers[i] for i in idx)} (stage the earlier ones as ~{path})"
        for path, idx in sorted(final.items()) if len(idx) > 1
    ]
    for path in sorted(changed - set(final)):
        errors.append(f"missing: {path}" + (" (staged, but no final layer)" if path in staged else ""))
    # a staged file may end where it started
    errors += [f"not changed: {path}" for path in sorted(set(final) - changed - set(staged))]
    return errors


def staged_errors(final, staged, changed, layers):
    errors = []
    for path, idx in sorted(staged.items()):
        if path in final and max(idx) >= min(final[path]):
            errors.append(f"staged at or after its final layer: {path} in {layers[max(idx)]}")
        if path not in final and path not in changed:
            errors.append(f"staged but no final layer: {path}")
    return errors


def missing_hooks(directory, staged_layers):
    """Staged layers without an executable hook for their ~paths."""
    return [
        f"no executable hooks/{layer} for its ~paths"
        for layer in staged_layers
        if not os.access(os.path.join(directory, "hooks", layer), os.X_OK)
    ]


def warn_missing_hooks(missing):
    for message in missing:
        print(f"warning: {message}; fix_layers.sh will 3-way merge them")


def main():
    args = [a for a in sys.argv[1:] if a != "--require-hooks"]
    require_hooks = len(args) != len(sys.argv) - 1
    if len(args) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    base, source, directory = args
    changed = changed_paths(base, source)
    try:
        manifests = read_manifests(directory)
    except StackError as error:
        sys.exit(str(error))
    layers = [manifest.name for manifest in manifests]
    staged_layers = [manifest.name for manifest in manifests if manifest.staged]
    final, staged = layer_indexes(manifests)

    errors = final_errors(final, staged, changed, layers) + staged_errors(final, staged, changed, layers)
    missing = missing_hooks(directory, staged_layers)
    if require_hooks:
        errors += missing
    else:
        warn_missing_hooks(missing)
    for error in errors:
        print(error)
    print(
        f"{len(layers)} layers, {len(changed)} changed files, {len(final)} final,"
        f" {len(staged)} staged in {len(staged_layers)} layers"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
