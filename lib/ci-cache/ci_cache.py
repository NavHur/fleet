#!/usr/bin/env python3
"""Runner-local CI state for self-hosted runners, kept on the runner's disk between jobs.

`passed` remembers each tree a job passed, so a later run on the same tree (a merge commit whose
tree the pull request already tested) can skip its work. `godot` keeps a Godot project's `.godot`
directory and `.import` files per cache key, replacing actions/cache's upload and download.

State lives under $FLEET_CI_STATE, default ~/.cache/fleet-ci, one directory per repository
($GITHUB_REPOSITORY). Run from the checkout's root:
`ci_cache.py passed-check KEY`, `passed-record KEY`, `godot-restore PREFIX`, `godot-save KEY`.
"""

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PASS_MAX_AGE_S = 30 * 24 * 3600
GODOT_ENTRIES_KEPT = 3
GODOT_DIR = ".godot"
TRASH_PREFIX = ".trash-"
# Sources Godot imports. Godot re-imports any whose modification time moved, so restore pins them all.
IMPORTED = re.compile(r"\.(import|png|jpe?g|webp|svg|wav|ogg|mp3|ttf|otf|woff2?|glb|gltf|fbx|obj)$", re.I)


def state_root():
    base = os.environ.get("FLEET_CI_STATE") or os.path.expanduser("~/.cache/fleet-ci")
    return Path(base) / os.environ["GITHUB_REPOSITORY"]


def entry_name(key):
    """A key as a file name: keys hold arbitrary text, so they are hashed."""
    return hashlib.sha256(key.encode()).hexdigest()


def head_tree():
    return subprocess.run(["git", "rev-parse", "HEAD^{tree}"], check=True, capture_output=True,
                          text=True).stdout.strip()


def set_output(name, value):
    print(f"{name}={value}")
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as output:
            output.write(f"{name}={value}\n")


def pass_stamp(key):
    return state_root() / "passed" / entry_name(f"{head_tree()}\n{key}")


def passed_check(key):
    set_output("hit", "true" if pass_stamp(key).exists() else "false")


def passed_record(key):
    stamp = pass_stamp(key)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.touch()
    cutoff = time.time() - PASS_MAX_AGE_S
    for old in stamp.parent.iterdir():
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)


def import_files(root):
    """The `.import` files in the checkout, outside .git and .godot, as paths relative to it."""
    found = []
    for directory, subdirs, files in os.walk(root):
        if directory == str(root):
            subdirs[:] = [name for name in subdirs if name not in (".git", GODOT_DIR)]
        found += [Path(directory, name).relative_to(root) for name in files if name.endswith(".import")]
    return sorted(found)


def pinned_assets(tracked):
    """The tracked files to pin: each `.import` file with its source, and every file of an imported type."""
    pinned = set()
    for path in tracked:
        if IMPORTED.search(path):
            pinned.add(path)
        if path.endswith(".import") and Path(path[: -len(".import")]).is_file():
            pinned.add(path[: -len(".import")])
    return pinned


def pinned_assets_key(prefix):
    """Pin the assets to mtime 0; the key hashes them and project.godot.

    The assets are every tracked `.import` file with its source, plus every tracked file of a type
    Godot imports, for projects that gitignore `.import`. Pinned times make Godot's import of a
    restored entry a no-op for unchanged assets, and the key makes a hit mean identical assets.
    """
    listed = subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True).stdout
    pinned = pinned_assets(listed.decode().split("\0"))
    digest = hashlib.sha256()
    for name in sorted(pinned):
        os.utime(name, (0, 0))
        digest.update(name.encode() + b"\0" + hashlib.sha256(Path(name).read_bytes()).digest())
    digest.update(Path("project.godot").read_bytes())
    return f"{prefix}-{digest.hexdigest()}"


def godot_restore(prefix):
    """Pin the assets, then copy the entry saved under their key over the checkout, times kept.

    Prints the key as the `key` output, for `save` after the job's work.
    """
    key = pinned_assets_key(prefix)
    set_output("key", key)
    entry = state_root() / "godot" / entry_name(key)
    if not entry.is_dir():
        set_output("hit", "false")
        return
    shutil.copytree(entry, Path.cwd(), symlinks=True, dirs_exist_ok=True)
    os.utime(entry)
    set_output("hit", "true")


def godot_save(key):
    """Save the checkout's `.godot` and `.import` files under the key, unless it is already saved."""
    root = Path.cwd()
    if not (root / GODOT_DIR).is_dir():
        sys.exit(f"ci-cache: cannot save {key}: {root / GODOT_DIR} is missing")
    entries = state_root() / "godot"
    entry = entries / entry_name(key)
    if entry.is_dir():
        print(f"ci-cache: {key} is already saved")
        return
    entries.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=entries, prefix=".staging-"))
    try:
        shutil.copytree(root / GODOT_DIR, staging / GODOT_DIR, symlinks=True)
        for path in import_files(root):
            (staging / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / path, staging / path)
        # A rename is atomic, so a concurrent restore sees the whole entry or none of it.
        staging.rename(entry)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    prune(entries)
    print(f"ci-cache: saved {key}")


def prune(entries):
    for leftover in entries.glob(f"{TRASH_PREFIX}*"):
        remove_tree(leftover)
    saved = [path for path in entries.iterdir() if path.is_dir() and not path.name.startswith(".")]
    saved.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for old in saved[GODOT_ENTRIES_KEPT:]:
        # Renamed first, atomically, so a restore never sees a half-deleted entry.
        try:
            trash = old.rename(old.with_name(TRASH_PREFIX + old.name))
        except OSError as error:
            print(f"ci-cache: warning: could not prune {old}: {error}", file=sys.stderr)
            continue
        remove_tree(trash)


def remove_tree(path):
    """Delete a directory; a failure warns, since pruning must not fail the job."""
    try:
        shutil.rmtree(path)
    except OSError as error:
        print(f"ci-cache: warning: could not remove {path}: {error}", file=sys.stderr)


COMMANDS = {
    "passed-check": (passed_check, "set output hit=true when this tree passed under KEY"),
    "passed-record": (passed_record, "record that this tree passed under KEY"),
    "godot-restore": (godot_restore, "pin assets, set output key=KEY-<assets hash>, restore its entry"),
    "godot-save": (godot_save, "save .godot and the .import files under KEY, the key restore set"),
}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ci-cache", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (_, help_text) in COMMANDS.items():
        sub.add_parser(name, help=help_text).add_argument("key", metavar="KEY")
    args = parser.parse_args(argv)
    COMMANDS[args.command][0](args.key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
