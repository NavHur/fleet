"""loop.py start and finish: a pass's run record, the spec its reviewers read, and what its sessions cost.

start writes LOOP/run.json (repo, host, orchestrator, start time) and saves the spec into LOOP/spec/, so a
later replay reads the spec as it stood. finish writes LOOP/usage.json, the cost of every session this pass
ran, from this machine's transcripts while they still exist, stamps run.json finished, and copies the ledger
into ARCHIVE on this machine, out of ~/.cache, so the record outlives a cache cleanup.
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from loop_state import LoopError, heads

ORCHESTRATOR = "You are the orchestrator of a review loop"
REVIEWER = re.compile(r"You are the \S+ reviewer in round \d+ of a review loop")
PASS = re.compile(r"^Pass: (\d+)", re.MULTILINE)
LOOP_NAME = re.compile(r"(.+)-p(\d+)")
# Where finish keeps a copy of each finished ledger; each machine keeps its own.
ARCHIVE = Path.home() / ".local" / "share" / "review-loop-archive"
# Without a start time, how far back finish looks for the pass's sessions.
DEFAULT_SINCE = "30d"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path):
    return json.loads(path.read_text()) if path.exists() else {}


def write_json(path, data):
    path.write_text(json.dumps(data, indent=1) + "\n")


# start


def check_specs(sources):
    """Refuse a spec that is not a file, or two that would save under one name."""
    by_name = {}
    for source in sources:
        if not source.is_file():
            raise LoopError(f"spec {source} is not a file")
        by_name.setdefault(source.name, []).append(source)
    clashes = [paths for paths in by_name.values() if len(paths) > 1]
    if clashes:
        raise LoopError(f"specs share the file name {clashes[0][0].name}: "
                        f"{', '.join(map(str, clashes[0]))}; rename one")


def copy_specs(out, sources):
    check_specs(sources)
    for source in sources:
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


def loop_prompt_pattern(loop):
    """Regex for a prompt naming one of this loop's passes: pr-7 matches pr-7-p1 but not pr-70-p1."""
    slug = LOOP_NAME.fullmatch(loop.name)
    if not slug:
        return rf"review-loop/{re.escape(loop.name)}(?![\w-])"
    return rf"review-loop/{re.escape(slug.group(1))}-p\d+(?![\w-])"


def session_role(prompt, loop):
    """The session's part in this pass (orchestrator, reviewer, or worker), or None when it belongs elsewhere."""
    match = LOOP_NAME.fullmatch(loop.name)
    if ORCHESTRATOR in prompt:
        if not re.search(loop_prompt_pattern(loop), prompt):
            return None
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
    pattern = loop_prompt_pattern(loop)
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


def archive_ledger(loop):
    """Make ARCHIVE/<loop> an exact copy of the ledger; at every step the old or the new copy is on disk."""
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(dir=ARCHIVE, prefix=f".{loop.name}-new-"))
    try:
        shutil.copytree(loop, staged, dirs_exist_ok=True)
    except BaseException:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    replace_archive(staged, ARCHIVE / loop.name)


def replace_archive(staged, final):
    """Swap staged in for final: the old copy moves aside first and comes back if the swap fails.

    The last installed archive is always at final or old, so a retry after a crash mid-swap restores it first.
    """
    old = final.with_name(f".{final.name}-old")
    if old.exists() and not final.exists():
        old.rename(final)
    shutil.rmtree(old, ignore_errors=True)
    if final.exists():
        final.rename(old)
    try:
        staged.rename(final)
    except BaseException:
        if old.exists():
            old.rename(final)
        raise
    shutil.rmtree(old, ignore_errors=True)


def finish(loop):
    """Write usage.json, stamp run.json finished, and archive the ledger; running it again refreshes all three."""
    run = read_json(loop / "run.json")
    since = run["started"][:10] if "started" in run else DEFAULT_SINCE
    usage = usage_record(pass_sessions(loop, since), loop)
    write_json(loop / "usage.json", usage)
    write_json(loop / "run.json", {**run, "finished": usage["at"]})
    archive_ledger(loop)
    total = sum(usage["usd_by_role"].values())
    roles = ", ".join(f"{role} ${usd:.2f}" for role, usd in sorted(usage["usd_by_role"].items()))
    gaps = f"; unpriced: {', '.join(usage['unpriced'])}" if usage["unpriced"] else ""
    cost = f"{len(usage['sessions'])} sessions, ${total:.2f} ({roles or 'none found'}){gaps}"
    return f"{cost}\narchived in {ARCHIVE / loop.name}"
