"""Behavior tests for binaries.py. Run from this directory: python3 -m unittest test_binaries"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import platform
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import binaries

TARGET = binaries.TARGETS.get((platform.system(), platform.machine()), "x86_64-unknown-linux-gnu")


def archive(directory: Path, name: str, payload: bytes) -> Path:
    path = directory / f"{name}-{TARGET}.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return path


class Binaries(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.releases = Path(tempfile.mkdtemp())
        self.backup = self.home / "backup"
        for name, value in {"HOME": self.home, "BIN": self.home / ".local/bin",
                            "STORE": self.home / ".local/share/fleet/bin"}.items():
            patcher = mock.patch.object(binaries, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for patcher in (mock.patch.object(binaries, "asset_url", lambda repo, tag, asset: (self.releases / tag / asset).as_uri()),
                        mock.patch.object(binaries.platform, "system", lambda: {"aarch64-apple-darwin": "Darwin"}.get(TARGET, "Linux")),
                        mock.patch.object(binaries.platform, "machine", lambda: {"aarch64-apple-darwin": "arm64"}.get(TARGET, "x86_64"))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def release(self, tag: str, payload: bytes, sha256: str | None = None) -> Path:
        directory = self.releases / tag
        directory.mkdir(parents=True, exist_ok=True)
        path = archive(directory, "tool", payload)
        manifest = self.home / "binaries.json"
        digest = sha256 or hashlib.sha256(path.read_bytes()).hexdigest()
        manifest.write_text(json.dumps({"binaries": {"tool": {"repo": "o/r", "tag": tag, "sha256": {TARGET: digest}}}}))
        return manifest

    def sync(self, manifest: Path, apply: bool = True) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            binaries.main([str(manifest), str(self.backup), *(["--apply"] if apply else [])])
        return out.getvalue()

    def installed(self) -> bytes:
        return (self.home / ".local/bin/tool").read_bytes()

    def test_installs_links_and_then_has_nothing_to_do(self):
        manifest = self.release("v1", b"one")
        self.assertIn("binary     tool v1", self.sync(manifest))
        self.assertEqual(self.installed(), b"one")
        self.assertTrue((self.home / ".local/bin/tool").is_symlink())
        self.assertEqual(self.sync(manifest), "")

    def test_a_new_tag_swaps_the_binary(self):
        self.sync(self.release("v1", b"one"))
        self.assertIn("binary     tool v2", self.sync(self.release("v2", b"two")))
        self.assertEqual(self.installed(), b"two")

    def test_a_dry_run_changes_nothing(self):
        self.assertIn("binary     tool v1", self.sync(self.release("v1", b"one"), apply=False))
        self.assertFalse((self.home / ".local/bin/tool").exists())

    def test_a_checksum_mismatch_installs_nothing(self):
        with self.assertRaises(SystemExit) as raised:
            self.sync(self.release("v1", b"one", sha256="0" * 64))
        self.assertIn("does not match binaries.json", str(raised.exception))
        self.assertFalse((self.home / ".local/bin/tool").exists())
        self.assertFalse((self.home / ".local/share/fleet/bin/tool/v1/tool").exists())

    def test_a_foreign_binary_moves_to_the_backup(self):
        foreign = self.home / ".local/bin/tool"
        foreign.parent.mkdir(parents=True)
        foreign.write_bytes(b"cargo")
        self.assertIn("replace    ~/.local/bin/tool", self.sync(self.release("v1", b"one")))
        self.assertEqual(self.installed(), b"one")
        self.assertEqual((self.backup / ".local/bin/tool").read_bytes(), b"cargo")


if __name__ == "__main__":
    unittest.main()
