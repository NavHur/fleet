"""Run bin/sync on every machine in hosts/ at once (bin/sync --all).

    python3 sync_all.py FLEET SELF [--apply]

Each hosts/<name>/host.json names the machine's fleet `checkout` and, for a
machine reached over SSH, its `ssh` host. SELF, this machine, runs its
checkout's bin/sync directly; the machines its host.json `reaches` lists run
theirs over SSH in a login bash,
which puts node and npx on PATH. Each machine's whole output goes to
~/.cache/fleet/sync/<name>.log and stdout gets one line per machine. Exits 1
when any machine failed or could not be reached.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HOME = Path.home()
LOGS = HOME / ".cache" / "fleet" / "sync"
SSH = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
TIMEOUT_SECONDS = 30 * 60
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# bin/sync's plan lines: two spaces, a lowercase verb, spaces, the target.
PLAN_LINE = re.compile(r"^  [a-z][a-z-]* +\S")


def say(verb: str, text: str) -> None:
    print(f"  {verb:<10} {text}", flush=True)


def machines(fleet: Path) -> dict[str, dict]:
    return {conf.parent.name: json.loads(conf.read_text()) for conf in sorted((fleet / "hosts").glob("*/host.json"))}


def command(name: str, conf: dict, self_name: str, reaches: list[str], apply: bool) -> list[str] | None:
    """How to run bin/sync on that machine from this one, or None when it cannot be reached."""
    checkout = conf.get("checkout")
    if not checkout:
        return None
    flags = ["--apply"] if apply else []
    if name == self_name:
        return [str(Path(checkout).expanduser() / "bin" / "sync"), *flags]
    if "ssh" not in conf or name not in reaches:
        return None
    # The checkout's ~ expands on the far side.
    return [*SSH, conf["ssh"], "bash -lc " + shlex.quote(" ".join([f"cd {checkout} &&", "bin/sync", *flags]))]


def run(argv: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, errors="replace", timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as timeout:
        output = timeout.output if isinstance(timeout.output, str) else (timeout.output or b"").decode(errors="replace")
        return 124, output + f"\nStopped after {TIMEOUT_SECONDS // 60} minutes."
    except OSError as error:
        return 127, str(error)
    return done.returncode, done.stdout


def summary(code: int, output: str) -> tuple[str, str]:
    """The status column and the detail for one machine's run."""
    lines = [line for line in output.splitlines() if line.strip()]
    if code != 0:
        return "failed", f"exit {code}: {lines[-1].strip() if lines else 'no output'}"
    if "Already in sync." in output:
        return "ok", "already in sync"
    count = sum(1 for line in lines if PLAN_LINE.match(line))
    changes = f"{count} change" + ("" if count == 1 else "s")
    if "Dry run: nothing changed." in output:
        return "plan", f"{changes} planned"
    return "ok", f"{changes} made"


def main(argv: list[str]) -> int:
    fleet, self_name, apply = Path(argv[0]), argv[1], "--apply" in argv[2:]
    confs = machines(fleet)
    reaches = confs[self_name].get("reaches", [])
    plans = {name: command(name, conf, self_name, reaches, apply) for name, conf in confs.items()}
    reachable = {name: argv for name, argv in plans.items() if argv}
    with ThreadPoolExecutor(max_workers=max(len(reachable), 1)) as pool:
        results = dict(zip(reachable, pool.map(run, reachable.values())))
    LOGS.mkdir(parents=True, exist_ok=True)
    failed = False
    for name in plans:
        if name not in results:
            say("skipped", f"{name}: not in {self_name}'s reaches, or host.json has no checkout or ssh host")
            continue
        code, output = results[name]
        (LOGS / f"{name}.log").write_text(ANSI.sub("", output))
        status, detail = summary(code, output)
        failed = failed or status == "failed"
        say(status, f"{name}: {detail}")
    print(f"Full output: {LOGS}/<machine>.log")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
