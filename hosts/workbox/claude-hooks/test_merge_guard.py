"""Run with: cd hosts/workbox/claude-hooks && python3 -m unittest test_merge_guard"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("merge_guard", Path(__file__).with_name("merge-guard.py"))
merge_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge_guard)


class MergeGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="merge-guard-")
        self.transcript = Path(self.temp.name) / "session.jsonl"
        self.say("let's ship it")

    def tearDown(self):
        self.temp.cleanup()

    def say(self, text):
        line = {"type": "user", "message": {"role": "user", "content": text}}
        self.transcript.write_text(json.dumps(line) + "\n")

    def reason(self, command, **payload):
        return merge_guard.bash_reason(command, {"transcript_path": str(self.transcript), **payload})

    def test_help_passes(self):
        for command in ["gh stack merge --help", "gh pr merge -h", "gh pr merge 12 --help"]:
            with self.subTest(command=command):
                self.assertIsNone(self.reason(command))

    def test_merges_need_a_number(self):
        self.assertIn("Name the PR number", self.reason("gh stack merge"))

    def test_merges_need_chat_approval(self):
        self.assertIn("hasn't approved merging PR #12", self.reason("gh pr merge 12 --merge"))
        self.say("merge 12")
        self.assertIsNone(self.reason("gh pr merge 12 --merge"))
        self.assertIn("#13", self.reason("gh pr merge 12 && gh pr merge 13"))

    def test_merges_behind_wrappers_need_approval(self):
        for command in ["env -u GH_TOKEN gh pr merge 12 --merge", "setsid gh pr merge 12 --merge"]:
            with self.subTest(command=command):
                self.assertIn("hasn't approved merging PR #12", self.reason(command))

    def test_negation_withholds_approval(self):
        self.say("don't merge 12 yet")
        self.assertIsNotNone(self.reason("gh pr merge 12"))

    def test_subagents_cannot_merge(self):
        self.say("merge 12")
        self.assertIn("Subagents can't merge", self.reason("gh pr merge 12", agent_id="a1"))

    def test_rest_and_graphql_merges(self):
        self.assertIn("#7", self.reason("gh api -X PUT repos/o/r/pulls/7/merge"))
        self.assertIn("off limits", self.reason("gh api graphql -f query='mutation { mergePullRequest }'"))
        self.assertIsNone(self.reason("gh api repos/o/r/pulls/7"))


if __name__ == "__main__":
    unittest.main()
