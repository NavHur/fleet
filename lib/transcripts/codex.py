"""Codex transcripts: ~/.codex/sessions/YYYY/MM/DD/rollout-<time>-<id>.jsonl."""
from __future__ import annotations

from events import Event, Summary, Tokens, as_text, prompt_text, records, summary_records

# Context Codex sends as user messages ahead of the user's own words.
CONTEXT = ("# AGENTS.md instructions", "<environment_context>", "<user_instructions>", "<INSTRUCTIONS>")
LATE = ('"token_count"', '"turn_context"')  # what summary still needs once it has the session's start
CALLS = ("function_call", "custom_tool_call", "local_shell_call")
OUTPUTS = ("function_call_output", "custom_tool_call_output", "local_shell_call_output")


class Reading:
    """A summary under way: Codex reports a running total, so only the last one counts."""

    def __init__(self):
        self.summary, self.model, self.total = Summary(), "", None

    def read(self, record):
        payload = record.get("payload") or {}
        kind = record.get("type")
        if kind == "session_meta":
            self.summary.cwd = payload.get("cwd", "")
            self.summary.started = payload.get("timestamp", "")
        elif kind == "turn_context":
            self.model = payload.get("model") or self.model
        elif kind == "response_item" and not self.summary.prompt:
            self.summary.prompt = user_prompt(payload)
        elif payload.get("type") == "token_count" and payload.get("info"):
            self.total = payload["info"]["total_token_usage"]

    def result(self):
        if self.total:
            # ceiling: the session's whole total goes to its last model; a model switch mid-session is rare.
            self.summary.add(self.model, tokens(self.total))
        return self.summary


def tokens(total):
    cached = total.get("cached_input_tokens", 0)
    return Tokens(fresh=total.get("input_tokens", 0) - cached, read=cached, out=total.get("output_tokens", 0))


def summary(lines):
    reading = Reading()
    for record in summary_records(lines, LATE, lambda: reading.summary.prompt):
        reading.read(record)
    return reading.result()


def user_prompt(payload):
    if payload.get("type") != "message" or payload.get("role") != "user":
        return ""
    text = as_text(payload.get("content"))
    return "" if text.lstrip().startswith(CONTEXT) else prompt_text(text)


def events(lines):
    for record in records(lines):
        event = record_event(record)
        if event:
            yield event


def record_event(record):
    payload = record.get("payload") or {}
    if record.get("type") == "compacted":
        return Event("compaction", as_text(payload.get("message", "")))
    if record.get("type") != "response_item":
        return None
    kind = payload.get("type")
    if kind == "message":
        return message_event(payload)
    if kind in CALLS:
        return Event("tool", as_text(payload.get("arguments") or payload.get("input") or payload.get("action")),
                     name=payload.get("name", kind))
    if kind in OUTPUTS:
        return Event("result", output_text(payload.get("output")))
    return None


def message_event(payload):
    role, text = payload.get("role"), as_text(payload.get("content"))
    if role == "assistant":
        return Event("assistant", text)
    if role == "user" and not text.lstrip().startswith(CONTEXT):
        return Event("user", text)
    return None  # developer instructions, and the context ahead of a user's words


def output_text(output):
    if isinstance(output, dict):
        return as_text(output.get("content", output))
    return as_text(output)
