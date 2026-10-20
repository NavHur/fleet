#!/usr/bin/env python3
"""Reviewer briefs, findings checks, outcomes, and the PR comment for a review loop.

  loop.py brief LOOP ROUND ROLE --model TEXT [--pr PR ...] [--delta] [--checkout DIR]
  loop.py check LOOP ROUND [--only NAME] [--checkout DIR]
  loop.py outcome LOOP ID STATUS [--commit SHA] [--note TEXT]
  loop.py render LOOP PR --checkout DIR
  loop.py publish LOOP --checkout DIR [--dry-run]

LOOP is the loop's directory (~/.cache/review-loop/<slug>) and ROUND a round
number; round N lives in LOOP/rN with its heads.tsv
(PR<TAB>LAYER<TAB>BASE_SHA<TAB>HEAD_SHA, bottom to top).

brief prints the task for one reviewer (ROLE is standards, spec, delta, or
audit), registers it in rN/reviewers.tsv, and rewrites rN/context.md: reviewer.md,
rN/common.md, the ledger, the round's reviewers, and the settled findings, the one
file every reviewer in the round reads first. The reviewer writes
rN/<name>.json in the format reviewer.md describes. check validates every
registered reviewer's file and prints the round's findings. outcome appends a
finding's triage result (fixed, declined, decision, or ruled) to
LOOP/outcomes.jsonl; the last record for an ID wins. render prints one PR's
comment, and publish posts it on every PR whose GitHub head is the head the
last round reviewed, once per round.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from comment import github_repo, render
from loop_state import (COVERAGE, ROLES, LoopError, Reviewer, all_findings, findings_path, heads, id_prefix, location,
                        outcomes, read_findings, register, reviewers, round_dir, rounds)

SKILL_DIR = Path(__file__).resolve().parent.parent
PRIORITIES = ("P1", "P2", "P3")
KINDS = ("bug", "violation", "advisory", "opportunity")
STATUSES = ("fixed", "declined", "decision", "ruled")
REQUIRED = ("id", "pr", "priority", "kind", "rule", "title", "evidence", "recommendation")


# brief


BRIEF = """\
You are the {role} reviewer in round {n} of a review loop.

Read {context} in full before anything else. It holds your rules, the method for the {role} role, and the
output format (reviewer.md), the round packet, this round's reviewers, the ledger, and the settled findings.
Then read every file your role names in one turn, and keep batching independent reads and commands into one
turn throughout.

Your scope:
{scope}

Write your findings to {out}, numbering their IDs {prefix}1, {prefix}2, and so on. Then run
`python3 {skill}/scripts/loop.py check {loop} {n} --only {name}{checkout}`
and correct the file until it passes. Finish with one line: your finding counts by priority and the file path.
"""


def new_reviewer(loop, n, role, prs, delta, model):
    current = list(heads(loop, n))
    prs = prs or current
    if not set(prs) <= set(current):
        raise LoopError(f"r{n}/heads.tsv has PRs {', '.join(current)}, not {', '.join(prs)}")
    if role == "audit" and len(prs) != 1:
        raise LoopError("an audit covers one PR; pass --pr")
    # Audits are per PR; the other roles are named for a subset only.
    name = role if prs == current and role != "audit" else f"{role}-{'-'.join(prs)}"
    return Reviewer(name, role, "delta" if role == "delta" or delta else "whole", prs, model)


def scope_line(loop, n, pr, reviewer):
    head = heads(loop, n)[pr]
    if reviewer.scope == "whole":
        return f"- PR {pr} ({head.layer}): the whole change, `git diff {head.base} {head.head}`."
    previous = heads(loop, n - 1).get(pr) if n > 1 else None
    diff = round_dir(loop, n) / f"delta-{pr}.diff"
    if previous is None or not diff.exists():
        raise LoopError(f"PR {pr} has no delta in r{n}; review it whole or skip it")
    return f"- PR {pr} ({head.layer}): the fixes since round {n - 1}, in `{diff}` ({previous.head} to {head.head})."


CONTEXT = """\
# Review loop, round {n}: shared context

Every reviewer in round {n} reads this file first. `loop.py brief` assembles it from the files it quotes;
edit those, not this.

{files}

## Reviewers this round

{reviewers}

## Settled findings

The last outcome of every finding from earlier rounds; a round's `<reviewer>.json` holds the full record.
A finding fixed in the previous round carries the recommendation its fix answers.

