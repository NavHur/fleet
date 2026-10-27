"""Drive build_layers.sh against a real repository with commit sections."""

from pathlib import Path
import subprocess
import unittest

from stack_fixture import StackRepo

SCRIPT = Path(__file__).with_name("build_layers.sh")


class BuildLayersTests(unittest.TestCase):
    def setUp(self):
        self.repo = StackRepo(self)
        self.repo.commit({"old.ts": "old\n", ".gitignore": "generated.txt\n"}, "base")
        self.repo.branch("source", "main", {
            "old.ts": None, "types.ts": "types\n", "domain.ts": "domain\n", "view.ts": "view\n",
        })

    def build(self, layers, expected=0):
        for name, text in layers.items():
            self.repo.manifest(name, text)
        result = subprocess.run(
            ["bash", str(SCRIPT), "--base", "main", "--source", "source",
             "--manifests", str(self.repo.manifests), "--prefix", "s-"],
            cwd=self.repo.root, text=True, capture_output=True, env=self.repo.env(),
        )
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def subjects(self, rev_range):
        return self.repo.git("log", "--reverse", "--format=%s", rev_range).splitlines()

    def test_sections_become_commits_within_a_layer(self):
        self.build({
            "01-domain": "types.ts\n# commit: feat: add the types\n# commit: feat: add the domain\ndomain.ts\nold.ts\n",
            "02-view": "view.ts\n",
        })
        self.assertEqual(self.subjects("main..s-01-domain"), ["feat: add the types", "feat: add the domain"])
        self.assertEqual(self.repo.git("show", "--name-only", "--format=", "s-01-domain"), "domain.ts\nold.ts")
        self.assertEqual(self.subjects("s-01-domain..s-02-view"), ["wip: 02-view"])
        self.assertEqual(self.repo.git("diff", "source", "s-02-view"), "")

    def test_a_section_without_changes_fails(self):
        result = self.build({
            "01-all": "# commit: feat: everything\ntypes.ts\ndomain.ts\nview.ts\nold.ts\n# commit: feat: nothing\n",
        }, expected=1)
        self.assertIn("commit 2 (feat: nothing) changes nothing", result.stderr)

    def test_force_added_ignored_file_is_staged_in_its_section(self):
        self.repo.git("checkout", "-q", "-B", "source", "main")
        (self.repo.root / "generated.txt").write_text("generated\n")
        (self.repo.root / "view.ts").write_text("view\n")
        self.repo.git("add", "-f", "generated.txt", "view.ts")
        self.repo.git("commit", "-q", "-m", "source")
        self.repo.git("checkout", "-q", "main")
        result = self.build({
            "01-generated": "# commit: feat: add the generated output\ngenerated.txt\n# commit: feat: add the view\nview.ts\n",
        })
        self.assertIn("top tree equals source", result.stdout)
        self.assertEqual(self.subjects("main..s-01-generated"), ["feat: add the generated output", "feat: add the view"])


if __name__ == "__main__":
    unittest.main()
