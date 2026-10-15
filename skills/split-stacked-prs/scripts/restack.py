#!/usr/bin/env python3
"""Move a stack onto its base's new tip: rebase each layer, gate it, and push every branch at once.

    restack.py start --base REF BRANCH... [--old-base REV] [--tests] [--no-gates] [--push]
    restack.py resume STATE_DIR [--tests] [--no-gates] [--push]
    restack.py push STATE_DIR
    restack.py clean STATE_DIR

BRANCHes go bottom to top. List every branch of chained stacks in order: each
layer is rebased onto the new tip of the one below it, from the commit it forked
at, so a seam whose upper stack still sits on the lower stack's old tip moves
too (gh stack rebase skips it). The bottom layer forks at merge-base(REF, it),
or at --old-base when a lower layer was squash-merged into REF.

The work happens in a scratch worktree, STATE_DIR/wt, on restack/<branch>
copies of origin/<branch>; your checkouts and local branches stay as they are.
On a conflict the run stops with exit 3: resolve it in STATE_DIR/wt, run
`git -C STATE_DIR/wt rebase --continue`, then `restack.py resume STATE_DIR`.

After the rebase it reports, per layer, whether its diff against its parent is
unchanged (same patch-id), then runs layer_gates.sh over the restacked
branches: typecheck, lint, and format-check of the layer's files, plus the
tests on the top layer with --tests. --push (or the push command) sends every branch in one
atomic `git push` with a lease on each old remote tip: every branch moves or
none does, and a pre-push hook runs once.
Gates must pass before --push pushes; `push` pushes regardless.

Exit status: 0 done, 1 error, 2 gates failed, 3 rebase conflict to resolve.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
PREFIX = "restack/"
CONFLICT, GATES_FAILED = 3, 2


class Failure(Exception):
    pass


def git(*args, cwd=None, check=True):
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)
    if check and result.returncode != 0:
        raise Failure(f"git {' '.join(args)}: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def sha(ref, cwd=None):
    return git("rev-parse", "--verify", f"{ref}^{{commit}}", cwd=cwd)


def short(ref):
    return ref[:10]


# --- State ---------------------------------------------------------------------


def save(state):
    Path(state["dir"], "state.json").write_text(json.dumps(state, indent=2) + "\n")


def load(state_dir):
    try:
        return json.loads(Path(state_dir, "state.json").read_text())
    except (OSError, ValueError) as error:
        raise Failure(f"no restack state in {state_dir}: {error}") from error


# --- Start -----------------------------------------------------------------------


def fetch(base, branches):
    refs = [f"+refs/heads/{b}:refs/remotes/origin/{b}" for b in branches]
    if base.startswith("origin/"):
        refs.append(f"+refs/heads/{base[7:]}:refs/remotes/{base}")
    git("fetch", "--quiet", "origin", *refs)


def layer_plan(base, branches, old_base):
    """For each layer: its old tip, the commit it forked from, and nothing yet for the new tip."""
    tips = [sha(f"origin/{b}") for b in branches]
    forks = [old_base or git("merge-base", base, tips[0])]
    forks += [git("merge-base", lower, upper) for lower, upper in zip(tips, tips[1:])]
    return [{"branch": b, "old": tip, "fork": fork, "new": None} for b, tip, fork in zip(branches, tips, forks)]


def start(args):
    fetch(args.base, args.branches)
    root = git("rev-parse", "--show-toplevel")
    state_dir = Path.home() / ".cache" / "restack" / f"{Path(root).name}-{time.strftime('%Y%m%d-%H%M%S')}"
    state_dir.mkdir(parents=True)
    base_tip = sha(args.base)
    old_base = sha(args.old_base) if args.old_base else None
    state = {"dir": str(state_dir), "wt": str(state_dir / "wt"), "base": args.base, "base_tip": base_tip,
             "layers": layer_plan(args.base, args.branches, old_base), "pushed": False}
    git("worktree", "add", "--quiet", "--detach", state["wt"], base_tip)
    for layer in state["layers"]:
        git("branch", "--force", PREFIX + layer["branch"], layer["old"])
    save(state)
    print(f"state: {state_dir}")
    return state


# --- Rebase ----------------------------------------------------------------------


def rebase_in_progress(wt):
    paths = (git("rev-parse", "--path-format=absolute", "--git-path", name, cwd=wt) for name in ("rebase-merge", "rebase-apply"))
    return any(Path(path).exists() for path in paths)


def onto(state, index):
    return state["base_tip"] if index == 0 else state["layers"][index - 1]["new"]


def rebase_layer(state, index):
    """Rebase one layer; False when it stopped on a conflict."""
    layer = state["layers"][index]
    branch = PREFIX + layer["branch"]
    result = subprocess.run(["git", "rebase", "--quiet", "--onto", onto(state, index), layer["fork"], branch],
                            cwd=state["wt"], text=True, capture_output=True)
    if result.returncode == 0:
        layer["new"] = sha(branch, cwd=state["wt"])
        return True
    if not rebase_in_progress(state["wt"]):
        raise Failure(f"rebase of {layer['branch']} failed: {(result.stderr or result.stdout).strip()}")
    print(f"{layer['branch']}: conflict while rebasing onto {short(onto(state, index))}.\n"
          f"{result.stdout.strip()}\n"
          f"Resolve it in {state['wt']}, run `git -C {state['wt']} rebase --continue`, "
          f"then `{sys.argv[0]} resume {state['dir']}`.")
    return False


def rebase_layers(state):
    for index, layer in enumerate(state["layers"]):
        if layer["new"]:
            continue
        stopped = not rebase_layer(state, index)
        save(state)
        if stopped:
            return CONFLICT
    return None


def resume(state):
    if rebase_in_progress(state["wt"]):
        raise Failure(f"a rebase is still in progress in {state['wt']}; finish it with `git rebase --continue`")
    pending = next((i for i, layer in enumerate(state["layers"]) if not layer["new"]), None)
    if pending is not None and git("rev-parse", "--abbrev-ref", "HEAD", cwd=state["wt"]) == PREFIX + state["layers"][pending]["branch"]:
        state["layers"][pending]["new"] = sha("HEAD", cwd=state["wt"])  # the conflicted layer, now finished
        save(state)
    return rebase_layers(state)


# --- Report and gates --------------------------------------------------------------


def patch_id(parent, tip, cwd):
    diff = git("diff", "--binary", parent, tip, cwd=cwd)
    if not diff:
        return ""
    out = subprocess.run(["git", "patch-id", "--stable"], input=diff + "\n", cwd=cwd, text=True, capture_output=True)
    return out.stdout.split(" ")[0]


def report(state):
    print(f"base {state['base']} at {short(state['base_tip'])}")
    for index, layer in enumerate(state["layers"]):
        before = patch_id(layer["fork"], layer["old"], state["wt"])
        after = patch_id(onto(state, index), layer["new"], state["wt"])
        verdict = "diff unchanged" if before == after else "DIFF CHANGED (check the conflict resolution)"
        print(f"  {layer['branch']}: {short(layer['old'])} -> {short(layer['new'])}  {verdict}")


def write_manifests(state):
    manifests = Path(state["dir"], "manifests")
    manifests.mkdir(exist_ok=True)
    for index, layer in enumerate(state["layers"]):
        header = f"# base: {state['base_tip']}\n" if index == 0 else ""
        Path(manifests, f"{index + 1:02d}").write_text(f"{header}# branch: {PREFIX}{layer['branch']}\n")
    return manifests


def run_gates(state, tests):
    manifests = write_manifests(state)
    env = dict(os.environ, **({} if tests else {"TEST_CMD": "skip"}))
    log_dir = Path(state["dir"], "gates")
    command = ["bash", str(HERE / "layer_gates.sh"), "--manifests", str(manifests), "--log-dir", str(log_dir)]
    return subprocess.run(command, cwd=state["wt"], env=env).returncode == 0


# --- Push and clean ----------------------------------------------------------------


def push(state):
    leases = [f"--force-with-lease=refs/heads/{layer['branch']}:{layer['old']}" for layer in state["layers"]]
    refspecs = [f"refs/heads/{PREFIX}{layer['branch']}:refs/heads/{layer['branch']}" for layer in state["layers"]]
    result = subprocess.run(["git", "push", "--atomic", "--porcelain", "origin", *leases, *refspecs],
                            cwd=state["wt"], text=True, capture_output=True)
    print(result.stdout.strip() or result.stderr.strip())
    if result.returncode != 0:
        raise Failure("push failed (a lease fails when someone pushed a layer since the fetch); nothing was forced")
    state["pushed"] = True
    save(state)
    print("Pushed. Local branches and worktrees that track these are now behind origin; "
          f"reset them where needed, then `{sys.argv[0]} clean {state['dir']}`.")


def clean(state):
    git("worktree", "remove", "--force", state["wt"], check=False)
    for layer in state["layers"]:
        git("branch", "--delete", "--force", PREFIX + layer["branch"], check=False)
    print(f"removed the worktree and {PREFIX}* branches; state kept in {state['dir']}")


def finish(state, args):
    report(state)
    gates_ok = args.no_gates or run_gates(state, args.tests)
    if not gates_ok:
        print(f"gates failed; logs in {state['dir']}/gates. Fix on the layer that owns the code and restack again, "
              f"or `{sys.argv[0]} push {state['dir']}` to push anyway.")
        return GATES_FAILED
    if args.push:
        push(state)
    else:
        print(f"Not pushed. Push with `{sys.argv[0]} push {state['dir']}`.")
    return 0


# --- CLI ---------------------------------------------------------------------------


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    begin = commands.add_parser("start")
    begin.add_argument("--base", required=True, help="the base's ref, e.g. origin/nightly")
    begin.add_argument("--old-base", help="where the bottom layer forked, when merge-base is wrong")
    begin.add_argument("branches", nargs="+", help="stack branches, bottom to top")
    again = commands.add_parser("resume")
    again.add_argument("state_dir")
    for sub in (begin, again):
        sub.add_argument("--tests", action="store_true", help="also run the tests, once on the top layer")
        sub.add_argument("--no-gates", action="store_true", help="skip layer_gates.sh")
        sub.add_argument("--push", action="store_true", help="push when the gates pass")
    for name in ("push", "clean"):
        commands.add_parser(name).add_argument("state_dir")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        if args.command in ("push", "clean"):
            state = load(args.state_dir)
            (push if args.command == "push" else clean)(state)
            return 0
        state = start(args) if args.command == "start" else load(args.state_dir)
        stopped = rebase_layers(state) if args.command == "start" else resume(state)
        return stopped or finish(state, args)
    except Failure as error:
        print(f"restack: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
