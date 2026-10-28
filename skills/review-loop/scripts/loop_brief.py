"""loop.py brief: one reviewer's task, and rN/context.md, the file every reviewer in the round reads first."""
from __future__ import annotations

from pathlib import Path

from loop_state import (LoopError, Reviewer, all_findings, findings_path, heads, id_prefix, location, outcomes,
                        pr_file_key, register, reviewers, round_dir)

SKILL_DIR = Path(__file__).resolve().parent.parent


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
    name = role if prs == current and role != "audit" else f"{role}-{'+'.join(map(pr_file_key, prs))}"
    return Reviewer(name, role, "delta" if role == "delta" or delta else "whole", prs, model)


def scope_line(loop, n, pr, reviewer):
    head = heads(loop, n)[pr]
    if reviewer.scope == "whole":
        return f"- PR {pr} ({head.layer}): the whole change, `git diff {head.fork} {head.head}`."
    previous = heads(loop, n - 1).get(pr) if n > 1 else None
    diff = round_dir(loop, n) / f"delta-{pr_file_key(pr)}.diff"
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
