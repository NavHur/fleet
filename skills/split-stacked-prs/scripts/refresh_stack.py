#!/usr/bin/env python3
"""Re-measure every layer and refresh the size and gate lines of every PR body.

Run after each fix round. Every layer in the manifest directory is covered,
so none is left out. For each layer it runs diff_budget.py against the
merge-base with its parent, and again with --per-commit for the layer's own
commits, and prints a table; a layer under the 12 KB weighted floor shows as
"small" and needs a stated reason. With --gates LOG_DIR (from
layer_gates.sh) it also reports each layer's gate verdicts, but only for
results recorded at the branch's current commit.

PR bodies: the line starting "Size against its base:" (and, with --gates,
"Layer gates at") is replaced, or appended when missing. Without
--update-prs it prints the body changes only; with it, it PATCHes each body
over REST and reads it back. The PR comes from the manifest's `# pr:` header,
else from the open PR whose head is the branch.

Generated globs default to the policy's data exemptions; pass --generated to
replace them, --test for other verified test files.

Usage:
  refresh_stack.py --manifests DIR [--prefix P] [--base REF] [--gates LOG_DIR]
                   [--repo OWNER/REPO] [--update-prs] [--generated GLOB]... [--test GLOB]...
Exit status 2 when a layer or one of its commits exceeds a ceiling, 1 on other errors.
"""

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_GENERATED = [
    "data/*.json", "*/data/*.json", "prisma/municipalities.json", "*/prisma/municipalities.json",
    "prisma/migrations/*", "*/prisma/migrations/*", "*.geojson",
]
SIZE_PREFIX = "Size against its base:"
LAYER_FLOOR = 12_000  # weighted bytes: one full commit
GATES_PREFIX = "Layer gates at"


def run(*args, check=True):
    return subprocess.run(args, capture_output=True, text=True, check=check)


def git(*args):
    return run("git", *args).stdout.strip()


def header(path, key):
    with open(path) as fh:
        for line in fh:
            m = re.match(rf"#\s*{key}:\s*(.+)", line.strip())
            if m:
                return m.group(1).strip()
    return None


def repo_slug(explicit):
    if explicit:
        return explicit
    url = run("git", "remote", "get-url", "origin", check=False).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def find_pr(repo, branch):
    owner = repo.split("/")[0]
    out = run("gh", "api", f"repos/{repo}/pulls?head={owner}:{branch}&state=open", "--jq", ".[].number")
    numbers = out.stdout.split()
    return int(numbers[0]) if numbers else None


def set_line(body, prefix, line):
    lines = body.split("\n")
    for i, old in enumerate(lines):
        if old.startswith(prefix):
            lines[i] = line
            return "\n".join(lines)
    return body.rstrip("\n") + "\n\n" + line


