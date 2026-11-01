"""Behavior tests for loop.py start and finish: the run record, the saved spec, and the pass's session costs.

Run from this directory: python3 -m unittest test_loop_record
"""

import json
import os
import unittest

import loop_record
from loop_fixture import LoopCase

FAKE_GH = """\
#!/usr/bin/env python3
import sys
if sys.argv[1:] != ["api", "repos/acme/app/pulls/7", "--jq", ".body"]:
    sys.exit(f"unexpected: {sys.argv[1:]}")
print("Body of PR 7.")
"""

# Echoes its arguments into the state dir and lists sessions from that dir's sessions.json.
FAKE_TRANSCRIPTS = """\
#!/usr/bin/env python3
import os, sys
from pathlib import Path
state = Path(os.environ["FAKE_STATE"])
(state / "transcripts-args").write_text(" ".join(sys.argv[1:]))
print((state / "sessions.json").read_text())
"""


def session(sid, prompt, usd):
    return {"agent": "claude", "id": sid, "started": "2026-10-30T01:00:00Z", "prompt": prompt, "usd": usd,
            "tokens": {"claude-opus-5-5": {"fresh": 1, "write": 0, "read": 0, "out": 1, "write_1h": 0}}}


class RecordTests(LoopCase):
    def setUp(self):
        super().setUp()
        self.loop = self.loop.rename(self.root / "pr-7-p2")
        (self.loop / "run.json").unlink()
        self.state, self.bin = self.root / "state", self.root / "bin"
        self.state.mkdir()
        self.bin.mkdir()
        for name, text in (("gh", FAKE_GH), ("transcripts", FAKE_TRANSCRIPTS)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        self.env = {**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "FAKE_STATE": str(self.state),
                    "HOME": str(self.root / "home")}

    def run_record(self, *args):
        return self.run_loop(*args, env=self.env)

    def test_brief_refuses_until_start_has_run(self):
        code, out = self.run_record("brief", self.loop, 1, "standards", "--model", "m")
        self.assertEqual(code, 2)
        self.assertIn("run loop.py start", out)

    def test_start_saves_the_pr_body_and_the_run_record(self):
        code, out = self.run_record("start", self.loop, "--orchestrator", "claude-sonnet-5-5 high",
                                    "--checkout", self.repo)
        self.assertEqual(code, 0, out)
        self.assertEqual((self.loop / "spec" / "pr-7.md").read_text(), "Body of PR 7.\n")
        run = json.loads((self.loop / "run.json").read_text())
        self.assertEqual((run["repo"], run["orchestrator"]), ("acme/app", "claude-sonnet-5-5 high"))
        code, out = self.run_record("brief", self.loop, 1, "standards", "--model", "m")
        self.assertEqual(code, 0, out)

    def test_a_resumed_start_keeps_the_spec_and_start_time_it_saved_first(self):
        self.run_record("start", self.loop, "--orchestrator", "a", "--checkout", self.repo)
        first = json.loads((self.loop / "run.json").read_text())["started"]
        (self.loop / "spec" / "pr-7.md").write_text("As reviewed.\n")
        self.run_record("start", self.loop, "--orchestrator", "b", "--checkout", self.repo)
        run = json.loads((self.loop / "run.json").read_text())
        self.assertEqual((run["started"], run["orchestrator"]), (first, "b"))
        self.assertEqual((self.loop / "spec" / "pr-7.md").read_text(), "As reviewed.\n")

    def test_start_copies_spec_files_instead_of_pr_bodies(self):
        spec = self.root / "issue.md"
        spec.write_text("The issue.\n")
        code, out = self.run_record("start", self.loop, "--orchestrator", "a", "--checkout", self.repo,
                                    "--spec", spec)
        self.assertEqual(code, 0, out)
        self.assertEqual([p.name for p in (self.loop / "spec").iterdir()], ["issue.md"])

    def test_finish_costs_this_pass_sessions_by_role(self):
        (self.loop / "run.json").write_text('{"started": "2026-10-30T00:00:00+00:00"}\n')
        loop = "~/.cache/review-loop"
        sessions = [
            session("orch-2", f"You are the orchestrator of a review loop.\nLedgers: {loop}/pr-7-p1 and -p2\n"
                              "Pass: 2\n", 3.0),
            session("orch-1", f"You are the orchestrator of a review loop.\nLedgers: {loop}/pr-7-p1 and -p2\n"
                              "Pass: 1\n", 9.0),
            session("rev-2", f"You are the spec reviewer in round 1 of a review loop.\nRead {loop}/pr-7-p2/r1/c", 0.5),
            session("rev-1", f"You are the spec reviewer in round 1 of a review loop.\nRead {loop}/pr-7-p1/r1/c", 0.4),
            session("work-2", f"Fix R1-SPEC-1. The ledger is {loop}/pr-7-p2/ledger.md.", None),
        ]
        (self.state / "sessions.json").write_text(json.dumps(sessions))
        code, out = self.run_record("finish", self.loop)
        self.assertEqual(code, 0, out)
        archived = self.root / "home" / ".local" / "share" / "review-loop-archive" / "pr-7-p2"
        self.assertEqual(out, "3 sessions, $3.50 (orchestrator $3.00, reviewer $0.50, worker $0.00); "
                              f"unpriced: work-2\narchived in {archived}\n")
        self.assertEqual((self.state / "transcripts-args").read_text(),
                         "list --since 2026-10-30 --prompt review-loop/pr\\-7-p\\d+(?![\\w-]) --json")
        usage = json.loads((self.loop / "usage.json").read_text())
        self.assertEqual([(s["id"], s["role"]) for s in usage["sessions"]],
                         [("orch-2", "orchestrator"), ("rev-2", "reviewer"), ("work-2", "worker")])
        self.assertEqual(json.loads((self.loop / "run.json").read_text())["finished"], usage["at"])
        self.assertEqual((archived / "usage.json").read_text(), (self.loop / "usage.json").read_text())
        self.assertEqual((archived / "ledger.md").read_text(), (self.loop / "ledger.md").read_text())

    def test_a_second_finish_drops_files_removed_from_the_ledger(self):
        (self.state / "sessions.json").write_text("[]")
        (self.loop / "scratch.md").write_text("temporary\n")
        self.run_record("finish", self.loop)
        archived = self.root / "home" / ".local" / "share" / "review-loop-archive" / "pr-7-p2"
        self.assertTrue((archived / "scratch.md").exists())
        (self.loop / "scratch.md").unlink()
        code, out = self.run_record("finish", self.loop)
        self.assertEqual(code, 0, out)
        self.assertFalse((archived / "scratch.md").exists())
        self.assertEqual((archived / "ledger.md").read_text(), (self.loop / "ledger.md").read_text())
        self.assertEqual([p.name for p in archived.parent.iterdir()], ["pr-7-p2"])

    def test_a_failed_archive_swap_keeps_the_previous_archive(self):
        archive = self.root / "archive"
        final = archive / "pr-7-p2"
        final.mkdir(parents=True)
        (final / "ledger.md").write_text("previous\n")
        with self.assertRaises(FileNotFoundError):
            loop_record.replace_archive(archive / ".pr-7-p2-new-gone", final)
        self.assertEqual((final / "ledger.md").read_text(), "previous\n")
        self.assertEqual([p.name for p in archive.iterdir()], ["pr-7-p2"])

    def test_start_refuses_two_specs_with_the_same_file_name(self):
        first, second = self.root / "a" / "spec.md", self.root / "b" / "spec.md"
        for path in (first, second):
            path.parent.mkdir()
            path.write_text(f"{path.parent.name}\n")
        code, out = self.run_record("start", self.loop, "--orchestrator", "a", "--checkout", self.repo,
                                    "--spec", first, "--spec", second)
        self.assertEqual(code, 2)
        self.assertIn(str(first), out)
        self.assertIn(str(second), out)
        self.assertFalse((self.loop / "spec" / "spec.md").exists())

    def test_finish_leaves_out_an_orchestrator_of_a_loop_with_a_longer_number(self):
        (self.loop / "run.json").write_text('{"started": "2026-10-30T00:00:00+00:00"}\n')
        loop = "~/.cache/review-loop"
        sessions = [
            session("orch-7", f"You are the orchestrator of a review loop.\nLedgers: {loop}/pr-7-p1 and -p2\n"
                              "Pass: 2\n", 3.0),
            session("orch-70", f"You are the orchestrator of a review loop.\nLedgers: {loop}/pr-70-p1 and -p2\n"
                               "Pass: 2\n", 8.0),
        ]
        (self.state / "sessions.json").write_text(json.dumps(sessions))
        code, out = self.run_record("finish", self.loop)
        self.assertEqual(code, 0, out)
        usage = json.loads((self.loop / "usage.json").read_text())
        self.assertEqual([s["id"] for s in usage["sessions"]], ["orch-7"])


if __name__ == "__main__":
    unittest.main()
