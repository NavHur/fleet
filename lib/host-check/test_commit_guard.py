import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from guard import decision

ROOT = Path(__file__).parent
BIG = "x" * 20_001


class CommitGuardTest(unittest.TestCase):
    """The guard's file-size refusal of an agent `git commit`, through the whole hook decision."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="commit-guard-")
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "T"]):
            self.git(*args)
        self.write("a.py", "small\n")
        self.git("add", "a.py")
        self.git("commit", "-q", "-m", "first")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout

    def write(self, name, text):
        (self.repo / name).write_text(text)

    def denied(self, command, cwd=None):
        return decision({"tool_input": {"command": command, "cwd": str(cwd or self.repo)}})[0]

    def index_bytes(self):
        return (self.repo / ".git" / "index").read_bytes()

    def test_commit_adding_a_file_over_the_size_cap_is_denied(self):
        for name, size, denied in [("small.py", 10, False), ("big.py", 20_001, True)]:
            self.write(name, "x" * size)
            self.git("add", name)
            payload = {"tool_input": {"command": f"cd {self.repo} && git commit -m add"}}
            result = subprocess.run(["/usr/bin/python3", str(ROOT / "guard.py"), "claude"], input=json.dumps(payload),
                                    text=True, capture_output=True, check=True, cwd="/")
            output = json.loads(result.stdout).get("hookSpecificOutput", {})
            with self.subTest(name=name):
                self.assertEqual(output.get("permissionDecision"), "deny" if denied else None)
                self.assertEqual("big.py" in output.get("permissionDecisionReason", ""), denied)

    def test_wrapped_commits_are_denied(self):
        self.write("big.py", BIG)
        self.git("add", "big.py")
        for command in ["timeout 60 git commit -m x", "nice -n 5 git commit -m x", "env -i git commit -m x",
                        "if true; then git commit -m x; fi", "bash -c 'git commit -m x'",
                        "GIT_EDITOR=true git commit -m x"]:
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))

    def test_staging_in_the_same_command_is_checked(self):
        self.write("big.py", BIG)
        for command, cwd in [("git add big.py && git commit -m add", None), ("git add -A && git commit -m add", None),
                             ("git stage big.py; git commit -m add", None),
                             (f"git -C {self.repo} add . && git -C {self.repo} commit -m add", "/")]:
            with self.subTest(command=command):
                self.assertTrue(self.denied(command, cwd=cwd))

    def test_staging_a_small_file_ignores_an_unrelated_untracked_big_file(self):
        self.write("big.py", BIG)
        self.write("small.py", "small\n")
        self.assertFalse(self.denied("git add small.py && git commit -m add"))

    def test_replaying_the_staging_leaves_the_real_index_alone(self):
        self.write("big.py", BIG)
        before = self.index_bytes()
        self.assertTrue(self.denied("git add big.py && git commit -m add"))
        self.assertEqual(self.index_bytes(), before)
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")

    def test_unstaging_in_the_same_command_is_replayed_in_order(self):
        self.write("big.py", BIG)
        head, before = self.git("rev-parse", "HEAD"), self.index_bytes()
        for command in ["git add -A && git reset big.py && git commit -m x",
                        "git add -A && git reset HEAD -- big.py && git commit -m x",
                        "git add -A && git restore --staged big.py && git commit -m x",
                        "git add -A && git rm -q --cached big.py && git commit -m x",
                        "git add -A && git reset && git commit -m x"]:
            with self.subTest(command=command):
                self.assertFalse(self.denied(command))
        for command in ["git add -A && git reset --soft && git commit -m x",
                        "git add -A && git reset --soft HEAD && git commit -m x"]:
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
        self.assertTrue(self.denied("git add -A && git restore --staged --worktree big.py && git commit -m x"))
        self.assertTrue(self.denied("git add big.py && git reset -q big.py && git add big.py && git commit -m x"))
        self.assertEqual((self.git("rev-parse", "HEAD"), self.index_bytes()), (head, before))
        self.assertEqual(self.git("status", "--porcelain"), "?? big.py\n")

    def test_commands_in_a_bash_string_run_where_its_cd_leads(self):
        self.write("big.py", BIG)
        with tempfile.TemporaryDirectory() as outside:
            command = f"bash -c 'cd {self.repo} && git add big.py && git commit -m x'"
            self.assertTrue(self.denied(command, cwd=outside))
            self.assertFalse(self.denied(f"bash -c 'cd {outside} && git add big.py && git commit -m x'"))

    def test_interactive_staging_is_not_replayed(self):
        self.write("big.py", BIG)
        self.assertFalse(self.denied("git add -p big.py && git commit -m add"))

    def test_commit_in_a_repository_created_by_the_same_command_is_allowed(self):
        with tempfile.TemporaryDirectory() as outside:
            command = "mkdir x && cd x && git init && git commit --allow-empty -m init"
            self.assertFalse(self.denied(command, cwd=outside))


if __name__ == "__main__":
    unittest.main()
