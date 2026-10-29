from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parent / "pr_assets.py"
REMOTE = "https://github.com/acme/widgets.git"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, capture_output=True).stdout.strip()


class Fleet:
    """A bare repo standing in for github.com/acme/widgets, and clones of it."""

    def __init__(self, root):
        self.root = root
        self.bare = root / "widgets.git"
        git(root, "init", "-q", "--bare", "-b", "main", str(self.bare))

    def clone(self, name, branch):
        path = self.root / name
        git(self.root, "init", "-q", "-b", branch, str(path))
        for key, value in [("user.email", "t@example.com"), ("user.name", "T"),
                           (f"url.{self.bare}.insteadOf", REMOTE)]:
            git(path, "config", key, value)
        git(path, "remote", "add", "origin", REMOTE)
        (path / "app.txt").write_text("app\n")
        git(path, "add", "-A")
        git(path, "commit", "-q", "-m", "app")
        return path

    def shots(self, name, **files):
        folder = self.root / "shots" / name
        folder.mkdir(parents=True, exist_ok=True)
        for file, text in files.items():
            (folder / file).write_text(text)
        return folder

    def assets(self):
        tree = git(self.bare, "ls-tree", "-r", "--name-only", "pr-assets")
        return sorted(tree.splitlines())

    def show(self, path):
        return git(self.bare, "show", f"pr-assets:{path}")


def upload(cwd, *args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, text=True, capture_output=True)


class PrAssetsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fleet = Fleet(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_upload_creates_the_branch_and_prints_raw_blob_links(self):
        repo = self.fleet.clone("one", "feat/x")
        after = self.fleet.shots("after", **{"home-desktop.jpg": "jpg"})
        run = upload(repo, str(after))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.fleet.assets(), ["feat/x/after/home-desktop.jpg"])
        self.assertEqual(run.stdout.splitlines(), [
            "https://github.com/acme/widgets/blob/pr-assets/feat/x/after/home-desktop.jpg?raw=true"])

    def test_leaves_the_checkout_untouched(self):
        repo = self.fleet.clone("one", "feat/x")
        head = git(repo, "rev-parse", "HEAD")
        upload(repo, str(self.fleet.shots("after", **{"a.jpg": "a"})))
        self.assertEqual(git(repo, "rev-parse", "HEAD"), head)
        self.assertEqual(git(repo, "branch", "--show-current"), "feat/x")
        self.assertEqual(git(repo, "status", "--porcelain"), "")

    def test_rerun_replaces_only_its_own_folder(self):
        repo = self.fleet.clone("one", "feat/x")
        other = self.fleet.clone("two", "feat/y")
        upload(other, str(self.fleet.shots("after", **{"y.jpg": "y"})))
        upload(repo, str(self.fleet.shots("before", **{"old.jpg": "old"})))
        stale = self.fleet.shots("before", **{"new.jpg": "new"})
        (stale / "old.jpg").unlink()
        upload(repo, str(stale))
        self.assertEqual(self.fleet.assets(), ["feat/x/before/new.jpg", "feat/y/after/y.jpg"])

    def test_builds_on_a_head_that_moved_since_the_last_fetch(self):
        repo = self.fleet.clone("one", "feat/x")
        other = self.fleet.clone("two", "feat/y")
        upload(repo, str(self.fleet.shots("before", **{"x.jpg": "x1"})))
        upload(other, str(self.fleet.shots("after", **{"y.jpg": "y"})))
        upload(repo, str(self.fleet.shots("before", **{"x.jpg": "x2"})))
        self.assertEqual(self.fleet.assets(), ["feat/x/before/x.jpg", "feat/y/after/y.jpg"])
        self.assertEqual(self.fleet.show("feat/x/before/x.jpg"), "x2")

    def test_refuses_a_missing_folder(self):
        repo = self.fleet.clone("one", "feat/x")
        run = upload(repo, str(self.fleet.root / "nope"))
        self.assertEqual(run.returncode, 1)
        self.assertIn("not a folder with files", run.stderr)

    def test_detached_head_needs_a_branch_name(self):
        repo = self.fleet.clone("one", "feat/x")
        git(repo, "checkout", "-q", "--detach")
        folder = self.fleet.shots("after", **{"a.jpg": "a"})
        self.assertIn("--branch", upload(repo, str(folder)).stderr)
        self.assertEqual(upload(repo, "--branch", "feat/x", str(folder)).returncode, 0)
        self.assertEqual(self.fleet.assets(), ["feat/x/after/a.jpg"])


if __name__ == "__main__":
    unittest.main()
