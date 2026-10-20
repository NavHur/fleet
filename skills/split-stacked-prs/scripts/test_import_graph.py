"""Exercise the import graph CLI against real Git trees without creating commits."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("import_graph.py")
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
BODY = "".join(f"export const value{index} = {index};\n" for index in range(40))


class ImportGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "--quiet")
        self.paths = set()
        self.base = self.tree({})

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True, env={**os.environ, **IDENTITY}).strip()

    def tree(self, files):
        for path in self.paths:
            (self.root / path).unlink()
        for path, content in files.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        self.paths = set(files)
        self.git("add", "--all")
        return self.git("write-tree")

    def run_graph(self, before, after, *options):
        base = self.tree(before)
        tip = self.tree(after)
        out = self.root.parent / f"{self.root.name}-graph.json"
        self.addCleanup(lambda: out.unlink(missing_ok=True))
        result = subprocess.run(
            [sys.executable, str(SCRIPT), base, tip, "--json", str(out), *options],
            cwd=self.root, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return result.stdout, json.loads(out.read_text())

    def test_rename_shows_its_old_path(self):
        text, graph = self.run_graph({"src/old.ts": BODY}, {"src/new.ts": BODY + "export const extra = 1;\n"})
        self.assertEqual(list(graph), ["src/new.ts"])
        self.assertEqual(graph["src/new.ts"]["old_path"], "src/old.ts")
        self.assertEqual(graph["src/new.ts"]["status"], "R")
        self.assertIn("src/new.ts (from src/old.ts)", text)

    def test_plain_file_has_no_old_path(self):
        text, graph = self.run_graph({}, {"src/app.ts": BODY})
        self.assertIsNone(graph["src/app.ts"]["old_path"])
        self.assertNotIn("(from", text)

    def test_lockfile_and_test_weigh_zero(self):
        text, graph = self.run_graph({}, {
            "src/app.ts": BODY,
            "yarn.lock": BODY,
            "src/app.test.ts": BODY,
            "src/spec/case.ts": BODY,
        }, "--test", "src/spec/*")
        self.assertGreater(graph["src/app.ts"]["weighted"], 0)
        self.assertEqual(graph["yarn.lock"]["weighted"], 0)
        self.assertTrue(graph["yarn.lock"]["excluded"])
        self.assertEqual(graph["yarn.lock"]["reason"], "lockfile")
        self.assertEqual(graph["src/app.test.ts"]["weighted"], 0)
        self.assertTrue(graph["src/app.test.ts"]["test"])
        self.assertEqual(graph["src/spec/case.ts"]["weighted"], 0)
        self.assertTrue(graph["src/spec/case.ts"]["test"])
        self.assertIn("X", next(line for line in text.splitlines() if "yarn.lock" in line)[:4])
        self.assertIn("T", next(line for line in text.splitlines() if "src/spec/case.ts" in line)[:4])

    def test_generated_glob_weighs_zero(self):
        _, graph = self.run_graph({}, {"src/app.ts": BODY, "gen/api.ts": BODY}, "--generated", "gen/*")
        self.assertEqual(graph["gen/api.ts"]["weighted"], 0)
        self.assertEqual(graph["gen/api.ts"]["reason"], "verified-generated-pattern")

    def test_deleted_file_is_listed(self):
        text, graph = self.run_graph({"src/gone.ts": BODY, "src/keep.ts": BODY}, {"src/keep.ts": BODY})
        node = graph["src/gone.ts"]
        self.assertEqual(node["status"], "D")
        self.assertEqual(node["deps"], [])
        self.assertEqual(node["added"], 0)
        self.assertGreater(node["deleted"], 0)
        self.assertIn("src/gone.ts", text)

    def test_imports_among_changed_files(self):
        _, graph = self.run_graph({}, {
            "src/a.ts": "import { value0 } from './b';\n" + BODY,
            "src/b.ts": BODY,
        })
        self.assertEqual(graph["src/a.ts"]["deps"], ["src/b.ts"])
        self.assertEqual(graph["src/b.ts"]["deps"], [])


if __name__ == "__main__":
    unittest.main()
