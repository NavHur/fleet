"""Run with: cd hosts/workbox/claude-hooks && python3 -m unittest test_agent_cli_guard"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("agent_cli_guard", Path(__file__).with_name("agent-cli-guard.py"))
agent_cli_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_cli_guard)


def launches(command, cwd="/"):
    return [(kind, value, detached) for kind, value, detached, _ in agent_cli_guard.find(command, cwd)]


class AgentCliGuardTests(unittest.TestCase):
    def test_direct_cli_runs_are_found_past_wrappers_and_shells(self):
        for command in ["claude -p hi", "setsid env -u HOME claude -p hi", "timeout -s KILL 60 codex exec x",
                        "bash -lc 'cd /tmp && opencode run x'", "stdbuf -oL cursor-agent -p x"]:
            with self.subTest(command=command):
                self.assertEqual([kind for kind, _, _ in launches(command)], ["direct"])

    def test_a_lone_ampersand_marks_the_launch_detached(self):
        self.assertEqual(launches("claude -p hi &"), [("direct", "claude", True)])
        self.assertEqual(launches("claude -p hi 2>&1 | tee log"), [("direct", "claude", False)])

    def test_a_package_script_that_launches_a_cli_is_found(self):
        with tempfile.TemporaryDirectory(prefix="agent-cli-") as root:
            Path(root, "package.json").write_text(json.dumps({"scripts": {"ask": "claude -p review"}}))
            self.assertEqual(launches("pnpm ask", root), [("direct", "claude", False)])

    def test_help_maintenance_and_unparseable_commands_pass(self):
        for command in ["claude --help", "claude mcp list", "codex login", "echo 'claude -p", "rg 'claude -p'"]:
            with self.subTest(command=command):
                self.assertEqual(launches(command), [])


if __name__ == "__main__":
    unittest.main()
