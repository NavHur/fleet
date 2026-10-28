"""Drive check_manifests.py over a source branch and a manifest directory."""

import os
from pathlib import Path
import subprocess
import sys
import unittest

from stack_fixture import StackRepo

HERE = Path(__file__).parent


class CheckManifestsTests(unittest.TestCase):
    def setUp(self):
        self.repo = StackRepo(self)
        self.repo.branch("source", "main", {"a.ts": "a\n", "b.ts": "b\n", "app.ts": None})

    def check(self, *flags):
        return subprocess.run(
            [sys.executable, str(HERE / "check_manifests.py"), "main", "source", str(self.repo.manifests), *flags],
            text=True, capture_output=True,
        )

    def hook(self, layer):
        hook = self.repo.manifests / "hooks" / layer
        hook.parent.mkdir(exist_ok=True)
        hook.write_text("#!/bin/sh\n")
        os.chmod(hook, 0o755)

    def test_every_changed_path_in_one_final_layer_passes(self):
        self.repo.manifest("01-a", "# commit: feat: a\na.ts\napp.ts\n")
        self.repo.manifest("02-b", "b.ts\n")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("2 layers, 3 changed files, 3 final, 0 staged in 0 layers", result.stdout)

    def test_missing_duplicated_and_unchanged_paths_fail(self):
        self.repo.manifest("01-a", "a.ts\nnope.ts\n")
        self.repo.manifest("02-b", "a.ts\nb.ts\n")
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("duplicated: a.ts in 01-a, 02-b (stage the earlier ones as ~a.ts)", result.stdout)
        self.assertIn("missing: app.ts", result.stdout)
        self.assertIn("not changed: nope.ts", result.stdout)

    def test_a_path_staged_below_its_final_layer_passes(self):
        self.repo.manifest("01-a", "~b.ts\na.ts\napp.ts\n")
        self.repo.manifest("02-b", "b.ts\n")
        self.hook("01-a")
        result = self.check("--require-hooks")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("3 final, 1 staged in 1 layers", result.stdout)

    def test_a_path_staged_at_or_above_its_final_layer_fails(self):
        self.repo.manifest("01-a", "a.ts\napp.ts\nb.ts\n")
        self.repo.manifest("02-b", "~b.ts\n")
        self.hook("02-b")
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("staged at or after its final layer: b.ts in 02-b", result.stdout)

    def test_a_staged_layer_without_a_hook_warns_unless_hooks_are_required(self):
        self.repo.manifest("01-a", "~b.ts\na.ts\napp.ts\n")
        self.repo.manifest("02-b", "b.ts\n")
        warned = self.check()
        self.assertEqual(warned.returncode, 0, warned.stdout)
        self.assertIn("warning: no executable hooks/01-a", warned.stdout)
        refused = self.check("--require-hooks")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("no executable hooks/01-a for its ~paths", refused.stdout)


if __name__ == "__main__":
    unittest.main()
