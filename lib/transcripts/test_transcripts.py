import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import pricing  # noqa: E402
import sessions  # noqa: E402
import transcripts  # noqa: E402
from events import Tokens  # noqa: E402

CLAUDE_ID = "11111111-2222-3333-4444-555555555555"
CODEX_ID = "01a17da8-763d-7c23-a37f-4ab04c4ebfc8"
RATES = {
    "anthropic.claude-opus-5-5": {"input_cost_per_token": 1e-6, "cache_creation_input_token_cost": 2e-6,
                                  "cache_read_input_token_cost": 1e-7, "output_cost_per_token": 1e-5},
    "openai/gpt-6.1-terra": {"input_cost_per_token": 1e-6, "cache_read_input_token_cost": 1e-7,
                             "output_cost_per_token": 1e-5},
}


def usage(fresh, write, read, out):
    return {"input_tokens": fresh, "cache_creation_input_tokens": write, "cache_read_input_tokens": read,
            "output_tokens": out}


def claude_records():
    def assistant(message_id, blocks, model="claude-opus-5-5"):
        return {"type": "assistant", "message": {"id": message_id, "model": model, "content": blocks,
                                                 "usage": usage(100, 1000, 10000, 50)}}
    return [
        {"type": "user", "cwd": "/w/fleet/t3-1", "timestamp": "2026-10-27T10:00:00Z", "isMeta": True,
         "message": {"content": "Base directory for this skill"}},
        {"type": "user", "message": {"content": "<system-reminder>ctx</system-reminder>\nFix the login PATH"}},
        {"type": "ai-title", "aiTitle": "Draft title"},
        # One response, two content blocks: its usage is on both records and counts once.
        assistant("m1", [{"type": "text", "text": "Looking."}]),
        assistant("m1", [{"type": "tool_use", "name": "Bash",
                          "input": {"command": "ls", "description": "List files"}}]),
        {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True,
                                                  "content": [{"type": "text", "text": "no such file"}]}]}},
        assistant("m2", [{"type": "text", "text": "No reply."}], model="<synthetic>"),
        {"type": "system", "subtype": "compact_boundary"},
        {"type": "ai-title", "aiTitle": "Login PATH fix"},
    ]


def codex_records():
    def item(payload):
        return {"type": "response_item", "payload": payload}

    def total(fresh_and_cached, cached, out):
        info = {"total_token_usage": {"input_tokens": fresh_and_cached, "cached_input_tokens": cached,
                                      "output_tokens": out}}
        return {"type": "event_msg", "payload": {"type": "token_count", "info": info}}
    return [
        {"type": "session_meta", "payload": {"cwd": "/w/fleet/pedro-x", "timestamp": "2026-10-26T09:00:00Z"}},
        {"type": "turn_context", "payload": {"model": "gpt-6.1-terra"}},
        item({"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "You are Codex"}]}),
        item({"type": "message", "role": "user", "content": [{"type": "input_text", "text": "# AGENTS.md instructions"}]}),
        item({"type": "message", "role": "user",
              "content": [{"type": "input_text", "text": "You are the delta reviewer in round 2"}]}),
        total(1000, 600, 40),
        item({"type": "function_call", "name": "exec", "arguments": '{"cmd": "git diff"}'}),
        item({"type": "function_call_output", "output": "diff --git a/x b/x"}),
        item({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "1 P2 finding"}]}),
        total(5000, 3000, 200),
    ]


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records) + '{"truncated": \n')


