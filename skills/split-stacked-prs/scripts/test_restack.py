"""Drive restack.py against a real bare origin and clone."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("restack.py")
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class RestackTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="restack-test-")
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.env = dict(os.environ, HOME=str(self.home), **IDENTITY)
        self.env.pop("GIT_DIR", None)
        origin = self.home / "origin.git"
        self.run_git(None, "init", "--quiet", "--bare", "-b", "main", str(origin))
        self.repo = self.home / "repo"
        self.run_git(None, "clone", "--quiet", str(origin), str(self.repo))
        self.commit("main", {"app.txt": "one\ntwo\nthree\n"}, new=True)
        self.commit("l1", {"f1.txt": "layer one\n"}, new=True, start="main")
        self.commit("l2", {"f2.txt": "layer two\n"}, new=True, start="l1")
        self.commit("l3", {"f3.txt": "layer three\n"}, new=True, start="l2")

    def run_git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, text=True, check=True, capture_output=True).stdout.strip()

    def git(self, *args):
        return self.run_git(self.repo, *args)

    def commit(self, branch, files, new=False, start=None):
        self.git("checkout", "--quiet", *(["-B", branch, start] if new and start else ["-B", branch] if new else [branch]))
        for name, text in files.items():
            (self.repo / name).write_text(text)
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", f"{branch} change")
        self.git("push", "--quiet", "--force", "origin", branch)

    def restack(self, *args, expected=0):
        result = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.repo, env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout

    def state_dir(self, output):
        return next(line.split(": ", 1)[1] for line in output.splitlines() if line.startswith("state: "))

    def remote_file(self, branch, name):
        self.git("fetch", "--quiet", "origin")
        return self.git("show", f"origin/{branch}:{name}")

    def assert_chain(self, *branches):
        self.git("fetch", "--quiet", "origin")
        for lower, upper in zip(branches, branches[1:]):
            self.git("merge-base", "--is-ancestor", f"origin/{lower}", f"origin/{upper}")

    def test_moves_a_stack_onto_its_new_base_in_one_push(self):
        self.commit("main", {"main.txt": "landed\n"})
        out = self.restack("start", "--base", "origin/main", "l1", "l2", "l3", "--no-gates", "--push")
        self.assertEqual(out.count("diff unchanged"), 3, out)
        self.assert_chain("main", "l1", "l2", "l3")
        self.assertEqual(self.remote_file("l3", "main.txt"), "landed")
        self.restack("clean", self.state_dir(out))
        self.assertNotIn("restack/l1", self.git("branch", "--list", "restack/*"))

    def test_moves_a_stale_seam(self):
        """l2 still sits on l1's old tip; it moves onto l1's new tip."""
        self.commit("l1", {"f1.txt": "layer one, fixed\n"})
        out = self.restack("start", "--base", "origin/main", "l1", "l2", "l3", "--no-gates", "--push")
        self.assertEqual(out.count("diff unchanged"), 3, out)
        self.assert_chain("main", "l1", "l2", "l3")
        self.assertEqual(self.remote_file("l3", "f1.txt"), "layer one, fixed")

    def test_stops_on_a_conflict_and_resumes(self):
        self.commit("l2", {"app.txt": "one\nTWO from l2\nthree\n"})
        self.commit("l3", {"f3.txt": "layer three again\n"}, new=True, start="l2")
        self.git("push", "--quiet", "--force", "origin", "l3")
        self.commit("main", {"app.txt": "one\nTWO from main\nthree\n"})
        out = self.restack("start", "--base", "origin/main", "l1", "l2", "l3", "--no-gates", expected=3)
        state, wt = self.state_dir(out), self.state_dir(out) + "/wt"
        Path(wt, "app.txt").write_text("one\nTWO from both\nthree\n")
        self.run_git(wt, "add", "app.txt")
        subprocess.run(["git", "-c", "core.editor=true", "rebase", "--continue"], cwd=wt, env=self.env, check=True, capture_output=True)
        out = self.restack("resume", state, "--no-gates", "--push")
        self.assertIn("l2: ", out)
        self.assertIn("DIFF CHANGED", out)  # l2's own diff now carries the resolution
        self.assert_chain("main", "l1", "l2", "l3")
        self.assertEqual(self.remote_file("l3", "app.txt"), "one\nTWO from both\nthree")

    def test_lease_refuses_to_overwrite_a_newer_push(self):
        self.commit("main", {"main.txt": "landed\n"})
        out = self.restack("start", "--base", "origin/main", "l1", "l2", "l3", "--no-gates")
        self.commit("l2", {"f2.txt": "someone else\n"})
        self.restack("push", self.state_dir(out), expected=1)
        self.assertEqual(self.remote_file("l2", "f2.txt"), "someone else")
        self.assertNotIn("main.txt", self.git("ls-tree", "--name-only", "origin/l1"))

    def test_failing_gates_hold_the_push(self):
        self.commit("main", {"main.txt": "landed\n"})
        self.env.update(TYPECHECK_CMD="true", LINT_CMD="false", FORMAT_CMD="skip", SETUP_HOOK="skip")
        self.restack("start", "--base", "origin/main", "l1", "l2", "l3", "--push", expected=2)
        self.assertNotIn("main.txt", self.git("ls-tree", "--name-only", "origin/l1"))


if __name__ == "__main__":
    unittest.main()
