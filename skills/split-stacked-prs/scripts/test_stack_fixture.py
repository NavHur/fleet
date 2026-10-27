"""The stack fixture stays out of the repository whose hook runs the tests."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from stack_fixture import StackRepo


class HookEnvironmentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.decoy = Path(temp.name) / "decoy"
        subprocess.run(["git", "init", "-q", str(self.decoy)], check=True)
        hook = {"GIT_DIR": str(self.decoy / ".git"), "GIT_INDEX_FILE": str(self.decoy / ".git" / "index")}
        patch = mock.patch.dict(os.environ, hook)
        patch.start()
        self.addCleanup(patch.stop)
        self.hook = hook

    def test_a_hook_s_repository_variables_reach_neither_the_fixture_nor_its_scripts(self):
        inner = unittest.TestCase()
        repo = StackRepo(inner)
        repo.branch("s-01-a", "main", {"a.ts": "a\n"})
        script = subprocess.run(["git", "rev-parse", "--show-toplevel"], text=True, capture_output=True, check=True)
        self.assertEqual(Path(script.stdout.strip()).resolve(), repo.root.resolve())
        inner.doCleanups()
        self.assertFalse((self.decoy / ".git" / "index").exists(), "the decoy's index was written")
        self.assertEqual({name: os.environ[name] for name in self.hook}, self.hook, "the variables come back")


if __name__ == "__main__":
    unittest.main()
