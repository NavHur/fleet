import json
from pathlib import Path
import subprocess
import unittest

from guard import segments
from merge_method import refuses

ROOT = Path(__file__).parent


def refused(command):
    return refuses(command, segments(command))


class MergeMethodTests(unittest.TestCase):
    def test_pr_merge_refuses_squash_and_rebase(self):
        for command, expected in [
            ("gh pr merge 12 --merge", False), ("gh pr merge 12 -m -d", False), ("gh pr merge 12 --auto --merge", False),
            ("gh pr merge 12 --squash", True), ("gh pr merge 12 -s", True), ("gh pr merge 12 --rebase", True),
            ("gh pr merge 12 -r", True), ("gh pr merge 12 -ds", True), ("gh pr merge 12 --auto --squash", True),
            ("gh pr merge 12 --squash=true", True), ("GH_TOKEN=x /opt/homebrew/bin/gh pr merge 12 -s", True),
            ("gh pr merge 12 -tFix -m", False), ("gh pr merge 12 --merge -t 'squash later'", False),
            ("gh pr merge --help", False), ("gh pr view 12 --json mergeable", False),
            ("git fetch && gh pr merge 12 --squash", True), ('echo "$(gh pr merge 12 -s)"', True),
        ]:
            with self.subTest(command=command):
                self.assertEqual(refused(command), expected)

    def test_stack_merge_must_name_merge(self):
        """Without a method, gh stack merge reuses the last one used, which may be squash."""
        for command, expected in [
            ("gh stack merge --yes --merge", False), ("gh stack merge 42 --merge-method merge --yes", False),
            ("gh stack merge --merge-method=merge", False), ("gh stack merge --help", False),
            ("gh stack merge --yes", True), ("gh stack merge 42", True), ("gh stack merge --yes --squash", True),
            ("gh stack merge --rebase", True), ("gh stack merge --merge-method squash", True),
            ("gh stack merge --merge-method=rebase", True), ("gh stack view", False),
        ]:
            with self.subTest(command=command):
                self.assertEqual(refused(command), expected)

    def test_api_merges_refuse_squash_and_rebase(self):
        for command, expected in [
            ("gh api -X PUT repos/o/r/pulls/12/merge -f merge_method=merge", False),
            ("gh api -X PUT repos/o/r/pulls/12/merge", False),
            ("gh api -X PUT repos/o/r/pulls/12/merge -f merge_method=squash", True),
            ("gh api -X PUT repos/o/r/pulls/12/merge -F merge_method=rebase", True),
            ("gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {pullRequestId: \"X\", mergeMethod: SQUASH}) { clientMutationId } }'", True),
            ("gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"X\", mergeMethod: MERGE}) { clientMutationId } }'", False),
            ("gh api graphql -f query=@q.graphql -f mergeMethod=REBASE", True),
            ("curl -X PUT https://api.github.com/repos/o/r/pulls/12/merge -d '{\"merge_method\":\"squash\"}'", True),
            ("curl -X PUT https://api.github.com/repos/o/r/pulls/12/merge -d '{\"merge_method\":\"merge\"}'", False),
            ("gh api -X PATCH repos/o/r -F allow_squash_merge=false", False),
            ("git commit -m 'stop using merge_method=squash'", False),
        ]:
            with self.subTest(command=command):
                self.assertEqual(refused(command), expected)

    def test_hook_denies_with_the_reason(self):
        for adapter in ["claude", "codex", "cursor", "opencode"]:
            command = "gh pr merge 12 --squash"
            payload = {"command": command} if adapter in {"cursor", "opencode"} else {"tool_input": {"command": command}}
            result = subprocess.run(
                ["/usr/bin/python3", str(ROOT / "guard.py"), adapter],
                input=json.dumps(payload), text=True, capture_output=True, check=False, cwd="/",
            )
            with self.subTest(adapter=adapter):
                if adapter == "opencode":
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("merge commit", result.stderr)
                elif adapter == "cursor":
                    self.assertEqual(json.loads(result.stdout)["permission"], "deny")
                else:
                    output = json.loads(result.stdout)["hookSpecificOutput"]
                    self.assertEqual(output["permissionDecision"], "deny")
                    self.assertIn("gh pr merge N --merge", output["permissionDecisionReason"])


if __name__ == "__main__":
    unittest.main()
