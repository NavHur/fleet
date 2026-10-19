"""The revision being measured: the files and lines it changes, their contents, and a temporary copy to run tools on."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

HOST_CHECK = os.path.expanduser("~/.local/bin/host-check")
LANGUAGES = {
    "js": {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts", ".svelte", ".vue", ".astro"},
    "python": {".py"},
    "gdscript": {".gd"},
    "php": {".php"},
}


def language_of(path: str) -> str | None:
    suffix = PurePosixPath(path).suffix
    return next((name for name, suffixes in LANGUAGES.items() if suffix in suffixes), None)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    if result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {result.stderr.decode().strip()}")
    return result.stdout.decode()


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
    if os.environ.get("HOST_CHECK_ACTIVE") != "1" and os.access(HOST_CHECK, os.X_OK):
        command = [HOST_CHECK, *command]
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)


def changed_files(root: Path, base: str, head: str | None) -> list[str]:
    files = git(root, "diff", "--name-only", "--diff-filter=d", "-z", base, *([head] if head else [])).split("\0")
    if head is None:
        files += git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    return sorted({f for f in files if f and language_of(f) and "node_modules/" not in f})


def changed_lines(root: Path, base: str, head: str | None, files: list[str]) -> dict[str, set[int] | None]:
    """Map each file to its added or modified lines; None means the whole file."""
    lines: dict[str, set[int] | None] = {}
    current = None
    diff = git(root, "diff", "-U0", "--no-color", "--no-ext-diff", base, *([head] if head else []), "--", *files)
    for row in diff.splitlines():
        if row.startswith("+++ "):
            current = row[6:] if row.startswith("+++ b/") else None
            if current:
                lines.setdefault(current, set())
        elif row.startswith("@@") and current:
            match = re.match(r"@@ -\S+ \+(\d+)(?:,(\d+))? @@", row)
            start, count = int(match.group(1)), int(match.group(2) or 1)
            target = lines[current]
            if target is not None:
                target.update(range(start, start + count) if count else (start, start + 1))
    for path in files:
        lines.setdefault(path, None)  # untracked: every line is new
    return lines


def materialize(root: Path, head: str | None, paths: list[str], tree: Path) -> None:
    if not paths:
        return
    if head:
        archive = subprocess.run(["git", "-C", str(root), "archive", "--format=tar", head, "--", *paths],
                                 capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(tree)], input=archive.stdout, check=True)
        return
    for path in paths:
        source, target = root / path, tree / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("node_modules"))
        elif source.exists():
            shutil.copy2(source, target)


def read_file(root: Path, head: str | None, path: str) -> str | None:
    if head:
        result = subprocess.run(["git", "-C", str(root), "show", f"{head}:{path}"], capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else None
    target = root / path
    return target.read_text(errors="replace") if target.exists() else None
