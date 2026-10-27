"""The PR comment that reports a review loop: its rounds, findings and their outcomes, and coverage.

A loop run in passes (one ledger per pass, each a loop of its own) reports every pass in one comment:
the earlier passes first, the final pass last.
"""
from __future__ import annotations

from collections import Counter, namedtuple
from urllib.parse import quote

from loop_state import (COVERAGE, LoopError, all_findings, heads, location, outcomes, read_findings, reports, reviewers,
                        rounds)

COVERAGE_LABEL = {"incomplete": "Incomplete", "findings": "Findings above", "clean": "Clean",
                  "inapplicable": "Inapplicable"}
OUTCOME = {"fixed": "Fixed in `{commit}`", "declined": "Declined: {note}", "ruled": "Ruled: {note}",
           "decision": "Awaiting a decision: {note}", None: "Open"}
SUMMARY = {"fixed": "fixed", "declined": "declined", "ruled": "settled by a ruling",
           "decision": "awaiting a decision", None: "open"}

# One ledger's share of a PR's comment: [(round, Head)], its findings on the PR, and their outcomes.
Pass = namedtuple("Pass", "loop history found settled")


def cell(text):
    return str(text).replace("\n", " ").replace("|", "\\|")


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


def alert(unresolved, incomplete):
    if any(f["priority"] in ("P1", "P2") for f in unresolved):
        return "CAUTION"
    if unresolved:
        return "WARNING"
    return "IMPORTANT" if incomplete else "NOTE"


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
    gaps = f"incomplete ({', '.join(incomplete)})" if incomplete else "complete"
    return f"{result} Coverage: {gaps}."


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


def finding_rows(found, settled, final, repo):
    rows = ["| ID | Priority | Rule | Location | Finding | Outcome |", "| --- | --- | --- | --- | --- | --- |"]
    rows += [f"| {f['id']} | {f['priority']} {f['kind']} | {cell(f['rule'])} | {location_cell(f, final, repo)} "
             f"| {cell(f['title'])} | {cell(outcome_text(f, settled))} |" for f in found]
    return rows


def details(found, settled, heading):
    parts = ["<details><summary>Evidence and recommendations</summary>", ""]
    for f in found:
        parts += [f"{heading} {f['id']}: {f['title']}", "", f"{f['rule']} · `{location(f)}` · {outcome_text(f, settled)}",
                  "", "**Evidence**", "", f["evidence"], ""]
        if f.get("failure"):
            parts += [f"**Failure.** {f['failure']}", ""]
        parts += [f"**Recommendation.** {f['recommendation']}", ""]
    return parts + ["</details>"]


def coverage_rows(coverage):
    """A status per check, with the note only where coverage has a gap; every note goes in the details."""
    rows = ["| Check | Result |", "| --- | --- |"]
    for check_name, row in coverage.items():
        gap = f": {row['note']}" if row["status"] == "incomplete" and row.get("note") else ""
        rows.append(f"| {cell(check_name)} | {COVERAGE_LABEL[row['status']]}{cell(gap)} |")
    notes = [f"- **{name}**: {row['note']}" for name, row in coverage.items() if row.get("note")]
    return rows + (["", "<details><summary>Coverage notes</summary>", "", *notes, "", "</details>"] if notes else [])


def pr_history(loop, pr):
    """[(round, Head)] for each round that pinned this PR."""
    history = [(n, heads(loop, n)[pr]) for n in rounds(loop) if pr in heads(loop, n)]
    if not history:
        raise LoopError(f"PR {pr} is in no round's heads.tsv")
    return history


def models(passes, pr):
    return sorted({r.model for p in passes for m, _ in p.history for r in reviewers(p.loop, m) if pr in r.prs})


def headline(passes, pr, coverage, repo):
    final = passes[-1]
    n, head = final.history[-1]
    incomplete = [name for name, row in coverage.items() if row["status"] == "incomplete"]
    unresolved = [f for f, s in zip((f for p in passes for f in p.found), statuses(passes)) if s in (None, "decision")]
    return [f"<!-- review-loop {final.loop.name} r{n} {head.head} -->", "## Review loop", "",
            f"> [!{alert(unresolved, incomplete)}]", f"> {summary(passes, incomplete)}", "",
            f"Reviewed head [`{head.head[:9]}`](https://github.com/{repo}/commit/{head.head}) from fork point "
            f"`{head.fork[:9]}` · reviewers: {', '.join(models(passes, pr)) or 'none'}", ""]


def pass_section(p, pr, final, repo, heading):
    """One ledger's rounds and findings, under headings of the given level."""
    parts = [f"{heading} Rounds", "", *round_rows(p.loop, pr, p.history, p.found, p.settled), ""]
    if p.found:
        parts += [f"{heading} Findings", "", *finding_rows(p.found, p.settled, final, repo), "",
                  *details(p.found, p.settled, heading + "#"), ""]
    return parts


def load_pass(loop, pr):
    return Pass(loop, pr_history(loop, pr), [f for f in all_findings(loop) if str(f["pr"]) == pr], outcomes(loop))


def numbered_sections(passes, pr, repo):
    """Each pass under its own heading, named for its reviewers; only the final pass links locations."""
    parts = []
    for i, p in enumerate(passes, 1):
        final = p.history[-1] if i == len(passes) else None
        parts += [f"### Pass {i}: {', '.join(models([p], pr)) or 'no reviewers'}", "",
                  *pass_section(p, pr, final, repo, "####")]
    return parts


def render(loops, pr, repo):
    """The comment for PR over loops, oldest pass first; a single loop's comment has no pass headings."""
    passes = [load_pass(loop, pr) for loop in loops]
    coverage = merged_coverage(loops, pr)
    parts = headline(passes, pr, coverage, repo)
    if len(passes) == 1:
        parts += pass_section(passes[0], pr, passes[0].history[-1], repo, "###")
    else:
        parts += numbered_sections(passes, pr, repo)
    if coverage:
        parts += ["### Coverage", "", *coverage_rows(coverage), ""]
    return "\n".join(parts)
