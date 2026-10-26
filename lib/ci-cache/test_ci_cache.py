import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


class Checkout:
    """A git checkout of a tiny Godot project, with its own CI state directory."""

    def __init__(self, path, state):
        self.path = path
        self.env = dict(os.environ, FLEET_CI_STATE=str(state), GITHUB_REPOSITORY="owner/game")
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        self.commit({"project.godot": "config_version=5\n", "art/hero.png": "png",
                     "art/hero.png.import": "[remap]\n", "main.gd": "extends Node\n"})

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.path, check=True, capture_output=True)

    def commit(self, files):
        for name, text in files.items():
            (self.path / name).parent.mkdir(parents=True, exist_ok=True)
            (self.path / name).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "commit")

    def run(self, *args):
        """The command's outputs as a dict, read from the GITHUB_OUTPUT file it appended to."""
        with tempfile.NamedTemporaryFile("r") as output:
            subprocess.run([sys.executable, str(ROOT / "ci_cache.py"), *args], cwd=self.path, check=True,
                           capture_output=True, env=dict(self.env, GITHUB_OUTPUT=output.name))
            return dict(line.rstrip("\n").split("=", 1) for line in output)


class CiCacheTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        (self.temp / "work").mkdir()
        self.repo = Checkout(self.temp / "work", self.temp / "state")

    def test_a_recorded_tree_passes_until_the_tree_or_key_changes(self):
        self.assertEqual(self.repo.run("passed-check", "gate")["hit"], "false")
        self.repo.run("passed-record", "gate")
        self.assertEqual(self.repo.run("passed-check", "gate")["hit"], "true")
        self.assertEqual(self.repo.run("passed-check", "gate-godot-4.8")["hit"], "false")
        self.repo.commit({"main.gd": "extends Node2D\n"})
        self.assertEqual(self.repo.run("passed-check", "gate")["hit"], "false")

    def test_a_merge_commit_with_the_tested_tree_passes(self):
        self.repo.git("switch", "-q", "-c", "feature")
        self.repo.commit({"main.gd": "extends Node2D\n"})
        self.repo.run("passed-record", "gate")
        self.repo.git("switch", "-q", "main")
        self.repo.git("merge", "-q", "--no-ff", "-m", "merge", "feature")
        self.assertEqual(self.repo.run("passed-check", "gate")["hit"], "true")

    def test_restore_pins_assets_and_round_trips_the_import_cache(self):
        first = self.repo.run("godot-restore", "godot-4.7.1")
        self.assertEqual(first["hit"], "false")
        self.assertTrue(first["key"].startswith("godot-4.7.1-"))
        self.assertEqual(os.stat(self.repo.path / "art/hero.png").st_mtime, 0)
        (self.repo.path / ".godot/imported").mkdir(parents=True)
        (self.repo.path / ".godot/imported/hero.ctex").write_text("texture")
        self.repo.run("godot-save", first["key"])

        (self.temp / "clone").mkdir()
        clone = Checkout(self.temp / "clone", self.temp / "state")
        second = clone.run("godot-restore", "godot-4.7.1")
        self.assertEqual(second, {"hit": "true", "key": first["key"]})
        self.assertEqual((clone.path / ".godot/imported/hero.ctex").read_text(), "texture")

    def test_a_changed_asset_misses(self):
        key = self.repo.run("godot-restore", "godot-4.7.1")["key"]
        self.repo.run("godot-save", key)
        self.repo.commit({"art/hero.png": "new png"})
        self.assertEqual(self.repo.run("godot-restore", "godot-4.7.1")["hit"], "false")

    def test_save_keeps_the_three_most_recent_entries(self):
        for version in range(5):
            self.repo.run("godot-save", f"key-{version}")
        entries = [path for path in (self.temp / "state/owner/game/godot").iterdir()
                   if not path.name.startswith(".")]
        self.assertEqual(len(entries), 3)


if __name__ == "__main__":
    unittest.main()
