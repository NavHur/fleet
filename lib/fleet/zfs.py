"""Make a machine's ZFS settings match hosts/<machine>/zfs.

    python3 zfs.py ZFS_DIR [--apply]

ZFS_DIR/properties.json maps each dataset to the properties set on it locally
(`zfs get -s local`). A property with another value is set; one set locally
but missing from the manifest is reported, since only a person can say whether
it belongs. Every other file under ZFS_DIR mirrors a system path
(ZFS_DIR/etc/sanoid/sanoid.conf is /etc/sanoid/sanoid.conf) and is copied
there as root. A changed modprobe.d file also rebuilds the initramfs, which
loads ZFS before the root pool mounts, and writes its `options zfs` values to
the running module.

Changes run through `sudo -n`, so --apply fails rather than prompts on a
machine without passwordless sudo. Prints one plan line per change, in
bin/sync's format. A machine without ZFS_DIR has nothing to do.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

MANIFEST = "properties.json"
SYSTEM_ROOT = Path("/")
MODULE_PARAMETERS = Path("/sys/module/zfs/parameters")


def say(verb: str, text: str) -> None:
    print(f"  {verb:<10} {text}", flush=True)


def run(command: list[str]) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def sudo(*command: str) -> None:
    run(["sudo", "-n", *command])


def local_properties(pools: set[str]) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    output = run(["zfs", "get", "-H", "-s", "local", "-o", "name,property,value", "all", "-r", *sorted(pools)])
    for line in output.splitlines():
        name, prop, value = line.split("\t")
        if "@" not in name:
            found.setdefault(name, {})[prop] = value
    return found


def sync_properties(wanted: dict[str, dict[str, str]], apply: bool) -> None:
    actual = local_properties({name.split("/")[0] for name in wanted})
    for name, props in wanted.items():
        for prop, value in props.items():
            current = actual.get(name, {}).get(prop)
            if current == value:
                continue
            say("zfs-set", f"{name} {prop}={value} (now {current or 'inherited'})")
            if apply:
                sudo("zfs", "set", f"{prop}={value}", name)
    for name, props in actual.items():
        for prop, value in props.items():
            if prop not in wanted.get(name, {}):
                say("warning", f"{name} {prop}={value} is set locally but not in {MANIFEST}")


def module_options(conf: str) -> dict[str, str]:
    options: dict[str, str] = {}
    for line in conf.splitlines():
        words = line.split()
        if words[:2] == ["options", "zfs"]:
            options.update(word.split("=", 1) for word in words[2:])
    return options


def sync_files(zfs_dir: Path, apply: bool) -> None:
    changed = []
    for source in sorted(p for p in zfs_dir.rglob("*") if p.is_file() and p.name != MANIFEST):
        relative = source.relative_to(zfs_dir)
        target = SYSTEM_ROOT / relative
        if target.is_file() and target.read_bytes() == source.read_bytes():
            continue
        say("system", f"/{relative}")
        changed.append(relative)
        if apply:
            sudo("install", "-D", "-m", "0644", str(source), str(target))
    modprobe = [r for r in changed if r.parts[:2] == ("etc", "modprobe.d")]
    if not modprobe:
        return
    say("initramfs", "rebuild (modprobe.d changed)")
    if not apply:
        return
    for relative in modprobe:
        for name, value in module_options((zfs_dir / relative).read_text()).items():
            sudo("sh", "-c", 'echo "$1" > "$2"', "-", value, str(MODULE_PARAMETERS / name))
    sudo("update-initramfs", "-u")


def main(argv: list[str]) -> int:
    zfs_dir, apply = Path(argv[0]), "--apply" in argv
    if not zfs_dir.is_dir():
        return 0
    sync_properties(json.loads((zfs_dir / MANIFEST).read_text()), apply)
    sync_files(zfs_dir, apply)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
