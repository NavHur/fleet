"""Which suites a change runs, and that each suite's watched paths still match what it imports."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from changed_tests import ROOT, SUITES, Suite, changed_since, plan_for  # noqa: E402

# Imports every test module of the suite run from the current directory, as unittest does,
# then prints the files Python loaded.
LOADED_FILES = """
import importlib, json, sys
for name in sys.argv[1:]:
    importlib.import_module(name)
print(json.dumps([getattr(module, "__file__", None) for module in list(sys.modules.values())]))
"""


def directories(*changed):
    return [suite.directory for suite in plan_for(list(changed)).suites]


def loaded_repo_files(suite: Suite) -> list[str]:
    command = [sys.executable, "-c", LOADED_FILES, *suite.modules()]
    result = subprocess.run(command, cwd=ROOT / suite.directory, capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(f"importing {suite.directory}'s tests failed:\n{result.stderr}")
    tracked = set(subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split())
    files = {Path(file).resolve() for file in json.loads(result.stdout) if file}
    return sorted(str(file.relative_to(ROOT)) for file in files if file.is_relative_to(ROOT)
                  and str(file.relative_to(ROOT)) in tracked)


class PlanTest(unittest.TestCase):
    def test_no_changes_run_nothing(self):
        plan = plan_for([])
        self.assertEqual((plan.suites, plan.rust), ((), False))

    def test_without_a_base_everything_runs(self):
        plan = plan_for(None)
        self.assertEqual((plan.suites, plan.rust), (SUITES, True))

    def test_a_doc_runs_nothing(self):
        self.assertEqual(directories("README.md", "docs/adr/0001.md", "skills/grilling/SKILL.md"), [])

    def test_a_suites_own_file_runs_it_and_this_suite(self):
        self.assertEqual(directories("lib/transcripts/transcripts.py"), ["lib/transcripts", "lib/changed-tests"])

    def test_host_check_runs_every_suite_that_imports_it(self):
        self.assertEqual(directories("lib/host-check/guard.py"), [
            "lib/host-check", "bin", "lib/file-size", "skills/pre-commit/scripts",
            "hosts/workbox/claude-hooks", "lib/changed-tests"])

    def test_the_stack_scripts_run_the_review_loop_too(self):
        self.assertEqual(directories("skills/stack/scripts/diff_budget.py"),
                         ["skills/review-loop/scripts", "skills/stack/scripts", "lib/changed-tests"])

    def test_rust_runs_the_rust_checks_and_the_analyzer_tests(self):
        plan = plan_for(["crates/pbp-complexity/src/main.rs"])
        self.assertTrue(plan.rust)
        self.assertEqual([suite.directory for suite in plan.suites],
                         ["skills/pedro-best-practices/tests", "lib/changed-tests"])

    def test_python_alone_skips_the_rust_checks(self):
        self.assertFalse(plan_for(["lib/fleet/zfs.py"]).rust)

    def test_the_runner_or_its_workflow_runs_everything(self):
        for path in ("bin/test", "Makefile", ".github/workflows/test.yml", "lib/changed-tests/changed_tests.py"):
            with self.subTest(path):
                plan = plan_for([path])
                self.assertEqual((plan.suites, plan.rust), (SUITES, True))

    def test_a_directory_prefix_does_not_cover_a_sibling_with_a_longer_name(self):
        self.assertEqual(directories("binaries.json"), ["skills/pedro-best-practices/tests", "lib/changed-tests"])


class ChangedSinceTest(unittest.TestCase):
    def git(self, *args):
        identity = ["-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "-C", self.repo, *identity, *args], check=True, capture_output=True)

    def write(self, name):
        (Path(self.repo) / name).write_text(name)

    def test_commits_edits_and_untracked_files_since_the_fork_count_but_the_bases_own_do_not(self):
        with tempfile.TemporaryDirectory() as self.repo:
            self.git("init", "-q", "-b", "main")
            self.git("commit", "-q", "--allow-empty", "-m", "fork point")
            self.git("checkout", "-q", "-b", "work")
            self.write("committed")
            self.git("add", "committed")
            self.git("commit", "-q", "-m", "work")
            self.git("checkout", "-q", "main")
            self.write("on-main")
            self.git("add", "on-main")
            self.git("commit", "-q", "-m", "main moves on")
            self.git("checkout", "-q", "work")
            self.write("staged")
            self.git("add", "staged")
            self.write("untracked")
            with mock.patch("changed_tests.ROOT", Path(self.repo)):
                self.assertEqual(sorted(changed_since("main")), ["committed", "staged", "untracked"])


class SuitesMatchTheRepoTest(unittest.TestCase):
    def test_every_test_module_belongs_to_a_suite(self):
        tests = subprocess.run(["git", "ls-files", "*test_*.py"], cwd=ROOT, capture_output=True, text=True)
        homes = {str(Path(path).parent) for path in tests.stdout.split() if "/fixtures/" not in path}
        self.assertEqual(homes - {suite.directory for suite in SUITES}, set())

    def test_each_suite_imports_only_what_it_watches(self):
        for suite in SUITES:
            with self.subTest(suite.directory):
                outside = [path for path in loaded_repo_files(suite) if not suite.covers(path)]
                self.assertEqual(outside, [], f"add these to {suite.directory}'s watches in changed_tests.py")


if __name__ == "__main__":
    unittest.main()
