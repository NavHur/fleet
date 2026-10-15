"""Drive build_layers.sh against a real repository with commit sections."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("build_layers.sh")
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class BuildLayersTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "repo"
        self.manifests = Path(temp.name) / "layers"
        self.manifests.mkdir()
        self.root.mkdir()
        self.git("init", "-q", "-b", "main")
        self.write({"app.ts": "app\n", "old.ts": "old\n"})
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "source")
        (self.root / "old.ts").unlink()
        self.write({"types.ts": "types\n", "domain.ts": "domain\n", "view.ts": "view\n"})
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "source")
        self.git("checkout", "-q", "main")

    def git(self, *args):
        env = {**os.environ, **IDENTITY}
        return subprocess.check_output(["git", *args], cwd=self.root, text=True, env=env).strip()

    def write(self, files):
        for path, content in files.items():
            (self.root / path).write_text(content)

    def build(self, layers, expected=0):
        for name, text in layers.items():
            (self.manifests / name).write_text(text)
        result = subprocess.run(
            ["bash", str(SCRIPT), "--base", "main", "--source", "source",
             "--manifests", str(self.manifests), "--prefix", "s-"],
            cwd=self.root, text=True, capture_output=True, env={**os.environ, **IDENTITY},
        )
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def subjects(self, rev_range):
        return self.git("log", "--reverse", "--format=%s", rev_range).splitlines()

    def test_sections_become_commits_within_a_layer(self):
        self.build({
            "01-domain": "types.ts\n# commit: feat: add the types\n# commit: feat: add the domain\ndomain.ts\nold.ts\n",
            "02-view": "view.ts\n",
        })
        self.assertEqual(self.subjects("main..s-01-domain"), ["feat: add the types", "feat: add the domain"])
        self.assertEqual(self.git("show", "--name-only", "--format=", "s-01-domain"), "domain.ts\nold.ts")
        self.assertEqual(self.subjects("s-01-domain..s-02-view"), ["wip: 02-view"])
        self.assertEqual(self.git("diff", "source", "s-02-view"), "")

    def test_a_section_without_changes_fails(self):
        result = self.build({
            "01-all": "# commit: feat: everything\ntypes.ts\ndomain.ts\nview.ts\nold.ts\n# commit: feat: nothing\n",
        }, expected=1)
        self.assertIn("commit 2 (feat: nothing) changes nothing", result.stderr)


if __name__ == "__main__":
    unittest.main()
