"""Behavior tests for zfs.py. Run from this directory: python3 -m unittest test_zfs"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import zfs


class FakeHost:
    """Answers `zfs get` from a property table and records every other command."""

    def __init__(self, local: dict[str, dict[str, str]]):
        self.local = local
        self.commands: list[list[str]] = []

    def run(self, command: list[str]) -> str:
        if command[0] == "zfs":
            return "".join(f"{name}\t{prop}\t{value}\n"
                           for name, props in self.local.items() for prop, value in props.items())
        self.commands.append(command)
        return ""


class Zfs(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()) / "zfs"
        self.root = Path(tempfile.mkdtemp())
        self.dir.mkdir()
        patcher = mock.patch.object(zfs, "SYSTEM_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def manifest(self, props: dict[str, dict[str, str]]) -> None:
        (self.dir / "properties.json").write_text(json.dumps(props))

    def file(self, base: Path, relative: str, text: str) -> None:
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def sync(self, host: FakeHost, apply: bool = True) -> str:
        out = io.StringIO()
        with mock.patch.object(zfs, "run", host.run), contextlib.redirect_stdout(out):
            zfs.main([str(self.dir), *(["--apply"] if apply else [])])
        return out.getvalue()

    def test_matching_settings_have_nothing_to_do(self):
        self.manifest({"rpool": {"compression": "lz4"}})
        self.file(self.dir, "etc/sanoid/sanoid.conf", "a\n")
        self.file(self.root, "etc/sanoid/sanoid.conf", "a\n")
        host = FakeHost({"rpool": {"compression": "lz4"}})
        self.assertEqual(self.sync(host), "")
        self.assertEqual(host.commands, [])

    def test_a_different_property_is_set_through_sudo(self):
        self.manifest({"rpool/home/pedro": {"sync": "disabled"}})
        host = FakeHost({})
        self.assertIn("zfs-set    rpool/home/pedro sync=disabled (now inherited)", self.sync(host))
        self.assertEqual(host.commands, [["sudo", "-n", "zfs", "set", "sync=disabled", "rpool/home/pedro"]])

    def test_a_dry_run_changes_nothing(self):
        self.manifest({"rpool": {"compression": "lz4"}})
        self.file(self.dir, "etc/sanoid/sanoid.conf", "new\n")
        host = FakeHost({"rpool": {"compression": "zstd"}})
        plan = self.sync(host, apply=False)
        self.assertIn("rpool compression=lz4 (now zstd)", plan)
        self.assertIn("system     /etc/sanoid/sanoid.conf", plan)
        self.assertEqual(host.commands, [])

    def test_a_local_property_missing_from_the_manifest_is_reported_not_changed(self):
        self.manifest({"rpool": {}})
        host = FakeHost({"rpool": {"recordsize": "1M"}})
        self.assertIn("warning    rpool recordsize=1M is set locally but not in properties.json", self.sync(host))
        self.assertEqual(host.commands, [])

    def test_a_changed_file_is_installed_as_root(self):
        self.manifest({})
        self.file(self.dir, "etc/sanoid/sanoid.conf", "new\n")
        self.file(self.root, "etc/sanoid/sanoid.conf", "old\n")
        host = FakeHost({})
        self.sync(host)
        self.assertEqual(host.commands, [["sudo", "-n", "install", "-D", "-m", "0644",
                                          str(self.dir / "etc/sanoid/sanoid.conf"),
                                          str(self.root / "etc/sanoid/sanoid.conf")]])

    def test_a_modprobe_change_reaches_the_running_module_and_the_initramfs(self):
        self.manifest({})
        self.file(self.dir, "etc/modprobe.d/zfs.conf", "# note\noptions zfs zfs_arc_max=6442450944\n")
        host = FakeHost({})
        self.assertIn("initramfs  rebuild", self.sync(host))
        self.assertEqual([c[2] for c in host.commands], ["install", "sh", "update-initramfs"])
        self.assertEqual(host.commands[1][-2:], ["6442450944", str(zfs.MODULE_PARAMETERS / "zfs_arc_max")])

    def test_a_machine_without_a_zfs_folder_has_nothing_to_do(self):
        self.dir.rmdir()
        host = FakeHost({"rpool": {"compression": "zstd"}})
        self.assertEqual(self.sync(host), "")


if __name__ == "__main__":
    unittest.main()