def budget(fork, head, flags):
    result = run(sys.executable, os.path.join(HERE, "diff_budget.py"), fork, head, "--json", *flags, check=False)
    if result.returncode not in (0, 2):
        sys.exit(f"diff_budget failed for {head[:9]}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def layer_status(size, commits):
    if any(c["status"] == "cap-violation" for c in commits):
        return "commit-over"
    if size["status"] == "within-cap" and size["weighted_size"] < LAYER_FLOOR:
        return "small"
    return size["status"]


def gates_line(log_dir, name, head):
    path = os.path.join(log_dir, f"{name}.result")
    if not os.path.exists(path):
        return None, "no result"
    sha, _branch, rest = open(path).read().strip().split(" ", 2)
    if sha != head:
        return None, f"stale (gated {sha[:9]}, branch is at {head[:9]})"
    verdicts, _, summary = rest.partition("::")
    pretty = ", ".join(v.replace("=", " ") for v in verdicts.split())
    summary = re.sub(r"\s+", " ", summary).strip()
    text = f"{GATES_PREFIX} `{sha[:9]}`: {pretty}" + (f" ({summary})" if summary else "") + "."
    return text, verdicts


def kb_figure(size):
    return f"{size / 1000:.1f}"


def kilobytes(size):
    return f"{kb_figure(size)} KB"


def print_table(rows):
    w = max(len(r[0]) for r in rows)
    print(
        f"\n{'layer':<{w}} {'PR':>5} {'weighted KB':>11} {'raw KB':>7} {'tests KB':>9}"
        f" {'excl KB':>8} {'commits':>7}  status   gates"
    )
    for name, pr, size, commits, status, gate_note in rows:
        print(
            f"{name:<{w}} {('#' + str(pr)) if pr else '-':>5} {kb_figure(size['weighted_size']):>11}"
            f" {kb_figure(size['raw_churn']):>7} {kb_figure(size['test_churn']):>9}"
            f" {kb_figure(size['excluded_bytes']):>8} {len(commits):>7}  {status:<8} {gate_note}"
        )
    over = [(row[0], c) for row in rows for c in row[3] if c["status"] == "cap-violation"]
    for name, c in over:
        print(
            f"{name}: commit {c['commit'][:9]} weighted {kilobytes(c['weighted_size'])},"
            f" raw {kilobytes(c['raw_churn'])} over "
            f"{kb_figure(c['hard_cap'])}/{kilobytes(c['raw_cap'])}: {c['subject']}"
        )


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifests", required=True)
    parser.add_argument("--prefix", default="")
    parser.add_argument("--base")
    parser.add_argument("--gates", help="layer_gates.sh log directory")
    parser.add_argument("--repo")
    parser.add_argument("--update-prs", action="store_true")
    parser.add_argument("--generated", action="append")
    parser.add_argument("--test", action="append", default=[])
    return parser.parse_args()


def budget_flags(args):
    flags = []
    for glob in args.generated or DEFAULT_GENERATED:
        flags += ["--generated", glob]
    for glob in args.test:
        flags += ["--test", glob]
    return flags


def size_line(size, commits):
    excluded = f", excluded {kilobytes(size['excluded_bytes'])}" if size["excluded_bytes"] else ""
    return (
        f"{SIZE_PREFIX} weighted {kilobytes(size['weighted_size'])}, raw churn {kilobytes(size['raw_churn'])}"
        f" (tests {kilobytes(size['test_churn'])}{excluded}) in {len(commits)} commits."
    )


def layer_pr(manifest, repo, branch):
    pr = header(manifest, "pr")
    if pr:
        return int(pr)
    return find_pr(repo, branch) if repo else None


def patch_body(name, repo, pr, new, line):
    """PATCH the body, read it back; 1 when the size line did not take, else 0."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(new)
    run("gh", "api", "-X", "PATCH", f"repos/{repo}/pulls/{pr}", "-F", f"body=@{fh.name}", "--jq", ".number")
    os.unlink(fh.name)
    back = run("gh", "api", f"repos/{repo}/pulls/{pr}", "--jq", ".body").stdout
    if line in back:
        print(f"{name}: PR #{pr} body updated")
        return 0
    print(f"{name}: PR #{pr} body did not take the new size line", file=sys.stderr)
    return 1


def sync_body(name, branch, pr, repo, line, gate_text, update_prs):
    """Show or apply the new size and gate lines of a PR body; the number of errors."""
    if pr is None or repo is None:
        print(f"{name}: no open PR for {branch}" if repo else f"{name}: no GitHub origin; pass --repo", file=sys.stderr)
        return int(update_prs)
    body = run("gh", "api", f"repos/{repo}/pulls/{pr}", "--jq", ".body").stdout
    body = body[:-1] if body.endswith("\n") else body
    new = set_line(body, SIZE_PREFIX, line)
    if gate_text:
        new = set_line(new, GATES_PREFIX, gate_text)
    if new == body:
        print(f"{name}: PR #{pr} body already current")
        return 0
    if update_prs:
        return patch_body(name, repo, pr, new, line)
    diff = difflib.unified_diff(body.split("\n"), new.split("\n"), f"#{pr}", f"#{pr} new", lineterm="", n=0)
    print("\n".join(diff))
    return 0


def manifest_names(directory):
    return sorted(
        f for f in os.listdir(directory)
        if not f.startswith(".") and os.path.isfile(os.path.join(directory, f))
    )


def stack_base(args, names):
    base = args.base or header(os.path.join(args.manifests, names[0]), "base")
    if not base:
        sys.exit("no --base and no '# base:' header in the first manifest")
    return base


def main():
    args = parse_args()
    names = manifest_names(args.manifests)
    base = stack_base(args, names)
    flags = budget_flags(args)
    repo = repo_slug(args.repo)

    over, errors, parent = False, 0, base
    rows = []
    for name in names:
        manifest = os.path.join(args.manifests, name)
        branch = header(manifest, "branch") or args.prefix + name
        head = git("rev-parse", branch)
        fork = git("merge-base", parent, branch)
        size = budget(fork, head, flags)
        commits = budget(fork, head, ["--per-commit", *flags])["commits"]
        status = layer_status(size, commits)
        over |= status in ("cap-violation", "commit-over")
        gate_text, gate_note = gates_line(args.gates, name, head) if args.gates else (None, "")
        pr = layer_pr(manifest, repo, branch)
        rows.append((name, pr, size, commits, status, gate_note))
        errors += sync_body(name, branch, pr, repo, size_line(size, commits), gate_text, args.update_prs)
        parent = branch

    print_table(rows)
    print(f"{len(rows)}/{len(names)} layers measured")
    if errors:
        return 1
    return 2 if over else 0


if __name__ == "__main__":
    sys.exit(main())