class Transcripts(unittest.TestCase):
    def setUp(self):
        home = Path(tempfile.mkdtemp())
        roots = {"claude": home / "claude", "codex": home / "codex"}
        write_jsonl(roots["claude"] / "-w-fleet" / f"{CLAUDE_ID}.jsonl", claude_records())
        write_jsonl(roots["codex"] / "2026/10/26" / f"rollout-2026-10-26T09-00-00-{CODEX_ID}.jsonl", codex_records())
        rates = home / "rates.json"
        rates.write_text(json.dumps({"document": RATES}))
        for target, value in ((sessions, {"ROOTS": roots}), (pricing, {"RATES": rates})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            transcripts.main(list(argv))
        return out.getvalue()

    def test_claude_summary_counts_each_response_once_and_takes_the_last_title(self):
        summary = sessions.resolve(CLAUDE_ID[:8]).summary()
        self.assertEqual((summary.cwd, summary.title, summary.prompt), ("/w/fleet/t3-1", "Login PATH fix",
                                                                          "Fix the login PATH"))
        self.assertEqual(summary.tokens, {"claude-opus-5-5": Tokens(100, 1000, 10000, 50)})

    def test_codex_summary_skips_context_and_keeps_the_last_total(self):
        summary = sessions.resolve(CODEX_ID[:8]).summary()
        self.assertEqual(summary.prompt, "You are the delta reviewer in round 2")
        self.assertEqual(summary.tokens, {"gpt-6.1-terra": Tokens(fresh=2000, read=3000, out=200)})

    def test_show_condenses_both_formats(self):
        claude = self.run_cli("show", CLAUDE_ID[:8]).split("\n", 2)
        self.assertEqual(claude[1], "# Login PATH fix")
        self.assertEqual(claude[2], "\n".join([
            "[1 U] Base directory for this skill",
            "[2 U] <system-reminder>ctx</system-reminder>\nFix the login PATH",
            "[3 A] Looking.",
            "[4 T:Bash] (List files) ls",
            "[5 R ERROR 12c] no such file",
            "[6 A] No reply.",
            "==== COMPACTION ====",
        ]) + "\n")
        codex = self.run_cli("show", CODEX_ID[:8]).splitlines()
        self.assertEqual(codex[1:], ["[1 U] You are the delta reviewer in round 2", '[2 T:exec] {"cmd": "git diff"}',
                                     "[3 R 18c] diff --git a/x b/x", "[4 A] 1 P2 finding"])

    def test_show_cuts_long_text(self):
        self.assertEqual(transcripts.cut("abcdef", 4), "abcd …[+2]")

    def test_filters_pick_sessions_by_agent_prompt_and_grep(self):
        def ids(*argv):
            return [line.split()[7] for line in self.run_cli("list", "--since", "2000-01-01", *argv).splitlines()]
        self.assertEqual(ids(), [CODEX_ID[:8], CLAUDE_ID[:8]])  # by start
        self.assertEqual(ids("--agent", "claude"), [CLAUDE_ID[:8]])
        self.assertEqual(ids("--prompt", "reviewer in round"), [CODEX_ID[:8]])
        self.assertEqual(ids("--prompt", "Login PATH"), [CLAUDE_ID[:8]])  # the title counts
        self.assertEqual(ids("--grep", "compact_boundary"), [CLAUDE_ID[:8]])
        self.assertEqual(ids("--cwd", "pedro-x"), [CODEX_ID[:8]])

    def test_list_json_prices_each_session(self):
        found = json.loads(self.run_cli("list", "--since", "2000-01-01", "--json"))
        usd = {record["agent"]: round(record["usd"], 6) for record in found}
        # claude: 100 fresh, 1000 written, 10000 read, 50 out; codex: 2000 fresh, 3000 read, 200 out.
        self.assertEqual(usd, {"claude": 0.0036, "codex": 0.0043})

    def test_usage_groups_and_totals(self):
        lines = self.run_cli("usage", "--since", "2000-01-01", "--by", "agent").splitlines()
        self.assertEqual([line.split()[0] for line in lines[1:]], ["codex", "claude", "total"])
        self.assertTrue(lines[-1].endswith("$0.01"))

    def test_usage_names_models_with_no_rate(self):
        pricing.RATES.write_text(json.dumps({"document": {}}))
        output = self.run_cli("usage", "--since", "2000-01-01")
        self.assertIn("unpriced", output)
        self.assertIn("claude-opus-5-5, gpt-6.1-terra", output)

    def test_usage_marks_unpriced_and_partly_priced_costs(self):
        pricing.RATES.write_text(json.dumps({"document": {"claude-opus-5-5": RATES["anthropic.claude-opus-5-5"]}}))
        rows = {line.split()[0]: line.split()[-1] for line in self.run_cli("usage", "--since", "2000-01-01").splitlines()}
        self.assertEqual((rows["claude-opus-5-5"], rows["gpt-6.1-terra"], rows["total"]), ("$0.00", "?", "$0.00+"))

    def test_usage_by_cwd_keeps_directories_with_the_same_ending_apart(self):
        records = claude_records()
        records[0] = {**records[0], "cwd": "/v/fleet/t3-1"}
        write_jsonl(sessions.ROOTS["claude"] / "-v-fleet" / "99999999-2222-3333-4444-555555555555.jsonl", records)
        lines = self.run_cli("usage", "--since", "2000-01-01", "--by", "cwd").splitlines()
        self.assertEqual(sorted(line.split()[0] for line in lines[1:-1]),
                         ["/v/fleet/t3-1", "/w/fleet/pedro-x", "/w/fleet/t3-1"])

    def test_an_unknown_id_exits_with_a_message(self):
        with self.assertRaises(SystemExit) as raised:
            transcripts.main(["show", "ffff"])
        self.assertIn("no session with an id starting 'ffff'", str(raised.exception.code))


class Pricing(unittest.TestCase):
    def test_rate_tries_provider_prefixes_and_drops_a_context_tag(self):
        rates = {"anthropic.claude-opus-5-5": "opus", "openai/gpt-6.1-terra": "terra"}
        self.assertEqual(pricing.rate(rates, "claude-opus-5-5[1m]"), "opus")
        self.assertEqual(pricing.rate(rates, "gpt-6.1-terra"), "terra")
        self.assertIsNone(pricing.rate(rates, "gpt-7"))

    def test_an_entry_without_token_prices_is_unpriced_not_free(self):
        image_model = {"dall-e-3": {"input_cost_per_pixel": 1e-8}}
        self.assertIsNone(pricing.cost(image_model, "dall-e-3", Tokens(fresh=1000, out=10)))


if __name__ == "__main__":
    unittest.main()
