"""The PR comment that reports a review loop: its rounds, findings and their outcomes, and coverage.

A loop run in passes (one ledger per pass, each a loop of its own) reports every pass in one comment:
the earlier passes first, the final pass last. The comment is a record, not a request: whatever needs the user
reaches them in the T3 thread before it is posted, so publish refuses a PR with a finding still open or awaiting
a decision. A one-line summary leads; each pass's rounds and findings, and the coverage table, sit in collapsed
sections below.
"""
from __future__ import annotations

from collections import Counter, namedtuple
from urllib.parse import quote

from loop_state import (COVERAGE, LoopError, all_findings, heads, location, outcomes, read_findings, reports, reviewers,
                        rounds)

COVERAGE_LABEL = {"incomplete": "Incomplete", "findings": "Findings", "clean": "Clean",
                  "inapplicable": "Inapplicable"}
OUTCOME = {"fixed": "Fixed in `{commit}`", "declined": "Declined: {note}", "ruled": "Ruled: {note}",
           "decision": "Awaiting a decision: {note}", None: "Open"}
SUMMARY = {"fixed": "fixed", "declined": "declined", "ruled": "settled by a ruling",
           "decision": "awaiting a decision", None: "open"}
# Outcomes that still need the user: a published comment has none.
UNSETTLED = (None, "decision")

# One ledger's share of a PR's comment: [(round, Head)], its findings on the PR, and their outcomes.
Pass = namedtuple("Pass", "loop history found settled")


def cell(text):
    return one_line(text).replace("|", "\\|")


def one_line(text):
    return str(text).replace("\n", " ")


def status(finding, settled):
    return (settled.get(finding["id"]) or {}).get("status")


def outcome_text(finding, settled):
    record = settled.get(finding["id"]) or {}
    return OUTCOME[record.get("status")].format(commit=(record.get("commit") or "")[:9], note=record.get("note"))


def location_cell(finding, final, repo):
    """Links only findings from the final pass's last round (final is None in earlier passes): earlier heads may
    never reach GitHub."""
    text = location(finding)
    if text == "-" or final is None or finding["round"] != final[0]:
        return f"`{text}`" if text != "-" else text
    anchor = f"#L{finding['line']}" if finding.get("line") else ""
    return f"[`{text}`](https://github.com/{repo}/blob/{final[1].head}/{quote(finding['file'])}{anchor})"


def coverage_entries(loop, pr):
    """The audits' checks, and the gaps the other reviewers report, under their role's name."""
    for _, reviewer, path in reports(loop):
        rows = read_findings(path).get("coverage") or [] if pr in reviewer.prs else []
        if reviewer.role == "audit":
            yield from rows
        else:
            yield from (dict(row, check=f"{reviewer.role.title()}: {row['check']}")
                        for row in rows if row["status"] == "incomplete")


def merged_coverage(loops, pr):
    merged = {}
    for row in (row for loop in loops for row in coverage_entries(loop, pr)):
        kept = merged.get(row["check"], row)
        if COVERAGE.index(row["status"]) <= COVERAGE.index(kept["status"]):
            merged[row["check"]] = row
    return merged


def gaps(coverage):
    return {name: row for name, row in coverage.items() if row["status"] == "incomplete"}


def plural(count, noun):
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def statuses(passes):
    return [status(f, p.settled) for p in passes for f in p.found]


def summary(passes, incomplete):
    counts = Counter(statuses(passes))
    parts = [f"{counts[key]} {label}" for key, label in SUMMARY.items() if counts[key]]
    result = f"{plural(sum(counts.values()), 'finding')} over {plural(sum(len(p.history) for p in passes), 'round')}"
    result += f" in {len(passes)} passes" if len(passes) > 1 else ""
    result += f": {', '.join(parts)}." if parts else "."
    coverage = plural(len(incomplete), "gap") if incomplete else "complete"
    return f"{result} Coverage: {coverage}."


def round_rows(loop, pr, history, found, settled):
    rows = ["| Round | Review | Head | Findings | Fixed |", "| --- | --- | --- | ---: | ---: |"]
    for n, head in history:
        covering = [r for r in reviewers(loop, n) if pr in r.prs]
        scope = "whole" if any(r.scope == "whole" for r in covering) else "delta"
        review = f"{scope}: {', '.join(r.role for r in covering)}" if covering else "skipped, no changes"
        raised = [f for f in found if f["round"] == n]
        fixed = sum(status(f, settled) == "fixed" for f in raised)
        rows.append(f"| r{n} | {review} | `{head.head[:9]}` | {len(raised)} | {fixed} |")
    return rows


