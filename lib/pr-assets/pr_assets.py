#!/usr/bin/env python3
"""Put PR screenshots on the repo's pr-assets branch and print their links.

  pr-assets [--branch NAME] DIR...

Run inside the PR's checkout. Each DIR lands at <branch>/<DIR's name>/ on
origin's pr-assets branch, replacing what that folder held, so

  pr-assets "$shots_dir/before" "$shots_dir/after"

writes <branch>/before/ and <branch>/after/. The branch is created when the
repo has none. The commit is built without a checkout and pushed straight to
the remote branch, retried when another push lands first, so the PR branch and
working tree are never touched. Prints one blob/...?raw=true link per file:
those render in private repos for anyone who can read the repo.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import quote

ASSETS = "pr-assets"
PUSH_ATTEMPTS = 3
GITHUB_REMOTE = re.compile(r"github\.com[:/](?P<repo>[^/]+/[^/]+?)(?:\.git)?/?$")


class Failure(Exception):
    pass


def git(*args, env=None):
    run = subprocess.run(["git", *args], text=True, capture_output=True, env=env)
    if run.returncode != 0:
        raise Failure(f"git {' '.join(args)}: {run.stderr.strip()}")
    return run.stdout.strip()


def github_repo():
    url = git("config", "--get", "remote.origin.url")
    match = GITHUB_REMOTE.search(url)
    if not match:
        raise Failure(f"origin is not a GitHub repo: {url}")
    return match["repo"]


def current_branch():
    branch = git("branch", "--show-current")
    if not branch:
        raise Failure("detached HEAD: pass --branch with the PR's branch name")
    return branch


def remote_head():
    """The remote pr-assets commit, or None when the repo has no such branch yet."""
    listed = git("ls-remote", "origin", f"refs/heads/{ASSETS}")
    if not listed:
        return None
    git("fetch", "--quiet", "origin", f"refs/heads/{ASSETS}")
    return git("rev-parse", "FETCH_HEAD")


def files_under(folder):
    return sorted(path for path in folder.rglob("*") if path.is_file())


def build_commit(parent, uploads, branch):
    """Commit parent's tree with each (folder, destination) replaced by the folder's files."""
    with tempfile.TemporaryDirectory() as scratch:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(scratch) / "index")}
        if parent:
            git("read-tree", parent, env=env)
        for folder, destination in uploads:
            git("rm", "--cached", "-r", "-q", "--ignore-unmatch", "--", destination, env=env)
            for path in files_under(folder):
                blob = git("hash-object", "-w", str(path))
                target = f"{destination}/{path.relative_to(folder).as_posix()}"
                git("update-index", "--add", "--cacheinfo", f"100644,{blob},{target}", env=env)
        tree = git("write-tree", env=env)
    parents = ["-p", parent] if parent else []
    return git("commit-tree", tree, *parents, "-m", f"chore(pr-assets): screenshots for {branch}")


def publish(uploads, branch):
    """Push the uploads onto origin's pr-assets, rebuilding on a fresh head after a rejected push."""
    for attempt in range(1, PUSH_ATTEMPTS + 1):
        commit = build_commit(remote_head(), uploads, branch)
        try:
            git("push", "--quiet", "origin", f"{commit}:refs/heads/{ASSETS}")
            return
        except Failure:
            if attempt == PUSH_ATTEMPTS:
                raise


def blob_url(repo, path):
    return f"https://github.com/{repo}/blob/{ASSETS}/{quote(path)}?raw=true"


def parse_uploads(folders, branch):
    uploads = []
    for folder in map(Path, folders):
        if not folder.is_dir() or not files_under(folder):
            raise Failure(f"{folder}: not a folder with files in it")
        uploads.append((folder, f"{branch}/{folder.resolve().name}"))
    return uploads


def main(argv):
    parser = argparse.ArgumentParser(prog="pr-assets", description=__doc__.split("\n\n")[0])
    parser.add_argument("--branch", help="PR branch whose folder to write (default: the current branch)")
    parser.add_argument("folders", nargs="+", metavar="DIR")
    args = parser.parse_args(argv)
    try:
        repo = github_repo()
        branch = args.branch or current_branch()
        uploads = parse_uploads(args.folders, branch)
        publish(uploads, branch)
    except Failure as failure:
        print(f"pr-assets: {failure}", file=sys.stderr)
        return 1
    for folder, destination in uploads:
        for path in files_under(folder):
            print(blob_url(repo, f"{destination}/{path.relative_to(folder).as_posix()}"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
