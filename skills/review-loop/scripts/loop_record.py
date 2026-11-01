"""loop.py start and finish: a pass's run record, the spec its reviewers read, and what its sessions cost.

start writes LOOP/run.json (repo, host, orchestrator, start time) and saves the spec into LOOP/spec/, so a
later replay reads the spec as it stood. finish writes LOOP/usage.json, the cost of every session this pass
ran, from this machine's transcripts while they still exist, and stamps run.json finished.
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from loop_state import LoopError, heads

ORCHESTRATOR = "You are the orchestrator of a review loop"
REVIEWER = re.compile(r"You are the \S+ reviewer in round \d+ of a review loop")
PASS = re.compile(r"^Pass: (\d+)", re.MULTILINE)
LOOP_NAME = re.compile(r"(.+)-p(\d+)")
# Without a start time, how far back finish looks for the pass's sessions.
DEFAULT_SINCE = "30d"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path):
    return json.loads(path.read_text()) if path.exists() else {}


def write_json(path, data):
    path.write_text(json.dumps(data, indent=1) + "\n")


# start


def copy_specs(out, sources):
    for source in sources:
        if not source.is_file():
            raise LoopError(f"spec {source} is not a file")
        target = out / source.name
        if not target.exists():
            shutil.copy(source, target)


def save_pr_bodies(loop, out, github):
    numbered = [pr for pr in heads(loop, 1) if pr.isdigit()]
    if not numbered:
        raise LoopError("no PR in r1/heads.tsv has a number to read a body from; pass the spec with --spec")
    for pr in numbered:
        target = out / f"pr-{pr}.md"
        if not target.exists():
            target.write_text(github.api(f"pulls/{pr}", "--jq", ".body") + "\n")


def start(loop, orchestrator, github, specs):
    """Write run.json and save the spec; a resumed pass keeps its start time and the spec it saved first."""
    out = loop / "spec"
    out.mkdir(parents=True, exist_ok=True)
    if specs:
        copy_specs(out, specs)
    else:
        save_pr_bodies(loop, out, github)
    run = {"started": now(), **read_json(loop / "run.json"),
           "repo": github.slug, "host": socket.gethostname(), "orchestrator": orchestrator}
    write_json(loop / "run.json", run)
    return f"run.json and spec/ ({', '.join(sorted(p.name for p in out.iterdir()))}) saved in {loop}"


# finish


def session_role(prompt, loop):
    """The session's part in this pass (orchestrator, reviewer, or worker), or None when it belongs elsewhere."""
    match = LOOP_NAME.fullmatch(loop.name)
    if ORCHESTRATOR in prompt:
        brief_pass = PASS.search(prompt)
        mine = not match or not brief_pass or brief_pass.group(1) == match.group(2)
        return "orchestrator" if mine else None
    if not re.search(rf"review-loop/{re.escape(loop.name)}(?![\w-])", prompt):
        return None
    return "reviewer" if REVIEWER.search(prompt) else "worker"


def transcripts_command():
    found = shutil.which("transcripts") or Path.home() / ".local" / "bin" / "transcripts"
    return str(found)


def pass_sessions(loop, since):
    slug = LOOP_NAME.fullmatch(loop.name)
    pattern = f"review-loop/{re.escape(slug.group(1) if slug else loop.name)}"
    result = subprocess.run([transcripts_command(), "list", "--since", since, "--prompt", pattern, "--json"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise LoopError(f"transcripts list failed: {(result.stderr or result.stdout).strip()}")
    return json.loads(result.stdout)


def usage_record(sessions, loop):
    rows, by_role, unpriced = [], {}, []
    for session in sessions:
        role = session_role(session.get("prompt") or "", loop)
        if role is None:
            continue
        rows.append({"id": session["id"], "agent": session["agent"], "role": role, "started": session["started"],
                     "usd": session["usd"], "tokens": session["tokens"]})
        by_role[role] = by_role.get(role, 0) + (session["usd"] or 0)
        if session["usd"] is None:
            unpriced.append(session["id"])
    return {"at": now(), "usd_by_role": by_role, "unpriced": unpriced, "sessions": rows}


def finish(loop):
    """Write usage.json and stamp run.json finished; running it again refreshes both."""
    run = read_json(loop / "run.json")
    since = run["started"][:10] if "started" in run else DEFAULT_SINCE
    usage = usage_record(pass_sessions(loop, since), loop)
    write_json(loop / "usage.json", usage)
    write_json(loop / "run.json", {**run, "finished": usage["at"]})
    total = sum(usage["usd_by_role"].values())
    roles = ", ".join(f"{role} ${usd:.2f}" for role, usd in sorted(usage["usd_by_role"].items()))
    gaps = f"; unpriced: {', '.join(usage['unpriced'])}" if usage["unpriced"] else ""
    return f"{len(usage['sessions'])} sessions, ${total:.2f} ({roles or 'none found'}){gaps}"
