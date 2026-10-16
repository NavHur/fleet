import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import hooks  # noqa: E402


class ClaudeSettings(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.settings = self.home / ".claude" / "settings.json"
        self.settings.parent.mkdir()
        self.config = self.home / "claude-settings.json"
        self.config.write_text(json.dumps({"$comment": "ignored", "syncClaudeAiSkills": False,
                                           "skillOverrides": {"dataviz": "user-invocable-only"}}))
        self.host = self.home / "host"
        self.host.mkdir()
        (self.host / "host.json").write_text("{}")
        patches = (mock.patch.object(hooks, "HOME", self.home), mock.patch.object(hooks, "CLAUDE_SETTINGS", self.config),
                   mock.patch.object(hooks, "HOST_CONF", self.host / "host.json"))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_writes_managed_keys_and_keeps_the_rest(self):
        self.settings.write_text(json.dumps({"model": "opus", "includeCoAuthoredBy": False,
                                             "skillOverrides": {"other": "on"}}))
        path, data, details = hooks.claude_settings()
        self.assertEqual(path, self.settings)
        self.assertEqual(data, {"model": "opus", "syncClaudeAiSkills": False,
                                "skillOverrides": {"dataviz": "user-invocable-only"}})
        self.assertEqual(details["keys"], "syncClaudeAiSkills, skillOverrides, includeCoAuthoredBy")

    def test_no_change_when_settings_match(self):
        self.settings.write_text(json.dumps({"model": "opus", "syncClaudeAiSkills": False,
                                             "skillOverrides": {"dataviz": "user-invocable-only"}}))
        self.assertIsNone(hooks.claude_settings())

    def test_host_file_replaces_keys(self):
        (self.host / "claude-settings.json").write_text(json.dumps({"$comment": "ignored", "syncClaudeAiSkills": True}))
        self.settings.write_text("{}")
        _, data, _ = hooks.claude_settings()
        self.assertEqual(data, {"syncClaudeAiSkills": True, "skillOverrides": {"dataviz": "user-invocable-only"}})

    def test_env_merges_per_variable(self):
        self.config.write_text(json.dumps({"env": {"ENABLE_TOOL_SEARCH": "true"}}))
        self.settings.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://proxy", "ENABLE_TOOL_SEARCH": "auto"}}))
        _, data, details = hooks.claude_settings()
        self.assertEqual(data["env"], {"ANTHROPIC_BASE_URL": "http://proxy", "ENABLE_TOOL_SEARCH": "true"})
        self.assertEqual(details["keys"], "env")
        self.settings.write_text(json.dumps(data))
        self.assertIsNone(hooks.claude_settings())

    def test_shipped_config_is_valid(self):
        managed = json.loads((Path(__file__).resolve().parents[2] / "config" / "claude-settings.json").read_text())
        self.assertEqual(managed["attribution"], {"commit": "", "pr": "", "sessionUrl": False})
        for host in (Path(__file__).resolve().parents[2] / "hosts").glob("*/claude-settings.json"):
            self.assertIsInstance(json.loads(host.read_text()), dict, host)


if __name__ == "__main__":
    unittest.main()
