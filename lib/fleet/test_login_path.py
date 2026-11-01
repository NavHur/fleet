"""Behavior tests for config/login-path.sh. Run from this directory: python3 -m unittest test_login_path"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

LOGIN_PATH = Path(__file__).resolve().parents[2] / "config" / "login-path.sh"
SYSTEM_PATH = "/usr/bin:/bin"


def executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


class LoginPath(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home)
        # A stand-in nvm whose nvm.sh puts its default node on PATH, as `nvm use default` does.
        self.nvm_bin = self.home / ".nvm" / "versions" / "node" / "v24.0.0" / "bin"
        executable(self.nvm_bin / "npx", "echo nvm-npx")
        (self.home / ".nvm" / "nvm.sh").write_text(f'PATH="{self.nvm_bin}:$PATH"\n')

    def npx_after_login(self, shell: str, path: str = SYSTEM_PATH) -> str:
        """Which npx a login shell resolves once its profile sources login-path.sh."""
        result = subprocess.run(
            [shell, "-c", f'. "{LOGIN_PATH}"; command -v npx || echo none'],
            env={"HOME": str(self.home), "PATH": path},
            capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def test_a_login_bash_without_npx_gets_nvms_default_node(self):
        self.assertEqual(self.npx_after_login("bash"), str(self.nvm_bin / "npx"))

    def test_an_npx_already_on_path_is_kept(self):
        system_npx = self.home / "system" / "npx"
        executable(system_npx, "echo system-npx")
        found = self.npx_after_login("bash", f"{system_npx.parent}:{SYSTEM_PATH}")
        self.assertEqual(found, str(system_npx))

    @unittest.skipUnless(shutil.which("dash"), "dash is not installed")
    def test_dash_reading_the_profile_leaves_nvm_alone(self):
        self.assertEqual(self.npx_after_login("dash"), "none")


if __name__ == "__main__":
    unittest.main()
