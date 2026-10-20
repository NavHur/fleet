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


def kilobytes(size):
    return f"{size / 1000:.1f}"


def print_table(rows):
    w = max(len(r[0]) for r in rows)
    print(f"\n{'layer':<{w}} {'PR':>5} {'weighted':>9} {'raw':>6} {'tests':>6} {'excl':>5} {'commits':>7}  status   gates  (KB)")
    for name, pr, size, commits, status, gate_note in rows:
        print(
            f"{name:<{w}} {('#' + str(pr)) if pr else '-':>5} {kilobytes(size['weighted_size']):>9}"
            f" {kilobytes(size['raw_churn']):>6} {kilobytes(size['test_churn']):>6}"
            f" {kilobytes(size['excluded_bytes']):>5} {len(commits):>7}  {status:<8} {gate_note}"
        )
    over = [(row[0], c) for row in rows for c in row[3] if c["status"] == "cap-violation"]
    for name, c in over:
        print(
            f"{name}: commit {c['commit'][:9]} weighted {kilobytes(c['weighted_size'])} KB,"
            f" raw {kilobytes(c['raw_churn'])} KB over {kilobytes(c['hard_cap'])}/{kilobytes(c['raw_cap'])}: {c['subject']}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifests", required=True)
    parser.add_argument("--prefix", default="")
    parser.add_argument("--base")
    parser.add_argument("--gates", help="layer_gates.sh log directory")
    parser.add_argument("--repo")
    parser.add_argument("--update-prs", action="store_true")
    parser.add_argument("--generated", action="append")
    parser.add_argument("--test", action="append", default=[])
    args = parser.parse_args()

    names = sorted(
        f for f in os.listdir(args.manifests)
        if not f.startswith(".") and os.path.isfile(os.path.join(args.manifests, f))
    )
    base = args.base or header(os.path.join(args.manifests, names[0]), "base")
    if not base:
        sys.exit("no --base and no '# base:' header in the first manifest")
    budget_flags = []
    for glob in args.generated or DEFAULT_GENERATED:
        budget_flags += ["--generated", glob]
    for glob in args.test:
        budget_flags += ["--test", glob]
    repo = repo_slug(args.repo)

    over, errors, parent = False, 0, base
    rows = []
    for name in names:
        manifest = os.path.join(args.manifests, name)
        branch = header(manifest, "branch") or args.prefix + name
        head = git("rev-parse", branch)
        fork = git("merge-base", parent, branch)
        size = budget(fork, head, budget_flags)
        commits = budget(fork, head, ["--per-commit", *budget_flags])["commits"]
        status = layer_status(size, commits)
        over |= status in ("cap-violation", "commit-over")
        excluded = f", excluded {kilobytes(size['excluded_bytes'])} KB" if size["excluded_bytes"] else ""
        size_line = (
            f"{SIZE_PREFIX} weighted {kilobytes(size['weighted_size'])} KB, raw churn {kilobytes(size['raw_churn'])} KB"
            f" (tests {kilobytes(size['test_churn'])} KB{excluded}) in {len(commits)} commits."
        )
        gate_text, gate_note = gates_line(args.gates, name, head) if args.gates else (None, "")
        pr = header(manifest, "pr")
        pr = int(pr) if pr else (find_pr(repo, branch) if repo else None)
        rows.append((name, pr, size, commits, status, gate_note))

        if pr is None or repo is None:
            print(f"{name}: no open PR for {branch}" if repo else f"{name}: no GitHub origin; pass --repo", file=sys.stderr)
            errors += args.update_prs
        else:
            body = run("gh", "api", f"repos/{repo}/pulls/{pr}", "--jq", ".body").stdout
            body = body[:-1] if body.endswith("\n") else body
            new = set_line(body, SIZE_PREFIX, size_line)
            if gate_text:
                new = set_line(new, GATES_PREFIX, gate_text)
            if new == body:
                print(f"{name}: PR #{pr} body already current")
            elif not args.update_prs:
                diff = difflib.unified_diff(body.split("\n"), new.split("\n"), f"#{pr}", f"#{pr} new", lineterm="", n=0)
                print("\n".join(diff))
            else:
                slug = repo
                with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
                    fh.write(new)
                run("gh", "api", "-X", "PATCH", f"repos/{slug}/pulls/{pr}", "-F", f"body=@{fh.name}", "--jq", ".number")
                os.unlink(fh.name)
                back = run("gh", "api", f"repos/{slug}/pulls/{pr}", "--jq", ".body").stdout
                if size_line in back:
                    print(f"{name}: PR #{pr} body updated")
                else:
                    print(f"{name}: PR #{pr} body did not take the new size line", file=sys.stderr)
                    errors += 1
        parent = branch

    print_table(rows)
    print(f"{len(rows)}/{len(names)} layers measured")
    if errors:
        return 1
    return 2 if over else 0


if __name__ == "__main__":
    sys.exit(main())
