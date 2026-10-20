"""Exercise the budget CLI against real Git trees without creating commits."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("diff_budget.py")
LINE_BYTES = 48  # 1000 lines fill the pull request's weighted ceiling
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class DiffBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "--quiet")
        self.base = self.tree({})
        self.paths = set()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True, env={**os.environ, **IDENTITY}).strip()

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
        """`count` distinct lines of LINE_BYTES bytes each, newline included."""
        return "".join(f"{prefix} {index}".ljust(LINE_BYTES - 1) + "\n" for index in range(count))

    def test_test_heavy_change_passes_weighted_budget(self):
        report = self.run_budget({
            "src/app.ts": self.lines(700),
            "src/app.test.ts": self.lines(900),
        })
        self.assertEqual(report["weighted_size"], 700 * LINE_BYTES)
        self.assertEqual(report["raw_churn"], 1600 * LINE_BYTES)
        self.assertEqual(report["test_churn"], 900 * LINE_BYTES)

    def test_tests_still_exceed_raw_ceiling(self):
        report = self.run_budget({
            "src/app.ts": self.lines(700),
            "src/app.spec.tsx": self.lines(1500),
        }, expected=2)
        self.assertEqual(report["weighted_size"], 700 * LINE_BYTES)
        self.assertEqual(report["raw_churn"], 2200 * LINE_BYTES)

    def test_exact_ceilings_pass(self):
        report = self.run_budget({
            "app.ts": self.lines(1000), "app.test.ts": self.lines(1000),
        })
        self.assertEqual(report["weighted_size"], 48_000)
        self.assertEqual(report["raw_churn"], 96_000)

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
        self.assertEqual(report["raw_churn"], 700 * LINE_BYTES)
        self.assertEqual(report["test_churn"], 700 * LINE_BYTES)

    def test_helpers_fixtures_and_setup_count_in_both(self):
        files = {path: self.lines(300) for path in (
            "tests/helpers.ts", "tests/setup.ts", "tests/fixtures.ts", "vitest.config.ts",
        )}
        report = self.run_budget(files, expected=2)
        self.assertEqual(report["weighted_size"], 1200 * LINE_BYTES)
        self.assertEqual(report["test_churn"], 0)

    def test_verified_accessibility_test_glob(self):
        report = self.run_budget({
            "scripts/a11y-pages.ts": self.lines(1100),
            "scripts/helpers.ts": self.lines(100),
        }, "--test", "scripts/a11y-pages.ts")
        self.assertEqual(report["weighted_size"], 100 * LINE_BYTES)
        self.assertEqual(report["raw_churn"], 1200 * LINE_BYTES)

    def test_generated_data_and_lockfiles_excluded_from_both(self):
        report = self.run_budget({
            "app.ts": self.lines(10), "pnpm-lock.yaml": self.lines(3000),
            "data/records.json": self.lines(3000),
        }, "--generated", "data/*.json")
        self.assertEqual(report["weighted_size"], 10 * LINE_BYTES)
        self.assertEqual(report["raw_churn"], 10 * LINE_BYTES)
        self.assertEqual(report["excluded_bytes"], 6000 * LINE_BYTES)

    def test_fractional_deletion_weight_is_not_truncated(self):
        self.base = self.tree({"old.ts": self.lines(1)})
        report = self.run_budget({"new.ts": self.lines(1000, "different")}, expected=2)
        self.assertEqual(report["weighted_size"], 48_000 + LINE_BYTES / 4)

    def test_rename_to_test_does_not_hide_production_changes(self):
        original = self.lines(1100)
        self.base = self.tree({"app.ts": original})
        report = self.run_budget({"app.test.ts": original + self.lines(10, "added")})
        self.assertEqual(report["weighted_size"], 10 * LINE_BYTES)
        self.assertEqual(report["test_churn"], 0)
        self.assertEqual(report["status"], "within-cap")

    def test_pure_deletion_retirement_exempt(self):
        self.base = self.tree({"old.ts": self.lines(5000)})
        report = self.run_budget({})
        self.assertEqual(report["raw_churn"], 5000 * LINE_BYTES)
        self.assertEqual(report["status"], "exempt-retirement")

    def test_pure_rename_retirement_exempt(self):
        original = self.lines(5000)
        self.base = self.tree({"old.ts": original})
        report = self.run_budget({"renamed.ts": original})
        self.assertEqual(report["status"], "exempt-retirement")

    def test_long_lines_count_by_their_bytes(self):
        """One minified line costs what it takes to read, not one line."""
        report = self.run_budget({"bundle.js": "x" * 49_999 + "\n"}, expected=2)
        self.assertEqual(report["weighted_size"], 50_000)
        self.assertEqual(report["files"][0]["bytes"], 50_000)

    def test_rewrite_counts_both_sides(self):
        self.base = self.tree({"app.ts": self.lines(100, "old")})
        report = self.run_budget({"app.ts": self.lines(100, "new")})
        self.assertEqual(report["weighted_added_bytes"], 100 * LINE_BYTES)
        self.assertEqual(report["weighted_deleted_bytes"], 100 * LINE_BYTES)
        self.assertEqual(report["weighted_size"], 125 * LINE_BYTES)

    def test_content_lines_that_look_like_file_headers_are_counted(self):
        """`--- x` and `+++ x` inside a hunk are a deleted `-- x` and an added `++ x`."""
        self.base = self.tree({"app.ts": "-- x\n"})
        report = self.run_budget({"app.ts": "++ y\n"})
        self.assertEqual(report["weighted_added_bytes"], len("+++ y"))
        self.assertEqual(report["weighted_deleted_bytes"], len("--- x"))

    def test_type_change_is_one_file_with_both_sides_counted(self):
        """Git patches a file turned symlink as two sections under one header."""
        self.base = self.tree({"app.ts": self.lines(2)})
        (self.root / "app.ts").unlink()
        os.symlink("target.ts", self.root / "app.ts")
        self.git("add", "--all")
        head = self.git("write-tree")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), self.base, head, "--json"],
            cwd=self.root, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(len(report["files"]), 1)
        self.assertEqual(report["weighted_added_bytes"], len("+target.ts"))
        self.assertEqual(report["weighted_deleted_bytes"], 2 * LINE_BYTES)

    def test_binary_files_are_counted_but_not_measured(self):
        report = self.run_budget({"app.ts": self.lines(1), "logo.bin": "\0" * 100})
        self.assertEqual(report["included_binary_files"], 1)
        self.assertEqual(report["raw_churn"], LINE_BYTES)

    def test_mixed_retirement_and_addition_is_not_exempt(self):
        self.base = self.tree({"old.ts": self.lines(5000)})
        report = self.run_budget({"new.ts": "new content\n"}, expected=2)
        self.assertEqual(report["status"], "cap-violation")

    def commit(self, files, *parents, message="commit"):
        tree = self.tree(files)
        flags = [flag for parent in parents for flag in ("-p", parent)]
        return self.git("commit-tree", tree, *flags, "-m", message)

    def run_commits(self, base, head, *options, expected=0):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), base, head, "--per-commit", "--json", *options],
            cwd=self.root, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, expected, result.stderr or result.stdout)
        return {c["subject"]: c for c in json.loads(result.stdout)["commits"]}

    def test_each_commit_measures_against_its_parent(self):
        """Two 200-line steps pass the 250-line commit ceiling though the range totals 400."""
        fork = self.commit({"app.ts": "a\n"})
        first = self.commit({"app.ts": "a\n", "one.ts": self.lines(200)}, fork, message="one")
        head = self.commit(
            {"app.ts": "a\n", "one.ts": self.lines(200), "two.ts": self.lines(200)},
            first, message="two",
        )
        commits = self.run_commits(fork, head)
        self.assertEqual(list(commits), ["one", "two"])
        self.assertEqual(commits["two"]["weighted_size"], 200 * LINE_BYTES)
        self.assertEqual(commits["two"]["status"], "within-cap")

    def test_commit_ceilings_fail_independently(self):
        fork = self.commit({})
        weighted = self.commit({"app.ts": self.lines(251)}, fork, message="weighted")
        raw = self.commit(
            {"app.ts": self.lines(251), "app.test.ts": self.lines(501)}, weighted, message="raw",
        )
        commits = self.run_commits(fork, raw, expected=2)
        self.assertEqual(commits["weighted"]["status"], "cap-violation")
        self.assertEqual(commits["raw"]["weighted_size"], 0)
        self.assertEqual(commits["raw"]["status"], "cap-violation")

    def test_size_exception_trailer_exempts_a_commit(self):
        fork = self.commit({})
        message = "feat: add the parser\n\nSize-Exception: one cohesive generated grammar"
        head = self.commit({"parser.ts": self.lines(900)}, fork, message=message)
        commits = self.run_commits(fork, head)
        self.assertEqual(commits["feat: add the parser"]["status"], "exempt-trailer")
        self.assertEqual(
            commits["feat: add the parser"]["exception"], "one cohesive generated grammar",
        )

    def test_merge_commits_are_skipped(self):
        fork = self.commit({"app.ts": "a\n"})
        side = self.commit({"app.ts": "a\n", "side.ts": self.lines(10)}, fork, message="side")
        main = self.commit({"app.ts": "a\n", "big.ts": self.lines(900)}, fork, message="main")
        merge = self.commit(
            {"app.ts": "a\n", "side.ts": self.lines(10), "big.ts": self.lines(900)},
            side, main, message="merge",
        )
        commits = self.run_commits(side, merge, expected=2)
        self.assertEqual(list(commits), ["main"])

    def test_tree_base_measures_history_from_the_root(self):
        """The empty tree as BASE lists every commit; the root diffs against it."""
        root = self.commit({"app.ts": self.lines(10)}, message="root")
        commits = self.run_commits(self.base, root, "--cap", "100", expected=2)
        self.assertEqual(commits["root"]["weighted_size"], 10 * LINE_BYTES)

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
        self.assertEqual(json.loads(result.stdout)["raw_churn"], 10 * LINE_BYTES)


if __name__ == "__main__":
    unittest.main()
