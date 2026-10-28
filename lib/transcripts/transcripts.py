#!/usr/bin/env python3
"""Read this machine's Claude Code and Codex session transcripts.

    transcripts list  [filters] [--json]     one line per session: start, agent, model, cost, place, id, title
    transcripts show  SESSION [--full]       the conversation, each message and tool output cut short
    transcripts usage [filters] [--by KEY]   tokens and list-price cost by model, agent, cwd, day, or week

Filters: --since 7d, 36h, or 2026-10-01 (default 7d, by the file's last write); --agent claude or codex;
--cwd TEXT, part of the session's working directory; --prompt REGEX, its first prompt or title;
--grep REGEX, any line of the file. SESSION is a transcript's path or the start of the id `list` prints.
Prices come from ~/.t3/userdata/usage-model-rates.json; a model it does not list is unpriced.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pricing  # noqa: E402
import sessions  # noqa: E402
from events import Tokens  # noqa: E402

AGO = re.compile(r"(\d+)([dh])")
LIMITS = {
    "brief": {"user": 3000, "assistant": 700, "tool": 350, "result": 500, "compaction": 300},
    "full": {"user": 6000, "assistant": 2000, "tool": 1200, "result": 1500, "compaction": 3000},
}
TAGS = {"user": "U", "assistant": "A"}


def since(value):
    match = AGO.fullmatch(value)
    if match:
        return time.time() - int(match.group(1)) * (86400 if match.group(2) == "d" else 3600)
    return datetime.fromisoformat(value).timestamp()


def started_at(summary):
    if not summary.started:
        return None
    return datetime.fromisoformat(summary.started.replace("Z", "+00:00")).astimezone()


def place(cwd):
    return "/".join(Path(cwd).parts[-2:]) if cwd else "?"


def home_relative(cwd):
    if not cwd:
        return "?"
    path = Path(cwd)
    return f"~/{path.relative_to(Path.home())}" if path.is_relative_to(Path.home()) else cwd


def headline(summary):
    text = (summary.title or summary.prompt).strip()
    return text.splitlines()[0][:90] if text else ""


def cut(text, limit):
    return text if len(text) <= limit else f"{text[:limit]} …[+{len(text) - limit}]"


def keeps_lines(session, grep):
    if grep is None:
        return True
    with session.lines() as lines:
        return any(grep.search(line) for line in lines)


def keeps_summary(summary, cwd, prompt):
    if cwd and cwd not in summary.cwd:
        return False
    return prompt is None or bool(prompt.search(summary.prompt) or prompt.search(summary.title))


def pattern(value):
    try:
        return re.compile(value)
    except re.error as error:
        raise argparse.ArgumentTypeError(f"{value!r} is not a regex: {error}") from error


def matching(args):
    """(session, summary) for each session the filters keep, oldest first."""
    for session in sessions.find(args.since, (args.agent,) if args.agent else tuple(sessions.ROOTS)):
        if not keeps_lines(session, args.grep):
            continue
        summary = session.summary()
        if keeps_summary(summary, args.cwd, args.prompt):
            yield session, summary


def session_cost(rates, summary):
    costs = [pricing.cost(rates, model, tokens) for model, tokens in summary.tokens.items()]
    return None if None in costs else sum(costs)


def money(usd):
    return f"{'?' if usd is None else '$' + format(usd, '.2f'):>8}"


def main_model(summary):
    return max(summary.tokens, key=lambda model: summary.tokens[model].total) if summary.tokens else "-"


def list_line(session, summary, rates):
    started = started_at(summary)
    total = sum(tokens.total for tokens in summary.tokens.values())
    return (f"{started.strftime('%m-%d %H:%M') if started else '?':<11} {session.agent:<6} "
            f"{main_model(summary)[:22]:<22} {money(session_cost(rates, summary))} {total / 1e6:>6.1f}M "
            f"{place(summary.cwd)[:32]:<32} {session.id[:8]}  {headline(summary)}")


def list_record(session, summary, rates):
    record = {"agent": session.agent, "id": session.id, "path": str(session.path), **asdict(summary)}
    record["prompt"] = summary.prompt[:2000]
    record["usd"] = session_cost(rates, summary)
    return record


def list_sessions(args):
    rates = pricing.load()
    if args.json:
        json.dump([list_record(*found, rates) for found in matching(args)], sys.stdout, indent=1)
        print()
        return
    for session, summary in sorted(matching(args), key=lambda found: found[1].started):
        print(list_line(session, summary, rates))


def event_line(number, event, limits):
    text = cut(event.text, limits[event.kind])
    if event.kind == "compaction":
        return f"==== COMPACTION ====\n{text}".rstrip()
    if event.kind == "tool":
        return f"[{number} T:{event.name}] {text}"
    if event.kind == "result":
        return f"[{number} R{' ERROR' if event.error else ''} {len(event.text)}c] {text}"
    return f"[{number} {TAGS[event.kind]}] {text}"


def show(args):
    session = sessions.resolve(args.session)
    summary = session.summary()
    rates = pricing.load()
    print(f"# {session.agent} {session.id} · {summary.cwd} · {summary.started} · {money(session_cost(rates, summary))}")
    if summary.title:
        print(f"# {summary.title}")
    limits = LIMITS["full" if args.full else "brief"]
    for number, event in enumerate(session.events(), 1):
        print(event_line(number, event, limits))


def day(summary):
    started = started_at(summary)
    return started.date() if started else None


def week(summary):
    date = day(summary)
    return date and date - timedelta(days=date.weekday())


GROUPS = {
    "model": lambda session, summary, model: model,
    "agent": lambda session, summary, model: session.agent,
    "cwd": lambda session, summary, model: home_relative(summary.cwd),
    "day": lambda session, summary, model: day(summary),
    "week": lambda session, summary, model: week(summary),
}


CHRONOLOGICAL = {"day", "week"}  # the other groupings list the costliest first


class Group:
    def __init__(self):
        self.sessions, self.tokens, self.usd, self.unpriced = set(), Tokens(), 0.0, set()

    def add(self, session, model, tokens, usd):
        self.sessions.add(session.path)
        self.tokens += tokens
        if usd is None:
            self.unpriced.add(model)
        else:
            self.usd += usd


def usage(args):
    rates, key, groups, total = pricing.load(), GROUPS[args.by], {}, Group()
    for session, summary in matching(args):
        for model, tokens in summary.tokens.items():
            usd = pricing.cost(rates, model, tokens)
            groups.setdefault(key(session, summary, model), Group()).add(session, model, tokens, usd)
            total.add(session, model, tokens, usd)
    width = max([40, *(len(str(name)) for name in groups)])  # names stay whole, so no two rows read alike
    print(f"{args.by:<{width}} {'sessions':>8} {'tokens':>9} {'output':>8} {'cost':>10}")
    order = (lambda item: str(item[0])) if args.by in CHRONOLOGICAL else (lambda item: -item[1].usd)
    for name, group in sorted(groups.items(), key=order):
        print(group_line(name, group, width))
    print(group_line("total", total, width))
    if total.unpriced:
        print(f"unpriced (no rate in {pricing.RATES}; ? has no price, + leaves some out): "
              f"{', '.join(sorted(total.unpriced))}")


def group_cost(group):
    priced = "$" + format(group.usd, ",.2f")
    if not group.unpriced:
        return priced
    return priced + "+" if group.usd else "?"


def group_line(name, group, width):
    return (f"{str(name):<{width}} {len(group.sessions):>8} {group.tokens.total / 1e6:>8.1f}M "
            f"{group.tokens.out / 1e3:>7.0f}k {group_cost(group):>10}")


def filters(parser):
    parser.add_argument("--since", type=since, default="7d", help="7d, 36h, or a date (default 7d)")
    parser.add_argument("--agent", choices=tuple(sessions.ROOTS))
    parser.add_argument("--cwd", help="text in the session's working directory")
    parser.add_argument("--prompt", type=pattern, help="regex for the session's first prompt or title")
    parser.add_argument("--grep", type=pattern, help="regex for any line of the transcript file")


def parser():
    root = argparse.ArgumentParser(prog="transcripts", description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = root.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="one line per session")
    filters(listing)
    listing.add_argument("--json", action="store_true", help="every field, tokens by model, and cost")
    listing.set_defaults(run=list_sessions)
    showing = commands.add_parser("show", help="the conversation, cut short")
    showing.add_argument("session", help="a transcript's path or the start of its id")
    showing.add_argument("--full", action="store_true", help="keep about three times as much of each message")
    showing.set_defaults(run=show)
    totals = commands.add_parser("usage", help="tokens and cost, grouped")
    filters(totals)
    totals.add_argument("--by", choices=tuple(GROUPS), default="model")
    totals.set_defaults(run=usage)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        args.run(args)
    except sessions.NotFound as error:
        sys.exit(f"transcripts: {error}")
    except BrokenPipeError:
        sys.stderr.close()  # `| head` closed the pipe; the rest of the output is not wanted


if __name__ == "__main__":
    main()
