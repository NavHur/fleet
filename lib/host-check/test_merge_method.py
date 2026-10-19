import json
from pathlib import Path
import subprocess
import unittest

from shell import unwrapped_commands
from merge_method import refuses

ROOT = Path(__file__).parent


def refused(command):
    return refuses(command, unwrapped_commands(command))


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

    def test_flag_values_are_not_flags(self):
        for command, expected in [
            ("gh pr merge 1 --merge -b '-s fixes'", False), ("gh pr merge 1 --merge --body --squash", False),
            ("gh pr merge 1 -m -tSubject", False), ("gh pr merge 1 -m -t -r", False),
            ("gh pr merge 1 --merge --subject=--help", False), ("gh pr merge 1 --auto -d --merge", False),
            ("gh pr merge 1 --squash -t --help", True), ("gh pr merge 1 --squash --subject --help", True),
            ("gh pr merge 1 -s -b notes -h", False), ("gh pr merge 1 -dt Title -s", True),
            ("gh stack merge --yes --merge-method --help", True), ("gh stack merge --yes --merge --help", False),
        ]:
            with self.subTest(command=command):
                self.assertEqual(refused(command), expected)

    def test_wrapped_calls_are_judged_too(self):
        for command, expected in [
            ("env gh pr merge 1 --squash", True), ("env -u FOO BAR=1 gh pr merge 1 -s", True),
            ("timeout 60 gh pr merge 1 --squash", True), ("timeout -s KILL 60 gh pr merge 1 -s", True),
            ("nohup gh pr merge 1 -s", True), ("nice -n 5 gh pr merge 1 -s", True),
            ("command gh pr merge 1 -s", True), ("exec gh pr merge 1 -s", True), ("time gh pr merge 1 -s", True),
            ("host-check gh pr merge 1 -s", True), ("bg-job start merge -- gh pr merge 1 -s", True),
            ("if true; then gh pr merge 1 -s; fi", True), ("{ gh pr merge 1 -s; }", True),
            ("! gh pr merge 1 -s", True), ("FOO+=x gh pr merge 1 -s", True),
            ("for n in 1 2; do gh pr merge $n --rebase; done", True), ("H=gh; $H pr merge 1 -s", True),
            ("bash -c 'gh pr merge 1 --squash'", True), ("bash -lc 'gh pr merge 1 -s'", True),
            ("host-check bash -lc 'gh stack merge --yes'", True),
            ("bash -c \"bash -c 'gh pr merge 1 -s'\"", True),
            ("env gh pr merge 1 --merge", False), ("timeout 60 gh pr merge 1 --merge", False),
            ("bash -lc 'gh pr merge 1 --merge'", False), ("bg-job start merge -- gh pr merge 1 --merge", False),
            ("if true; then gh pr merge 1 --merge; fi", False), ("env gh pr view 1", False),
            ("echo gh pr merge 1 --squash", False), ("bash -c 'echo hi'", False),
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

    def test_hook_denies_a_shell_string_it_cannot_parse(self):
        command = "host-check bash -lc \"echo $'it\\'s'; gh pr merge 1 --squash\""
        result = subprocess.run(
            ["/usr/bin/python3", str(ROOT / "guard.py"), "claude"],
            input=json.dumps({"tool_input": {"command": command}}), text=True, capture_output=True, check=False, cwd="/",
        )
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
