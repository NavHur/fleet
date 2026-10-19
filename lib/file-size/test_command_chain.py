from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from commit_guard import commit_refusal  # noqa: E402
from test_file_size import BIG, SMALL, Repo  # noqa: E402


class CommandChainTest(unittest.TestCase):
    """What the commands before a `git commit` in its line do to whether the commit is checked."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(Path(self.tmp.name))
        self.repo.commit(**{"a.py": SMALL})
        self.cwd = str(self.repo.path)

    def tearDown(self):
        self.tmp.cleanup()

    def chain(self, *commands):
        """The refusal for commands run in order here, each a string or its words as the walker reads them."""
        return commit_refusal([(command.split() if isinstance(command, str) else command, self.cwd)
                               for command in commands])

    def test_a_command_the_check_does_not_model_ends_it(self):
        self.repo.commit(**{"big.json": "{}\n"})
        self.repo.write("big.json", BIG)
        self.repo.write("scratch.json", BIG)
        self.repo.write("a.py", SMALL + "more\n")
        self.assertIn("big.json", self.chain("git commit -am x"))
        for chain in ("git checkout -- big.json|git commit -am x",
                      "git add big.json|git checkout HEAD -- big.json|git commit -m x",
                      "git stash push big.json|git commit -am x", "git clean -f|git add -A|git commit -m x",
                      "rm -f scratch.json|git add -A|git commit -m x", "git switch -|git commit -am x",
                      "git merge x|git commit -am x", "git mv a.py b.py|git commit -am x", "make|git commit -am x",
                      "git diff --output=out.txt|git commit -am x", "git log --out=x|git commit -am x"):
            with self.subTest(chain=chain):
                self.assertIsNone(self.chain(*chain.split("|")))

    def test_read_only_git_and_modelled_index_verbs_keep_the_check(self):
        self.repo.write("big.py", BIG)
        for read in ("git status", "git log -1", "git show", "git diff --stat", "git rev-parse HEAD", "git ls-files"):
            with self.subTest(read=read):
                self.assertIn("big.py", self.chain(read, "git add big.py", "git commit -m x"))

    def test_an_index_command_built_by_an_expansion_ends_the_check(self):
        self.repo.write("big.json", BIG)
        self.repo.git("add", "big.json")
        self.assertIn("big.json", self.chain("git add a.py", "git commit -m x"))
        for unstage in (["git", "reset", "-q", "--", "__substitution__"], ["git", "restore", "--staged", "$F"],
                        ["git", "rm", "-q", "--cached", "$f"], ["git", "reset", "`git diff --cached --name-only`"],
                        ["git", "restore", "--staged", "--source=$REV", "big.json"]):
            with self.subTest(unstage=unstage):
                self.assertIsNone(self.chain(unstage, "git commit -m x"))

    def test_a_cd_the_walker_cannot_follow_ends_the_check(self):
        self.repo.write("a.py", BIG)
        for cd in (["cd", "$B"], ["cd", "-"], ["pushd", "`pwd`"], ["cd", "__substitution__"], ["cd", "-P", "$B"]):
            with self.subTest(cd=cd):
                self.assertIsNone(self.chain(cd, "git commit -am x"))

    def test_a_cd_the_walker_can_follow_keeps_the_check(self):
        self.repo.write("a.py", BIG)
        for cd in (["cd"], ["cd", "-P", self.cwd], ["pushd", self.cwd]):
            with self.subTest(cd=cd):
                self.assertIn("a.py", self.chain(cd, "git commit -am x"))

    def test_an_empty_command_runs_nothing(self):
        self.repo.write("big.py", BIG)
        self.assertIn("big.py", self.chain([], "git add big.py", "git commit -m x"))


if __name__ == "__main__":
    unittest.main()
