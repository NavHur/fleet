import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from commit_guard import commit_refusal  # noqa: E402
from test_file_size import BIG, SMALL, Repo  # noqa: E402


class CommitRefusalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(Path(self.tmp.name))
        self.repo.commit(**{"a.py": SMALL})
        self.cwd = str(self.repo.path)

    def tearDown(self):
        self.tmp.cleanup()

    def refusal(self, *words, cwd=None):
        return commit_refusal([(list(words), cwd or self.cwd)])

    def chain(self, *commands, cwd=None):
        return commit_refusal([(command.split(), cwd or self.cwd) for command in commands])

    def test_commit_with_a_big_staged_file_is_refused(self):
        self.repo.write("big.py", BIG)
        self.repo.git("add", "big.py")
        self.assertIn("Commit blocked", self.refusal("git", "commit", "-m", "add"))
        self.assertIsNone(self.refusal("git", "status"))

    def test_commit_all_checks_unstaged_tracked_changes(self):
        self.repo.write("a.py", BIG)
        self.assertIsNone(self.refusal("git", "commit", "-m", "-a"))
        for words in (["git", "commit", "-am", "x"], ["git", "commit", "--all", "-m", "x"],
                      ["git", "commit", "-u", "-a", "-m", "x"]):
            with self.subTest(words=words):
                self.assertIsNotNone(self.refusal(*words))

    def test_a_short_option_with_an_attached_value_ends_the_cluster(self):
        self.repo.write("a.py", BIG)
        for words in (["git", "commit", "-uall", "-m", "x"], ["git", "commit", "-Skey", "-m", "x"]):
            with self.subTest(words=words):
                self.assertIsNone(self.refusal(*words))

    def test_git_dash_c_runs_the_check_in_that_directory(self):
        self.repo.write("big.py", BIG)
        self.repo.git("add", "big.py")
        self.assertIsNotNone(self.refusal("git", "-C", self.cwd, "commit", "-m", "x", cwd=os.sep))

    def test_commit_outside_a_repository_is_allowed(self):
        with tempfile.TemporaryDirectory() as outside:
            self.assertIsNone(self.refusal("git", "commit", "-m", "x", cwd=outside))
            self.assertIsNone(self.refusal("git", "commit", "-m", "x", cwd=os.path.join(outside, "missing")))

    def test_other_git_errors_inside_a_repository_are_refused(self):
        self.repo.write("big.py", BIG)
        self.repo.git("add", "big.py")
        (self.repo.path / ".git" / "index").write_bytes(b"not an index")
        self.assertIn("could not check", self.refusal("git", "commit", "-m", "x"))

    def test_a_glob_in_git_add_stages_what_the_shell_expands_it_to(self):
        self.repo.write("a.py", SMALL + "more\n")
        self.repo.write("sub/big.py", BIG)
        self.assertIsNone(self.chain("git add *.py", "git commit -m x"))
        self.assertIn("sub/big.py", self.chain("git add sub/*.py", "git commit -m x"))
        self.assertIsNone(self.chain("git add *.nothing", "git commit -m x"))

    def test_a_glob_that_matches_nothing_here_reaches_git_as_typed(self):
        self.repo.write("sub/big.log", BIG)
        self.assertIsNone(self.chain("git add -A", "git reset *.log", "git commit -m x"))
        self.assertIsNone(self.chain("git add -A", "git restore --staged *.log", "git commit -m x"))
        self.repo.write("data/big.json", BIG)
        self.assertIn("data/big.json", self.chain("git add *.json", "git commit -m x"))

    def test_pathspec_magic_reaches_git_as_typed(self):
        self.repo.write("big.py", BIG)
        self.repo.write("sub/c.txt", SMALL)
        sub = str(self.repo.path / "sub")
        self.assertIn("big.py", self.chain("git add :/", "git commit -m x", cwd=sub))
        self.assertIn("big.py", self.chain("git add -A :!sub", "git commit -m x"))

    def test_a_reset_with_no_paths_unstages_everything(self):
        self.repo.write("a.py", SMALL + "more\n")
        self.repo.write("big.py", BIG)
        for reset in ("git reset", "git reset -q", "git reset --mixed", "git reset HEAD", "git reset --mixed HEAD --"):
            with self.subTest(reset=reset):
                self.assertIsNone(self.chain("git add -A", reset, "git add a.py", "git commit -m x"))
        self.assertIn("big.py", self.chain("git add -A", "git reset", "git add big.py", "git commit -m x"))

    def test_a_reset_to_head_ends_the_index_at_head(self):
        self.repo.write("big.py", BIG)
        self.repo.git("add", "big.py")
        for reset in ("git reset --keep", "git reset --keep HEAD"):
            with self.subTest(reset=reset):
                self.assertIsNone(self.chain(reset, "git add a.py", "git commit -m x"))
                self.assertIn("big.py", self.chain(reset, "git add big.py", "git commit -m x"))

    def test_a_reset_that_rewrites_the_worktree_ends_the_check(self):
        self.repo.write("big.py", BIG)
        self.repo.git("add", "big.py")
        for reset in ("git reset --hard", "git reset --merge", "git reset --hard HEAD"):
            with self.subTest(reset=reset):
                self.assertIsNone(self.chain(reset, "git add big.py", "git commit -m x"))
                self.assertIsNone(self.chain(reset, "git commit -a -m x"))

    def test_a_soft_reset_to_head_changes_nothing(self):
        self.repo.write("big.py", BIG)
        for reset in ("git reset --soft", "git reset --soft HEAD"):
            with self.subTest(reset=reset):
                self.assertIn("big.py", self.chain("git add -A", reset, "git commit -m x"))

    def test_a_reset_to_another_commit_ends_the_check(self):
        self.repo.commit(**{"b.py": SMALL})
        self.repo.write("big.py", BIG)
        self.repo.git("add", "big.py")
        for reset in ("git reset HEAD~1", "git reset --soft HEAD~1", "git reset --keep HEAD~1"):
            with self.subTest(reset=reset):
                self.assertIsNone(self.chain(reset, "git add a.py", "git commit -m x"))
                self.assertIsNone(self.chain("git add -A", reset, "git add big.py", "git commit -m x"))

    def test_a_reset_to_a_commit_on_an_unborn_head_ends_the_check(self):
        self.repo.git("checkout", "-q", "--orphan", "fresh")
        self.repo.write("big.py", BIG)
        self.repo.git("add", "big.py")
        self.assertIn("big.py", self.chain("git commit -m x"))
        self.assertIsNone(self.chain("git reset main", "git commit -m x"))
        self.assertIsNone(self.chain("git reset --hard", "git commit -m x"))

    def test_a_reset_with_paths_replays_only_the_mixed_mode(self):
        self.repo.write("big.py", BIG)
        self.assertIn("big.py", self.chain("git add -A", "git reset --hard -- big.py", "git commit -m x"))
        self.assertIsNone(self.chain("git add -A", "git reset --mixed big.py", "git commit -m x"))

    def commit_with_a_shrunk_json_fixture(self):
        """HEAD~1 holds data/old.json at 25,000 bytes; HEAD shrinks it and changes x.json."""
        self.repo.commit(**{"data/old.json": "x" * 25_000, "x.json": SMALL})
        self.repo.commit(**{"data/old.json": SMALL, "x.json": SMALL + "more\n"})

    def test_a_glob_restored_from_another_revision_ends_the_check(self):
        self.commit_with_a_shrunk_json_fixture()
        for unstage in ("git reset HEAD~1 -- *.json", "git restore --staged --source=HEAD~1 *.json",
                        "git restore --staged --source HEAD~1 *.json", "git restore --staged -s HEAD~1 *.json",
                        "git restore -S -sHEAD~1 *.json", "git restore -S -qsHEAD~1 *.json"):
            with self.subTest(unstage=unstage):
                self.assertIsNone(self.chain(unstage, "git commit -m x"))

    def test_a_path_restored_from_another_revision_is_replayed(self):
        self.commit_with_a_shrunk_json_fixture()
        for branch in ("keep", "mainline"):
            self.repo.git("branch", branch, "HEAD~1")
        for unstage in ("git reset HEAD~1 -- data/old.json", "git restore --staged --source=HEAD~1 data/old.json",
                        "git restore -S -skeep data/old.json", "git restore --staged -smainline data/old.json"):
            with self.subTest(unstage=unstage):
                self.assertIn("data/old.json", self.chain(unstage, "git commit -m x"))

    def test_a_glob_restored_from_head_is_replayed(self):
        self.repo.write("big.py", BIG)
        self.repo.write("big.json", BIG)
        for unstage in ("git reset HEAD -- *.json", "git restore --staged --source=HEAD *.json",
                        "git restore --staged -s HEAD *.json", "git restore -S -sHEAD *.json"):
            with self.subTest(unstage=unstage):
                refusal = self.chain("git add -A", unstage, "git commit -m x")
                self.assertIn("big.py", refusal)
                self.assertNotIn("big.json", refusal)

    def test_paths_read_from_a_file_end_the_check(self):
        self.repo.write("big.py", BIG)
        for command in ("git restore --staged --pathspec-from-file=list.txt",
                        "git restore --staged --pathspec-from-file list.txt",
                        "git reset --pathspec-from-file list.txt", "git reset --pathspec-from-file=list.txt",
                        "git add --pathspec-from-file list.txt"):
            with self.subTest(command=command):
                self.assertIsNone(self.chain("git add -A", command, "git commit -m x"))

    def test_an_attached_source_is_not_read_as_staged(self):
        self.repo.commit(**{"f.py": SMALL})
        self.repo.git("branch", "STABLE")
        self.repo.commit(**{"f.py": BIG})
        self.repo.write("f.py", SMALL + "edit\n")
        self.repo.write("new.py", BIG)
        self.repo.git("add", "new.py")
        edited = (self.repo.path / "f.py").read_bytes()
        self.assertIsNone(self.chain("git restore -sSTABLE f.py", "git commit -m x"))
        self.assertEqual(edited, (self.repo.path / "f.py").read_bytes())

    def test_a_restore_that_writes_the_worktree_ends_the_check(self):
        self.repo.commit(**{"big.json": "{}\n"})
        self.repo.write("big.json", BIG)
        self.repo.write("a.py", SMALL + "more\n")
        for restore, commit in (("git restore -SW big.json", "git commit -m x"),
                                ("git restore --staged --worktree big.json", "git commit -m x"),
                                ("git restore big.json", "git commit -am x")):
            with self.subTest(restore=restore):
                self.assertIsNone(self.chain("git add -A", restore, commit))
                self.assertEqual(BIG.encode(), (self.repo.path / "big.json").read_bytes())

    def test_a_restore_option_that_git_refuses_with_staged_changes_nothing(self):
        self.repo.commit(**{"f.py": BIG})
        self.repo.git("branch", "old")
        self.repo.commit(**{"f.py": SMALL})
        self.repo.write("big.py", BIG)
        for restore in ("-m --source=old", "--ours --source=old", "--conflict=merge -sold", "-3 -sold"):
            with self.subTest(restore=restore):
                refusal = self.chain(f"git restore --staged {restore} f.py", "git add big.py", "git commit -m x")
                self.assertIn("big.py", refusal)
                self.assertNotIn("f.py", refusal)
        self.assertIn("f.py", self.chain("git restore --staged --source=old f.py", "git commit -m x"))

    def test_a_restore_option_the_replay_does_not_model_ends_the_check(self):
        self.repo.commit(**{"f.py": BIG})
        self.repo.git("branch", "old")
        self.repo.commit(**{"f.py": SMALL})
        self.repo.write("a.py", SMALL + "more\n")
        self.repo.git("add", "a.py")
        for option in ("--overlay", "--ignore-skip-worktree-bits", "-xsold"):
            with self.subTest(option=option):
                self.assertIsNone(self.chain(f"git restore --staged {option} --source=old f.py", "git commit -m x"))

    def test_rm_cached_with_no_cached_leaves_the_worktree_alone(self):
        self.repo.write("big.py", BIG)
        self.repo.git("add", "big.py")
        before = (self.repo.path / "a.py").read_bytes()
        self.assertIsNone(self.chain("git rm --cached --no-cached a.py", "git commit -m x"))
        self.assertEqual(before, (self.repo.path / "a.py").read_bytes())

    def test_rm_that_removes_a_staged_file_is_not_refused(self):
        self.repo.write("big.py", BIG)
        self.assertIsNone(self.chain("git add big.py", "git rm -qf big.py", "git commit -m x"))
        self.assertIsNone(self.chain("git add big.py", "git rm -f --cached --no-cached big.py", "git commit -m x"))

    def test_rm_cached_replays_the_options_it_models(self):
        self.repo.write("sub/big.py", BIG)
        self.repo.write("big.py", BIG)
        for rm in ("git rm -r --cached sub", "git rm -rq --cached sub", "git rm --no-cached --cached -r sub",
                   "git rm --cached -r --ignore-unmatch -- sub"):
            with self.subTest(rm=rm):
                refusal = self.chain("git add -A", rm, "git commit -m x")
                self.assertIn("big.py", refusal)
                self.assertNotIn("sub/big.py", refusal)

    def test_rm_cached_dry_run_changes_nothing(self):
        self.repo.write("sub/big.py", BIG)
        self.assertIn("sub/big.py", self.chain("git add -A", "git rm -n -r --cached sub", "git commit -m x"))
        self.assertIn("sub/big.py", self.chain("git add -A", "git rm --dry-run -r sub", "git commit -m x"))

    def test_rm_with_an_option_the_replay_does_not_model_ends_the_check(self):
        self.repo.write("sub/big.py", BIG)
        self.assertIsNone(self.chain("git add -A", "git rm --cached --sparse -r sub", "git commit -m x"))

    def test_a_reset_with_paths_replays_the_options_it_models(self):
        self.repo.write("big.py", BIG)
        self.repo.write("big2.py", BIG)
        for reset in ("git reset -q -- big.py", "git reset --quiet --refresh big.py", "git reset --mixed --no-refresh big.py"):
            with self.subTest(reset=reset):
                refusal = self.chain("git add -A", reset, "git commit -m x")
                self.assertIn("big2.py", refusal)
                self.assertNotIn("big.py:", refusal)

    def test_a_reset_with_paths_and_an_option_the_replay_does_not_model_ends_the_check(self):
        self.repo.write("big.py", BIG)
        self.repo.write("big2.py", BIG)
        for option in ("-N", "--recurse-submodules"):
            with self.subTest(option=option):
                self.assertIsNone(self.chain("git add -A", f"git reset {option} -- big.py", "git commit -m x"))

    def test_a_pathless_reset_with_an_option_the_replay_does_not_model_ends_the_check(self):
        self.repo.commit(**{"big.json": "{}\n"})
        self.repo.write("big.json", BIG)
        self.assertIn("big.json", self.chain("git add -A", "git reset --mixed", "git add -A", "git commit -m x"))
        for reset in ("git reset --ha", "git reset --har", "git reset --merg"):
            with self.subTest(reset=reset):
                self.assertIsNone(self.chain(reset, "git add -A", "git commit -m x"))
        self.assertIsNone(self.chain("git add big.json", "git reset -N", "git commit -am x"))

    def test_an_attached_source_is_not_read_as_worktree(self):
        self.repo.commit(**{"f.py": SMALL})
        self.repo.git("branch", "WIP")
        self.repo.write("f.py", BIG)
        self.repo.git("add", "f.py")
        self.assertIn("f.py", self.refusal("git", "commit", "-m", "x"))
        self.assertIsNone(self.chain("git restore --staged -sWIP f.py", "git commit -m x"))

    def test_a_glob_in_an_unstaging_command_reaches_git_as_typed(self):
        self.repo.commit(**{"x.json": SMALL})
        self.repo.write("a.py", SMALL + "more\n")
        self.repo.write("x.json", SMALL + "more\n")
        self.repo.write("data/big.json", BIG)
        for unstage in (["git", "reset", "*.json"], ["git", "restore", "--staged", "*.json"],
                        ["git", "rm", "--cached", "*.json"]):
            with self.subTest(unstage=unstage):
                self.assertIsNone(commit_refusal([(["git", "add", "-A"], self.cwd), (unstage, self.cwd),
                                                  (["git", "commit", "-m", "x"], self.cwd)]))

    def test_a_glob_expands_in_the_shell_directory_not_the_one_of_git_dash_c(self):
        self.repo.write("sub/big.py", BIG)
        self.assertIn("sub/big.py", self.chain(f"git -C {self.cwd} add sub/*.py", f"git -C {self.cwd} commit -m x"))
        with tempfile.TemporaryDirectory() as shell_cwd:
            (Path(shell_cwd) / "sub").mkdir()
            (Path(shell_cwd) / "sub" / "elsewhere.py").write_text(SMALL)
            self.assertIsNone(commit_refusal([(["git", "-C", self.cwd, "add", "sub/*.py"], shell_cwd),
                                              (["git", "-C", self.cwd, "commit", "-m", "x"], shell_cwd)]))

    def test_a_commit_with_nothing_over_the_cap_ignores_an_unrelated_submodule_bump(self):
        with tempfile.TemporaryDirectory() as origin:
            Repo(Path(origin)).commit(**{"lib.py": SMALL})
            self.repo.git("-c", "protocol.file.allow=always", "submodule", "add", origin, "sub")
            self.repo.git("commit", "-q", "-m", "add submodule")
            self.repo.git("-C", "sub", "-c", "user.email=t@example.com", "-c", "user.name=T",
                          "commit", "-q", "--allow-empty", "-m", "bump")
            self.repo.git("add", "sub")
            self.assertIsNone(self.refusal("git", "commit", "-m", "bump"))


if __name__ == "__main__":
    unittest.main()
