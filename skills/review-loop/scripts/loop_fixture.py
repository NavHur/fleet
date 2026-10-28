"""The loop.py tests' fixture: a real Git checkout with three commits and a loop directory pinned to it."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("loop.py")
SKILL_DIR = SCRIPT.resolve().parent.parent


def finding(**fields):
    base = {"id": "R1-STD-1", "pr": "7", "priority": "P2", "kind": "bug", "rule": "README.md \"Errors\"",
            "file": "app.py", "line": 2, "title": "Errors are swallowed.", "evidence": "`except: pass`",
            "failure": "A failed save looks like a success.", "recommendation": "Return the error.",
            "decision": False}
    return {**base, **fields}


class LoopCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "--quiet")
        self.git("remote", "add", "origin", "git@github.com:acme/app.git")
        self.base = self.commit({"app.py": "def save():\n    pass\n"})
        self.first = self.commit({"app.py": "def save():\n    try:\n        write()\n    except: pass\n"})
        self.second = self.commit({"app.py": "def save():\n    write()\n"})
        self.loop = self.root / "pr-7"
        self.setUpLoop()

    def setUpLoop(self):
        """Round 1 of self.loop, pinned to the first commit, with the pass's packet and ledger."""
        self.heads(1, self.first)
        (self.loop / "common.md").write_text("# Pass packet\n\nSpec: spec.md\n")
        (self.loop / "ledger.md").write_text("# Review loop: acme/app #7\n\n- Ruling: keep the retry.\n")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True).strip()

    def commit(self, files):
        for path, text in files.items():
            (self.repo / path).write_text(text)
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "c")
        return self.git("rev-parse", "HEAD")

    def heads(self, n, head):
        (self.loop / f"r{n}").mkdir(parents=True, exist_ok=True)
        (self.loop / f"r{n}" / "heads.tsv").write_text(f"7\tbranch\t{self.base}\t{head}\n")

    def run_loop(self, *args, env=None):
        result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                                env=env)
        return result.returncode, result.stdout + result.stderr

    def write(self, n, name, data):
        (self.loop / f"r{n}" / f"{name}.json").write_text(json.dumps(data))

    def two_rounds(self):
        self.run_loop("brief", self.loop, 1, "standards", "--model", "gpt-6.1-sol high")
        self.run_loop("brief", self.loop, 1, "audit", "--model", "gpt-6.1-sol high")
        self.write(1, "standards", {"findings": [finding()], "coverage": [
            {"check": "Core runtime", "status": "incomplete", "note": "not vendored"},
            {"check": "Glossary terms", "status": "clean"}]})
        self.write(1, "audit-7", {"findings": [], "coverage": [
            {"check": "Cognitive complexity (limit 8)", "status": "incomplete", "note": "php missing"}]})
        self.run_loop("outcome", self.loop, "R1-STD-1", "fixed", "--commit", self.second)
        self.heads(2, self.second)
        (self.loop / "r2" / "delta-7.diff").write_text("diff\n")
        self.run_loop("brief", self.loop, 2, "delta", "--model", "gpt-6.1-sol high")
        self.write(2, "delta", {"findings": [finding(id="R2-DELTA-1", priority="P3", kind="advisory",
                                                     rule="pedro/no-nested-ternary", line=1,
                                                     title="A | in the title.", failure="")]})