def finding_item(f, settled, final, repo):
    """A list item, not a table row: titles and notes run long, and a list wraps where a table scrolls."""
    return [f"- {f['priority']} {f['kind']}: **{one_line(f['title'])}** {one_line(outcome_text(f, settled))}\\",
            f"  `{f['id']}` · {one_line(f['rule'])} · {location_cell(f, final, repo)}"]


def evidence(found, settled):
    parts = []
    for f in found:
        parts += [f"#### {f['id']}: {f['title']}", "", f"{f['rule']} · `{location(f)}` · {outcome_text(f, settled)}",
                  "", "**Evidence**", "", f["evidence"], ""]
        if f.get("failure"):
            parts += [f"**Failure.** {f['failure']}", ""]
        parts += [f"**Recommendation.** {f['recommendation']}", ""]
    return parts


def pr_history(loop, pr):
    """[(round, Head)] for each round that pinned this PR."""
    history = [(n, heads(loop, n)[pr]) for n in rounds(loop) if pr in heads(loop, n)]
    if not history:
        raise LoopError(f"PR {pr} is in no round's heads.tsv")
    return history


def models(passes, pr):
    return sorted({r.model for p in passes for m, _ in p.history for r in reviewers(p.loop, m) if pr in r.prs})


def final_head(passes, i):
    """The (round, Head) whose locations link: the final pass's last round, None in earlier passes."""
    return passes[i].history[-1] if i == len(passes) - 1 else None


def headline(passes, pr, coverage, repo):
    final = passes[-1]
    n, head = final.history[-1]
    return [f"<!-- review-loop {final.loop.name} r{n} {head.head} -->", "## Review loop", "",
            "> [!NOTE]", f"> {summary(passes, gaps(coverage))}", "",
            f"Reviewed head [`{head.head[:9]}`](https://github.com/{repo}/commit/{head.head}) from fork point "
            f"`{head.fork[:9]}` · reviewers: {', '.join(models(passes, pr)) or 'none'}", ""]


def tally(p):
    fixed = sum(status(f, p.settled) == "fixed" for f in p.found)
    found = f"{plural(len(p.found), 'finding')}, {fixed} fixed" if p.found else "no findings"
    return f"{plural(len(p.history), 'round')}, {found}"


def pass_section(p, pr, final, repo, title):
    """One ledger's rounds, findings, and evidence, collapsed under a summary that tallies them."""
    parts = [f"<details><summary>{title}: {tally(p)}</summary>", "",
             *round_rows(p.loop, pr, p.history, p.found, p.settled), ""]
    if p.found:
        parts += [line for f in p.found for line in finding_item(f, p.settled, final, repo)]
        parts += ["", *evidence(p.found, p.settled)]
    return parts + ["</details>", ""]


def coverage_section(coverage):
    """Every check with its result and note, gaps first."""
    ordered = sorted(coverage.items(), key=lambda item: item[1]["status"] != "incomplete")
    rows = ["| Check | Result | Note |", "| --- | --- | --- |"]
    rows += [f"| {cell(name)} | {COVERAGE_LABEL[row['status']]} | {cell(row.get('note') or '')} |"
             for name, row in ordered]
    title = f"Coverage: {plural(len(coverage), 'check')}, {plural(len(gaps(coverage)), 'gap')}"
    return [f"<details><summary>{title}</summary>", "", *rows, "", "</details>", ""]


def load_pass(loop, pr):
    return Pass(loop, pr_history(loop, pr), [f for f in all_findings(loop) if str(f["pr"]) == pr], outcomes(loop))


def unsettled(loops, pr):
    """The IDs of PR's findings still open or awaiting a decision, each marked with its pass: IDs restart in each."""
    passes = [load_pass(loop, pr) for loop in loops]
    return [f"pass {i + 1} {f['id']}" if len(passes) > 1 else f["id"]
            for i, p in enumerate(passes) for f in p.found if status(f, p.settled) in UNSETTLED]


def pass_title(passes, i, pr):
    if len(passes) == 1:
        return "Rounds and findings"
    return f"Pass {i + 1}, {', '.join(models([passes[i]], pr)) or 'no reviewers'}"


def render(loops, pr, repo):
    """The comment for PR over loops, oldest pass first."""
    passes = [load_pass(loop, pr) for loop in loops]
    coverage = merged_coverage(loops, pr)
    parts = headline(passes, pr, coverage, repo)
    for i, p in enumerate(passes):
        parts += pass_section(p, pr, final_head(passes, i), repo, pass_title(passes, i, pr))
    if coverage:
        parts += coverage_section(coverage)
    return "\n".join(parts)
