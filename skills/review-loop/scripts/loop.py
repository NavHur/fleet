#!/usr/bin/env python3
"""Reviewer briefs, findings checks, outcomes, and the PR comment for a review loop.

  loop.py brief LOOP ROUND ROLE --model TEXT [--pr PR ...] [--delta] [--checkout DIR]
  loop.py check LOOP ROUND [--only NAME] [--checkout DIR]
  loop.py outcome LOOP ID STATUS [--commit SHA] [--note TEXT]
  loop.py render LOOP PR --checkout DIR [--earlier LOOP ...]
  loop.py publish LOOP --checkout DIR [--earlier LOOP ...] [--dry-run]

LOOP is the loop's directory (~/.cache/review-loop/<slug>) and ROUND a round
number; round N lives in LOOP/rN with its heads.tsv
(PR<TAB>LAYER<TAB>FORK<TAB>HEAD, bottom to top).

brief prints the task for one reviewer (ROLE is standards, spec, delta, or
audit), registers it in rN/reviewers.tsv, and rewrites rN/context.md, the one
file every reviewer in the round reads first: reviewer.md, LOOP/common.md (the
pass's packet), the ledger, the round's heads and reviewers, the rulings from
this pass and the earlier passes (LOOP named <slug>-p2 finds <slug>-p1), and the
settled findings. The reviewer writes rN/<name>.json in the format reviewer.md
describes. check validates every registered reviewer's file and prints the
round's findings, marking each one near an earlier round's fix. outcome appends a
finding's triage result (fixed, declined, decision, or ruled) to
LOOP/outcomes.jsonl; the last record for an ID wins. render prints one PR's
comment, and publish posts it on every PR whose GitHub head is the head the
last round reviewed, once per round. --earlier names an earlier pass's loop
(oldest first): its rounds and findings join the same comment, ahead of LOOP's.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR.parent / "split-stacked-prs" / "scripts"))

from comment import render  # noqa: E402
from loop_brief import brief  # noqa: E402
from stack_layers import GitHub, StackError  # noqa: E402
from loop_state import (COVERAGE, ROLES, LoopError, all_findings, findings_path, heads, id_prefix, location, outcomes,
                        read_findings, reviewers, rounds)  # noqa: E402

PRIORITIES = ("P1", "P2", "P3")
KINDS = ("bug", "violation", "advisory", "opportunity")
STATUSES = ("fixed", "declined", "decision", "ruled")
REQUIRED = ("id", "pr", "priority", "kind", "rule", "title", "evidence", "recommendation")
# How close, in lines, a new finding sits to an earlier round's fix for check to mark it as a possible regression.
NEAR_LINES = 20


# check


def git_show(checkout, revision, path):
    result = subprocess.run(["git", "-C", str(checkout), "show", f"{revision}:{path}"],
                            capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def shape_problem(path, line):
    if line is None:
        return None
    if not isinstance(line, int) or isinstance(line, bool) or line < 1:
        return f"line must be a positive integer or null, not {line!r}"
    return None if path else "a line needs a file"


def location_problem(finding, head, checkout):
    path, line = finding.get("file"), finding.get("line")
    problem = shape_problem(path, line)
    if problem or not path or checkout is None:
        return problem
    text = git_show(checkout, head, path)
    if text is None:
        return f"{path} does not exist at {head[:9]}"
    if line is not None and line > len(text.splitlines()):
        return f"line {line} is past the end of {path} at {head[:9]}"
    return None


def finding_problems(finding, reviewer, prefix, current, checkout):
    problems = [f"missing {key}" for key in REQUIRED if finding.get(key) in (None, "")]
    if not str(finding.get("id", "")).startswith(prefix):
        problems.append(f"id must start with {prefix}")
    if finding.get("priority") not in PRIORITIES:
        problems.append(f"priority must be one of {', '.join(PRIORITIES)}")
    if finding.get("kind") not in KINDS:
        problems.append(f"kind must be one of {', '.join(KINDS)}")
    if not isinstance(finding.get("decision", False), bool):
        problems.append("decision must be true or false")
    pr = str(finding.get("pr"))
    if pr not in reviewer.prs:
        problems.append(f"pr must be one of {', '.join(reviewer.prs)}")
        return problems
    problem = location_problem(finding, current[pr].head, checkout)
    return problems + ([problem] if problem else [])


def coverage_problems(data, reviewer):
    rows = data.get("coverage") or []
    if not isinstance(rows, list):
        return ["coverage must be a list"]
    if not rows and reviewer.role == "audit":
        return ["an audit needs a coverage entry for every check"]
    return [f"coverage {i + 1}: needs a check and a status from {', '.join(COVERAGE)}"
            for i, row in enumerate(rows)
            if not isinstance(row, dict) or not row.get("check") or row.get("status") not in COVERAGE]


def reviewer_problems(loop, n, reviewer, checkout):
    path = findings_path(loop, n, reviewer)
    if not path.exists():
        return [f"{path.name} has not been written"]
    try:
        data = read_findings(path)
    except ValueError as error:
        return [f"{path.name}: {error}"]
    prefix, current = id_prefix(n, reviewer), heads(loop, n)
    problems = coverage_problems(data, reviewer)
    ids = Counter(str(f.get("id")) for f in data["findings"] if isinstance(f, dict))
    problems += [f"{i} is used {count} times" for i, count in ids.items() if count > 1]
    for index, finding in enumerate(data["findings"]):
        if not isinstance(finding, dict):
            problems.append(f"finding {index + 1} is not an object")
            continue
        label = finding.get("id") or f"finding {index + 1}"
        problems += [f"{label}: {p}" for p in finding_problems(finding, reviewer, prefix, current, checkout)]
    return problems


def fixed_findings(loop, n):
    recorded = outcomes(loop)
    return [f for f in all_findings(loop) if f["round"] < n and recorded.get(f["id"], {}).get("status") == "fixed"]


def near(finding, fixed):
    """The earlier fixes in the finding's file within NEAR_LINES lines of it, which it may be a regression of."""
    path, line = finding.get("file"), finding.get("line")
    if not path:
        return []
    same_file = [f for f in fixed if str(f["pr"]) == str(finding["pr"]) and f.get("file") == path]
    return [f["id"] for f in same_file if line is None or f.get("line") is None or abs(f["line"] - line) <= NEAR_LINES]