{settled}
"""


def quoted_file(path):
    if not path.exists():
        raise LoopError(f"write {path} before the briefs")
    return f'<file path="{path}">\n{path.read_text().strip()}\n</file>'


def settled_line(finding, outcome, previous):
    status = outcome["status"]
    result = f"fixed in {outcome['commit'][:9]}" if status == "fixed" else f"{status}: {outcome['note']}"
    line = (f"- {finding['id']} ({finding['priority']} {finding['kind']}, PR {finding['pr']}, {location(finding)}) "
            f"{result}. {finding['title']}")
    if status == "fixed" and finding["round"] == previous:
        line += f"\n  Recommendation: {finding['recommendation']}"
    return line


def settled_lines(loop, n):
    recorded = outcomes(loop)
    earlier = [f for f in all_findings(loop) if f["round"] < n and f["id"] in recorded]
    return [settled_line(f, recorded[f["id"]], n - 1) for f in earlier] or ["None yet."]


def quoted_files(loop, n):
    paths = (SKILL_DIR / "reviewer.md", round_dir(loop, n) / "common.md", loop / "ledger.md")
    return "\n\n".join(quoted_file(path) for path in paths)


def write_context(loop, n, files):
    """Write rN/context.md, the one file every reviewer in round n reads before its role's own files."""
    roster = [f"- {r.name}: {r.role}, {r.scope}, PR {', '.join(r.prs)}" for r in reviewers(loop, n)]
    text = CONTEXT.format(n=n, files=files, reviewers="\n".join(roster), settled="\n".join(settled_lines(loop, n)))
    path = round_dir(loop, n) / "context.md"
    path.write_text(text)
    return path


def brief(loop, n, role, prs, delta, model, checkout):
    reviewer = new_reviewer(loop, n, role, prs, delta, model)
    scope = "\n".join(scope_line(loop, n, pr, reviewer) for pr in reviewer.prs)
    files = quoted_files(loop, n)
    register(loop, n, reviewer)
    (loop / "outcomes.jsonl").touch()
    context = write_context(loop, n, files)
    return BRIEF.format(role=role, n=n, context=context, scope=scope, skill=SKILL_DIR, loop=loop,
                        out=findings_path(loop, n, reviewer), prefix=id_prefix(n, reviewer), name=reviewer.name,
                        checkout=f" --checkout {checkout}" if checkout else "")


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
    rows = data.get("coverage")
    if rows is None and reviewer.role != "audit":
        return []
    if not isinstance(rows, list) or not rows:
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
    lines += [f"{f['id']}  {f['priority']} {f['kind']}  PR {f['pr']}  {location(f)}  {f['title']}" for f in found]
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


def gh(checkout, *args):
    return subprocess.run(["gh", *args], cwd=checkout, capture_output=True, text=True, check=True).stdout.strip()


def publish_pr(loop, checkout, repo, pr, head, dry_run):
    remote = gh(checkout, "pr", "view", pr, "--repo", repo, "--json", "headRefOid", "--jq", ".headRefOid")
    if remote != head:
        return (f"PR {pr}: GitHub has {remote[:9]} but the loop reviewed {head[:9]}; not posted. "
                "Run publish again once the reviewed head is pushed.")
    body = render(loop, pr, repo)
    marker = body.splitlines()[0]
    query = f".[] | select(.body | startswith({json.dumps(marker)})) | .html_url"
    posted = gh(checkout, "api", f"repos/{repo}/issues/{pr}/comments", "--paginate", "--jq", query)
    if posted:
        return f"PR {pr}: already posted, {posted.splitlines()[0]}"
    if dry_run:
        return f"PR {pr}: would post\n{body}"
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as handle:
        handle.write(body)
    return f"PR {pr}: posted {gh(checkout, 'pr', 'comment', pr, '--repo', repo, '--body-file', handle.name)}"


def publish(loop, checkout, dry_run):
    repo, n = github_repo(checkout), rounds(loop)[-1]
    for pr, head in heads(loop, n).items():
        if pr.isdigit():
            print(publish_pr(loop, checkout, repo, pr, head.head, dry_run))
        else:
            print(f"{pr}: no PR number in r{n}/heads.tsv; not posted")


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
    cmd = commands.add_parser("publish")
    cmd.add_argument("loop", type=Path)
    cmd.add_argument("--checkout", type=Path, required=True)
    cmd.add_argument("--dry-run", action="store_true")
    return root


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
        print(render(loop, args.pr, github_repo(args.checkout)))
    else:
        publish(loop, args.checkout, args.dry_run)
    return 0


def main(argv):
    try:
        return run(parser().parse_args(argv))
    except LoopError as error:
        print(f"loop.py: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
