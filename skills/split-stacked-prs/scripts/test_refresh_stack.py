"""Drive refresh_stack.py over a stack built by build_layers.sh, without GitHub."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).parent
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def lines(count, prefix="line"):
    """`count` distinct 48-byte lines: 250 fill a commit's weighted ceiling."""
    return "".join(f"{prefix} {index}".ljust(47) + "\n" for index in range(count))


class RefreshStackTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "repo"
        self.manifests = Path(temp.name) / "layers"
        self.manifests.mkdir()
        self.root.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.root / "app.ts").write_text("app\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def git(self, *args):
        env = {**os.environ, **IDENTITY}
        return subprocess.check_output(["git", *args], cwd=self.root, text=True, env=env).strip()

    def stack(self, files, layers):
        self.git("checkout", "-q", "-b", "source", "main")
        for path, content in files.items():
            (self.root / path).write_text(content)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "source")
        self.git("checkout", "-q", "main")
        for name, text in layers.items():
            (self.manifests / name).write_text(text)
        env = {**os.environ, **IDENTITY}
        subprocess.run(
            ["bash", str(HERE / "build_layers.sh"), "--base", "main", "--source", "source",
             "--manifests", str(self.manifests), "--prefix", "s-"],
            cwd=self.root, check=True, capture_output=True, env=env,
        )
        return self.refresh()

    def refresh(self):
        return subprocess.run(
            [sys.executable, str(HERE / "refresh_stack.py"), "--manifests", str(self.manifests),
             "--prefix", "s-", "--base", "main"],
            cwd=self.root, text=True, capture_output=True,
        )

    def row(self, result, name):
        return next(line.split() for line in result.stdout.splitlines() if line.startswith(name + " "))

    def test_layer_of_small_commits_passes(self):
        result = self.stack(
            {"a.ts": lines(200), "b.ts": lines(200)},
            {"01-feature": "# commit: feat: add a\na.ts\n# commit: feat: add b\nb.ts\n"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.row(result, "01-feature")[2:8], ["19.2", "19.2", "0.0", "0.0", "2", "within-cap"])

    def test_one_commit_over_the_commit_ceiling_fails_the_layer(self):
        result = self.stack({"a.ts": lines(300)}, {"01-feature": "a.ts\n"})
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(self.row(result, "01-feature")[7], "commit-over")
        self.assertIn("weighted 14.4 KB, raw 14.4 KB over 12.0/24.0 KB: wip: 01-feature", result.stdout)

    def test_layer_under_the_floor_is_small_but_passes(self):
        result = self.stack(
            {"a.ts": lines(200), "b.ts": lines(200), "c.ts": lines(200)},
            {"01-ab": "# commit: feat: a\na.ts\n# commit: feat: b\nb.ts\n", "02-c": "c.ts\n"},
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.row(result, "01-ab")[7], "within-cap")
        self.assertEqual(self.row(result, "02-c")[7], "small")

    def test_a_layer_whose_branch_is_missing_stops_with_the_reason(self):
        self.stack({"a.ts": lines(10)}, {"01-feature": "a.ts\n"})
        (self.manifests / "02-gone").write_text("b.ts\n")
        result = self.refresh()
        self.assertEqual(result.returncode, 1)
        self.assertIn("s-02-gone", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_without_an_origin_the_bodies_are_skipped_with_git_s_reason(self):
        result = self.stack({"a.ts": lines(10)}, {"01-feature": "a.ts\n"})
        self.assertIn("PR bodies skipped: git -C . remote get-url origin", result.stderr)
        self.assertIn("No such remote", result.stderr)


if __name__ == "__main__":
    unittest.main()
