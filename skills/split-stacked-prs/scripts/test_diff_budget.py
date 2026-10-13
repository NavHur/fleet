"""Exercise the budget CLI against real Git trees without creating commits."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("diff_budget.py")


class DiffBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "--quiet")
        self.base = self.tree({})
        self.paths = set()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True).strip()

    def tree(self, files):
        for path in getattr(self, "paths", set()):
            (self.root / path).unlink()
        for path, content in files.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        self.paths = set(files)
        self.git("add", "--all")
        return self.git("write-tree")

    def run_budget(self, files, *options, expected=0):
        head = self.tree(files)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), self.base, head, "--json", *options],
            cwd=self.root, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, expected, result.stderr or result.stdout)
        return json.loads(result.stdout)

    @staticmethod
    def lines(count, prefix="line"):
        return "".join(f"{prefix} {index}\n" for index in range(count))

    def test_test_heavy_change_passes_weighted_budget(self):
        report = self.run_budget({
            "src/app.ts": self.lines(700),
            "src/app.test.ts": self.lines(900),
        })
        self.assertEqual(report["weighted_size"], 700)
        self.assertEqual(report["raw_churn"], 1600)
        self.assertEqual(report["test_churn"], 900)

    def test_tests_still_exceed_raw_ceiling(self):
        report = self.run_budget({
            "src/app.ts": self.lines(700),
            "src/app.spec.tsx": self.lines(1500),
        }, expected=2)
        self.assertEqual(report["weighted_size"], 700)
        self.assertEqual(report["raw_churn"], 2200)

    def test_exact_ceilings_pass(self):
        report = self.run_budget({
            "app.ts": self.lines(1000), "app.test.ts": self.lines(1000),
        })
        self.assertEqual(report["weighted_size"], 1000)
        self.assertEqual(report["raw_churn"], 2000)

    def test_weighted_ceiling_fails_independently(self):
        self.run_budget({"app.ts": self.lines(1001)}, expected=2)

    def test_test_only_change_has_raw_limit(self):
        report = self.run_budget({"app.test.ts": self.lines(2001)}, expected=2)
        self.assertEqual(report["weighted_size"], 0)

    def test_supported_test_names_across_languages(self):
        files = {path: self.lines(100) for path in (
            "app.test.ts", "view.spec.tsx", "test_domain.py", "domain_test.py",
            "domain_test.go", "app.test.mjs", "app.spec.cts",
        )}
        report = self.run_budget(files)
        self.assertEqual(report["weighted_size"], 0)
        self.assertEqual(report["raw_churn"], 700)
        self.assertEqual(report["test_churn"], 700)

    def test_helpers_fixtures_and_setup_count_in_both(self):
        files = {path: self.lines(300) for path in (
            "tests/helpers.ts", "tests/setup.ts", "tests/fixtures.ts", "vitest.config.ts",
        )}
        report = self.run_budget(files, expected=2)
        self.assertEqual(report["weighted_size"], 1200)
        self.assertEqual(report["test_churn"], 0)

    def test_verified_accessibility_test_glob(self):
        report = self.run_budget({
            "scripts/a11y-pages.ts": self.lines(1100),
            "scripts/helpers.ts": self.lines(100),
        }, "--test", "scripts/a11y-pages.ts")
        self.assertEqual(report["weighted_size"], 100)
        self.assertEqual(report["raw_churn"], 1200)

    def test_generated_data_and_lockfiles_excluded_from_both(self):
        report = self.run_budget({
            "app.ts": self.lines(10), "pnpm-lock.yaml": self.lines(3000),
            "data/records.json": self.lines(3000),
        }, "--generated", "data/*.json")
        self.assertEqual(report["weighted_size"], 10)
        self.assertEqual(report["raw_churn"], 10)
        self.assertEqual(report["excluded_lines"], 6000)

    def test_fractional_deletion_weight_is_not_truncated(self):
        self.base = self.tree({"old.ts": self.lines(1)})
        report = self.run_budget({"new.ts": self.lines(1000, "different")}, expected=2)
        self.assertEqual(report["weighted_size"], 1000.25)

    def test_rename_to_test_does_not_hide_production_changes(self):
        original = self.lines(1100)
        self.base = self.tree({"app.ts": original})
        report = self.run_budget({"app.test.ts": original + self.lines(10, "added")})
        self.assertEqual(report["weighted_size"], 10)
        self.assertEqual(report["test_churn"], 0)
        self.assertEqual(report["status"], "target")

    def test_pure_deletion_retirement_exempt(self):
        self.base = self.tree({"old.ts": self.lines(5000)})
        report = self.run_budget({})
        self.assertEqual(report["raw_churn"], 5000)
        self.assertEqual(report["status"], "exempt-retirement")

    def test_pure_rename_retirement_exempt(self):
        original = self.lines(5000)
        self.base = self.tree({"old.ts": original})
        report = self.run_budget({"renamed.ts": original})
        self.assertEqual(report["status"], "exempt-retirement")

    def test_mixed_retirement_and_addition_is_not_exempt(self):
        self.base = self.tree({"old.ts": self.lines(5000)})
        report = self.run_budget({"new.ts": "new content\n"}, expected=2)
        self.assertEqual(report["status"], "cap-violation")

    def commit(self, files, *parents):
        tree = self.tree(files)
        flags = [flag for parent in parents for flag in ("-p", parent)]
        return self.git("commit-tree", tree, *flags, "-m", "commit")

    def test_commits_measure_from_their_merge_base(self):
        """A branch name works as BASE: work landed on it after the fork doesn't count."""
        fork = self.commit({"app.ts": "a\n"})
        head = self.commit({"app.ts": "a\n", "feature.ts": self.lines(10)}, fork)
        self.base = self.commit({"app.ts": "a\n", "landed.ts": self.lines(1500)}, fork)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), self.base, head, "--json"],
            cwd=self.root, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["raw_churn"], 10)


if __name__ == "__main__":
    unittest.main()
