"""Claude Code transcripts: ~/.claude/projects/<project>/<session>.jsonl, and subagents/ beside them."""
from __future__ import annotations

from events import Event, Summary, Tokens, as_text, prompt_text, records

SYNTHETIC = "<synthetic>"  # a message the harness wrote, with no model call behind it
USAGE = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
# The input field that best says what a tool call did, in order of preference.
TOOL_INPUT = ("command", "file_path", "pattern", "prompt", "task", "query", "url", "skill")
LATE = ('"usage"', '"ai-title"')  # what summary still needs once it has the session's start


def summary(lines):
    result, seen = Summary(), set()
    for line in lines:
        if result.prompt and not any(marker in line for marker in LATE):
            continue  # parsing every line of a long session costs more than the rest of the scan
        for record in records([line]):
            read(result, record, seen)
    return result


def read(result, record, seen):
    result.cwd = result.cwd or record.get("cwd", "")
    result.started = result.started or record.get("timestamp", "")
    kind = record.get("type")
    if kind == "ai-title":
        result.title = record.get("aiTitle") or result.title
    elif kind == "user" and not result.prompt:
        result.prompt = user_prompt(record)
    elif kind == "assistant":
        add_usage(result, record.get("message") or {}, seen)


def user_prompt(record):
    if record.get("isMeta") or record.get("isCompactSummary"):
        return ""
    return prompt_text(as_text((record.get("message") or {}).get("content")))


def add_usage(result, message, seen):
    """Count a model call once: a response with several content blocks repeats its usage on each record."""
    usage, model = message.get("usage"), message.get("model", "")
    if not usage or model == SYNTHETIC or message.get("id") in seen:
        return
    seen.add(message.get("id"))
    result.add(model, Tokens(*(usage.get(key) or 0 for key in USAGE)))


def events(lines):
    for record in records(lines):
        yield from record_events(record)


def record_events(record):
    kind, message = record.get("type"), record.get("message") or {}
    if kind == "system" and record.get("subtype") == "compact_boundary":
        return [Event("compaction", "")]
    if kind not in ("user", "assistant"):
        return []
    if record.get("isCompactSummary"):
        return [Event("compaction", as_text(message.get("content")))]
    return message_events(kind, message.get("content"))


def message_events(role, content):
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content or []
    found = (block_event(role, block) for block in blocks if isinstance(block, dict))
    return [event for event in found if event]


def block_event(role, block):
    kind = block.get("type")
    if kind == "text":
        return Event(role, block.get("text", ""))
    if kind == "tool_use":
        return Event("tool", tool_input(block.get("input")), name=block.get("name", ""))
    if kind == "tool_result":
        return Event("result", as_text(block.get("content")), error=bool(block.get("is_error")))
    return None


def tool_input(value):
    if not isinstance(value, dict):
        return as_text(value)
    shown = next((value[key] for key in TOOL_INPUT if value.get(key)), None)
    if shown is None:
        return as_text(value)
    description = value.get("description")
    return f"({description}) {as_text(shown)}" if description and "command" in value else as_text(shown)
