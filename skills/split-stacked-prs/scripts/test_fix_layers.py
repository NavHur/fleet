"""Drive fix_layers.sh over a stack built by build_layers.sh."""

import os
from pathlib import Path
import subprocess
import unittest

from stack_fixture import IDENTITY, StackRepo

HERE = Path(__file__).parent


class FixLayersTests(unittest.TestCase):
    def setUp(self):
        self.repo = StackRepo(self)
        self.repo.branch("source", "main", {"a.ts": "a\n", "b.ts": "b\n"})
        self.repo.manifest("01-a", "# base: main\na.ts\n")
        self.repo.manifest("02-b", "b.ts\n")
        self.run_script("build_layers.sh", "--base", "main", "--source", "source")
        self.messages = self.repo.manifests.parent / "msgs"
        self.messages.mkdir()
        (self.messages / "default").write_text("fix: carry the fix\n")

    def run_script(self, script, *args):
        result = subprocess.run(
            ["bash", str(HERE / script), *args, "--manifests", str(self.repo.manifests), "--prefix", "s-"],
            cwd=self.repo.root, text=True, capture_output=True, env={**os.environ, **IDENTITY},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_a_fix_lands_in_the_layer_that_owns_the_file_and_rides_up(self):
        fixed = self.repo.branch("fixed", "s-02-b", {"a.ts": "a fixed\n"})
        result = self.run_script("fix_layers.sh", "--source", fixed, "--fix-msgs", str(self.messages))
        self.assertIn("01-a: fix", result.stdout)
        self.assertIn("02-b: no fix", result.stdout)
        self.assertEqual(self.repo.git("show", "s-01-a:a.ts"), "a fixed")
        self.assertEqual(self.repo.git("show", "s-02-b:a.ts"), "a fixed")


if __name__ == "__main__":
    unittest.main()
