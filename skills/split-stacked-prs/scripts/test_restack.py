"""Drive restack.py against a repository with a real bare origin."""

from pathlib import Path
import subprocess
import sys
import unittest

from stack_fixture import StackRepo

SCRIPT = Path(__file__).with_name("restack.py")


class RestackTests(unittest.TestCase):
    def setUp(self):
        self.repo = StackRepo(self)
        self.repo.add_origin()
        self.repo.environ.update(HOME=str(self.repo.temp))
        self.commit("main", {"app.txt": "one\ntwo\nthree\n"})
        self.commit("l1", {"f1.txt": "layer one\n"}, start="main")
        self.commit("l2", {"f2.txt": "layer two\n"}, start="l1")
        self.commit("l3", {"f3.txt": "layer three\n"}, start="l2")

    def git_in(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, env=self.repo.environ, text=True, check=True, capture_output=True).stdout.strip()

    def commit(self, branch, files, start=None):
        """Commit FILES on BRANCH (created at START when given) and force-push it."""
        self.repo.git("checkout", "--quiet", *(["-B", branch, start] if start else [branch]))
        self.repo.commit(files, f"{branch} change")
        self.repo.git("push", "--quiet", "--force", "origin", branch)

    def restack(self, *args, expected=0):
        result = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.repo.root, env=self.repo.environ, text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout

    def state_dir(self, output):
        return next(line.split(": ", 1)[1] for line in output.splitlines() if line.startswith("state: "))

    def remote_file(self, branch, name):
        self.repo.git("fetch", "--quiet", "origin")
        return self.repo.git("show", f"origin/{branch}:{name}")

    def assert_chain(self, *branches):
        self.repo.git("fetch", "--quiet", "origin")
        for lower, upper in zip(branches, branches[1:]):
            self.repo.git("merge-base", "--is-ancestor", f"origin/{lower}", f"origin/{upper}")

    def test_moves_a_stack_onto_its_new_base_in_one_push(self):
        self.commit("main", {"main.txt": "landed\n"})
        out = self.restack("start", "--base", "origin/main", "l1", "l2", "l3", "--no-gates", "--push")
        self.assertEqual(out.count("diff unchanged"), 3, out)
        self.assert_chain("main", "l1", "l2", "l3")
        self.assertEqual(self.remote_file("l3", "main.txt"), "landed")
        self.restack("clean", self.state_dir(out))
        self.assertNotIn("restack/l1", self.repo.git("branch", "--list", "restack/*"))

    def test_moves_a_stale_seam(self):
        """l2 still sits on l1's old tip; it moves onto l1's new tip."""
        self.commit("l1", {"f1.txt": "layer one, fixed\n"})
        out = self.restack("start", "--base", "origin/main", "l1", "l2", "l3", "--no-gates", "--push")
        self.assertEqual(out.count("diff unchanged"), 3, out)
        self.assert_chain("main", "l1", "l2", "l3")
        self.assertEqual(self.remote_file("l3", "f1.txt"), "layer one, fixed")

    def test_stops_on_a_conflict_and_resumes(self):
        self.commit("l2", {"app.txt": "one\nTWO from l2\nthree\n"})
        self.commit("l3", {"f3.txt": "layer three again\n"}, start="l2")
        self.repo.git("push", "--quiet", "--force", "origin", "l3")
        self.commit("main", {"app.txt": "one\nTWO from main\nthree\n"})
        out = self.restack("start", "--base", "origin/main", "l1", "l2", "l3", "--no-gates", expected=3)
        state, wt = self.state_dir(out), self.state_dir(out) + "/wt"
        Path(wt, "app.txt").write_text("one\nTWO from both\nthree\n")
        self.git_in(wt, "add", "app.txt")
        self.git_in(wt, "-c", "core.editor=true", "rebase", "--continue")
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
        self.assertNotIn("main.txt", self.repo.git("ls-tree", "--name-only", "origin/l1"))

    def test_failing_gates_hold_the_push(self):
        self.commit("main", {"main.txt": "landed\n"})
        self.repo.environ.update(TYPECHECK_CMD="true", LINT_CMD="false", FORMAT_CMD="skip", SETUP_HOOK="skip")
        self.restack("start", "--base", "origin/main", "l1", "l2", "l3", "--push", expected=2)
        self.assertNotIn("main.txt", self.repo.git("ls-tree", "--name-only", "origin/l1"))


if __name__ == "__main__":
    unittest.main()