def finding_line(f, fixed):
    line = f"{f['id']}  {f['priority']} {f['kind']}  PR {f['pr']}  {location(f)}  {f['title']}"
    earlier = near(f, fixed)
    return line + (f"\n  near fixed {', '.join(earlier)}" if earlier else "")


def status_lines(name, problems):
    return [f"{name}: {'FAIL' if problems else 'ok'}", *(f"  {p}" for p in problems)]


def check(loop, n, only, checkout):
    registered = [r for r in reviewers(loop, n) if only in (None, r.name)]
    if not registered:
        raise LoopError(f"r{n}/reviewers.tsv has no reviewer {only or ''}".rstrip())
    results = {r.name: reviewer_problems(loop, n, r, checkout) for r in registered}
    lines = [line for name, problems in results.items() for line in status_lines(name, problems)]
    passed = [r for r in registered if not results[r.name]]
    found = [f for r in passed for f in read_findings(findings_path(loop, n, r))["findings"]]
    lines.append(f"{len(found)} findings from {len(passed)} of {len(registered)} reviewers")
    fixed = fixed_findings(loop, n)
    lines += [finding_line(f, fixed) for f in found]
    return len(passed) < len(registered), "\n".join(lines)


# outcome


def record_outcome(loop, finding_id, status, commit, note):
    if finding_id not in {f["id"] for f in all_findings(loop)}:
        raise LoopError(f"no finding {finding_id} in this loop")
    if status == "fixed" and not commit:
        raise LoopError("a fixed finding needs --commit")
    if status != "fixed" and not note:
        raise LoopError(f"a {status} finding needs --note")
    record = {"id": finding_id, "status": status, "commit": commit, "note": note,
              "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with (loop / "outcomes.jsonl").open("a") as log:
        log.write(json.dumps(record) + "\n")


# publish


def publish_pr(loops, github, pr, head, dry_run):
    remote = github.pr(int(pr)).head
    if remote != head:
        return (f"PR {pr}: GitHub has {remote[:9]} but the loop reviewed {head[:9]}; not posted. "
                "Run publish again once the reviewed head is pushed.")
    body = render(loops, pr, github.slug)
    marker = body.splitlines()[0]
    query = f".[] | select(.body | startswith({json.dumps(marker)})) | .html_url"
    posted = github.api(f"issues/{pr}/comments", "--paginate", "--jq", query)
    if posted:
        return f"PR {pr}: already posted, {posted.splitlines()[0]}"
    if dry_run:
        return f"PR {pr}: would post\n{body}"
    return f"PR {pr}: posted {post_comment(github, pr, body)}"


def post_comment(github, pr, body):
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as handle:
        handle.write(body)
    try:
        return github.api(f"issues/{pr}/comments", "-X", "POST", "-F", f"body=@{handle.name}", "--jq", ".html_url")
    finally:
        os.unlink(handle.name)


def publish(loops, checkout, dry_run):
    """Posts on the PRs of the final loop's last round; loops runs oldest pass first."""
    github, n = GitHub.from_origin(root=checkout), rounds(loops[-1])[-1]
    for pr, head in heads(loops[-1], n).items():
        if pr.isdigit():
            print(publish_pr(loops, github, pr, head.head, dry_run))
        else:
            print(f"{pr}: no PR number in r{n}/heads.tsv; not posted")


EARLIER = "an earlier pass's loop on the same PRs, reported first in the same comment; repeatable, oldest first"


def parser():
    root = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = root.add_subparsers(dest="command", required=True)
    cmd = commands.add_parser("brief")
    cmd.add_argument("loop", type=Path)
    cmd.add_argument("round", type=int)
    cmd.add_argument("role", choices=list(ROLES))
    cmd.add_argument("--model", required=True, help='the reviewer model and effort, e.g. "gpt-6.1-sol high"')
    cmd.add_argument("--pr", action="append", default=[], help="a PR from heads.tsv; repeatable (default: all)")
    cmd.add_argument("--delta", action="store_true", help="an audit of the round's delta instead of the whole PR")
    cmd.add_argument("--checkout", type=Path)
    cmd = commands.add_parser("check")
    cmd.add_argument("loop", type=Path)
    cmd.add_argument("round", type=int)
    cmd.add_argument("--only")
    cmd.add_argument("--checkout", type=Path)
    cmd = commands.add_parser("outcome")
    cmd.add_argument("loop", type=Path)
    cmd.add_argument("id")
    cmd.add_argument("status", choices=STATUSES)
    cmd.add_argument("--commit")
    cmd.add_argument("--note")
    cmd = commands.add_parser("render")
    cmd.add_argument("loop", type=Path)
    cmd.add_argument("pr")
    cmd.add_argument("--checkout", type=Path, required=True)
    cmd.add_argument("--earlier", type=Path, action="append", default=[], help=EARLIER)
    cmd = commands.add_parser("publish")
    cmd.add_argument("loop", type=Path)
    cmd.add_argument("--checkout", type=Path, required=True)
    cmd.add_argument("--earlier", type=Path, action="append", default=[], help=EARLIER)
    cmd.add_argument("--dry-run", action="store_true")
    return root


def passes(args):
    """The loops a comment reports, oldest pass first and args.loop last."""
    return [path.expanduser().resolve() for path in (*args.earlier, args.loop)]


def run(args):
    loop = args.loop.expanduser().resolve()
    if args.command == "brief":
        print(brief(loop, args.round, args.role, args.pr, args.delta, args.model, args.checkout))
    elif args.command == "check":
        failed, report = check(loop, args.round, args.only, args.checkout)
        print(report)
        return 1 if failed else 0
    elif args.command == "outcome":
        record_outcome(loop, args.id, args.status, args.commit, args.note)
    elif args.command == "render":
        print(render(passes(args), args.pr, GitHub.from_origin(root=args.checkout).slug))
    else:
        publish(passes(args), args.checkout, args.dry_run)
    return 0


def main(argv):
    try:
        return run(parser().parse_args(argv))
    except (LoopError, StackError) as error:
        print(f"loop.py: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
