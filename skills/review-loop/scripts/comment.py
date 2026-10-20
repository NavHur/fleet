"""The PR comment that reports a review loop: its rounds, findings and their outcomes, and coverage."""
from __future__ import annotations

import re
import subprocess
from collections import Counter
from urllib.parse import quote

from loop_state import (COVERAGE, LoopError, all_findings, heads, location, outcomes, read_findings, reports, reviewers,
                        rounds)

COVERAGE_LABEL = {"incomplete": "Incomplete", "findings": "Findings above", "clean": "Clean",
                  "inapplicable": "Inapplicable"}
OUTCOME = {"fixed": "Fixed in `{commit}`", "declined": "Declined: {note}", "ruled": "Ruled: {note}",
           "decision": "Awaiting a decision: {note}", None: "Open"}
SUMMARY = {"fixed": "fixed", "declined": "declined", "ruled": "settled by a ruling",
           "decision": "awaiting a decision", None: "open"}


def cell(text):
    return str(text).replace("\n", " ").replace("|", "\\|")


def github_repo(checkout):
    url = subprocess.run(["git", "-C", str(checkout), "remote", "get-url", "origin"],
                         capture_output=True, text=True, check=True).stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if not match:
        raise LoopError(f"origin is not a GitHub repository: {url}")
    return match.group(1)


def status(finding, settled):
    return (settled.get(finding["id"]) or {}).get("status")


def outcome_text(finding, settled):
    record = settled.get(finding["id"]) or {}
    return OUTCOME[record.get("status")].format(commit=(record.get("commit") or "")[:9], note=record.get("note"))


def location_cell(finding, final, repo):
    """Links only findings from the final round: earlier heads may never reach GitHub."""
    text = location(finding)
    if text == "-" or finding["round"] != final[0]:
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


def merged_coverage(loop, pr):
    merged = {}
    for row in coverage_entries(loop, pr):
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


def summary(found, settled, incomplete, history):
    counts = Counter(status(f, settled) for f in found)
    parts = [f"{counts[key]} {label}" for key, label in SUMMARY.items() if counts[key]]
    result = f"{plural(len(found), 'finding')} over {plural(len(history), 'round')}"
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


def details(found, settled):
    parts = ["<details><summary>Evidence and recommendations</summary>", ""]
    for f in found:
        parts += [f"#### {f['id']}: {f['title']}", "", f"{f['rule']} · `{location(f)}` · {outcome_text(f, settled)}",
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


def headline(loop, pr, history, found, settled, coverage, repo):
    n, head = history[-1]
    models = sorted({r.model for m, _ in history for r in reviewers(loop, m) if pr in r.prs})
    incomplete = [name for name, row in coverage.items() if row["status"] == "incomplete"]
    unresolved = [f for f in found if status(f, settled) in (None, "decision")]
    return [f"<!-- review-loop {loop.name} r{n} {head.head} -->", "## Review loop", "",
            f"> [!{alert(unresolved, incomplete)}]", f"> {summary(found, settled, incomplete, history)}", "",
            f"Reviewed head [`{head.head[:9]}`](https://github.com/{repo}/commit/{head.head}) on base "
            f"`{head.base[:9]}` · reviewers: {', '.join(models) or 'none'}", ""]


def render(loop, pr, repo):
    history, settled = pr_history(loop, pr), outcomes(loop)
    found = [f for f in all_findings(loop) if str(f["pr"]) == pr]
    coverage = merged_coverage(loop, pr)
    parts = [*headline(loop, pr, history, found, settled, coverage, repo),
             "### Rounds", "", *round_rows(loop, pr, history, found, settled), ""]
    if found:
        final = history[-1]
        parts += ["### Findings", "", *finding_rows(found, settled, final, repo), "", *details(found, settled), ""]
    if coverage:
        parts += ["### Coverage", "", *coverage_rows(coverage), ""]
    return "\n".join(parts)
