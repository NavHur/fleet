"""A review loop's state on disk: rounds and their heads, registered reviewers, findings files, and outcomes."""
from __future__ import annotations

import json
import re
from collections import namedtuple

ROLES = {"standards": "STD", "spec": "SPEC", "delta": "DELTA", "audit": "PBP"}
# Worst first: a check's merged status across rounds is the worst one reported.
COVERAGE = ("incomplete", "findings", "clean", "inapplicable")

Head = namedtuple("Head", "layer base head")
Reviewer = namedtuple("Reviewer", "name role scope prs model")


class LoopError(Exception):
    pass


def round_dir(loop, n):
    return loop / f"r{n}"


def rounds(loop):
    found = (re.fullmatch(r"r(\d+)", d.name) for d in loop.iterdir() if (d / "heads.tsv").exists())
    return sorted(int(m.group(1)) for m in found if m)


def heads(loop, n):
    """{pr: Head}, bottom to top."""
    path = round_dir(loop, n) / "heads.tsv"
    if not path.exists():
        raise LoopError(f"{path} does not exist")
    rows = {}
    for line in path.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            pr, layer, base, head = line.split("\t")
            rows[pr] = Head(layer, base, head)
    return rows


def reviewers(loop, n):
    path = round_dir(loop, n) / "reviewers.tsv"
    if not path.exists():
        return []
    rows = (line.split("\t") for line in path.read_text().splitlines() if line.strip())
    return [Reviewer(name, role, scope, prs.split(","), model) for name, role, scope, prs, model in rows]


def register(loop, n, reviewer):
    others = [r for r in reviewers(loop, n) if r.name != reviewer.name]
    lines = ["\t".join((r.name, r.role, r.scope, ",".join(r.prs), r.model)) for r in [*others, reviewer]]
    (round_dir(loop, n) / "reviewers.tsv").write_text("\n".join(lines) + "\n")


def id_prefix(n, reviewer):
    pr = reviewer.prs[0] if reviewer.role == "audit" else ""
    return f"R{n}-{ROLES[reviewer.role]}{pr}-"


def findings_path(loop, n, reviewer):
    return round_dir(loop, n) / f"{reviewer.name}.json"


def read_findings(path):
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise ValueError('the file must be an object with a "findings" list')
    return data


def location(finding):
    path = finding.get("file")
    if not path:
        return "-"
    return f"{path}:{finding['line']}" if finding.get("line") else path


def reports(loop):
    """(round, reviewer, findings file) for every file written so far, oldest round first."""
    for n in rounds(loop):
        for reviewer in reviewers(loop, n):
            path = findings_path(loop, n, reviewer)
            if path.exists():
                yield n, reviewer, path


def all_findings(loop):
    return [dict(f, round=n) for n, _, path in reports(loop) for f in read_findings(path)["findings"]]


def outcomes(loop):
    path = loop / "outcomes.jsonl"
    if not path.exists():
        return {}
    records = (json.loads(line) for line in path.read_text().splitlines() if line.strip())
    return {record["id"]: record for record in records}
