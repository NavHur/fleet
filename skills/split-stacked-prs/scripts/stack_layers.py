#!/usr/bin/env python3
"""A stack's layers: name, branch, parent, fork point, head, and pull request.

The one reader of a manifest directory's stack identity (the format is in the
header of lib.sh) and of a stack given as a branch list. The parent of a layer
is the branch below it, or the stack base for the bottom layer; its fork point
is the merge-base of its head with its parent's head, so `git diff FORK HEAD`
is the layer's own change. Pull requests come from a manifest's `# pr:`
header, else from the open PR whose head is the branch, over REST.

    stack_layers.py layers --manifests DIR [--prefix P]
        name<TAB>branch per layer, bottom to top; reads no Git refs.
    stack_layers.py base --manifests DIR [--base REF]
        the stack base: --base, else the first manifest's `# base:` header;
        no output, exit 0, when there is neither.
    stack_layers.py heads --manifests DIR [--prefix P] [--base REF] [--repo OWNER/REPO]
    stack_layers.py heads --base REF BRANCH... [--repo OWNER/REPO]
        PR<TAB>LAYER<TAB>FORK<TAB>HEAD per layer, bottom to top: review-loop's
        heads.tsv. PR is the number, or the branch when no PR is open.
    stack_layers.py pr-base --branch BRANCH [--repo OWNER/REPO]
        the base ref of BRANCH's open PR; no output, exit 0, when none is open.

Exit status 1 on a bad stack or a failed git or gh call, with the reason on stderr.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import subprocess
import sys


class StackError(Exception):
    pass


class NoBase(StackError):
    """Neither --base nor a `# base:` header names the stack base."""


@dataclass(frozen=True)
class Layer:
    name: str
    branch: str
    parent: str
    fork: str | None = None
    head: str | None = None
    pr: int | None = None


@dataclass(frozen=True)
class Manifest:
    name: str
    headers: dict[str, str]
    paths: tuple[str, ...]


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise StackError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def commit_sha(ref: str) -> str:
    return git("rev-parse", "--verify", f"{ref}^{{commit}}")


def resolve(base: str, layers: list[Layer], remote: str | None) -> list[Layer]:
    """Fill each layer's head (from REMOTE/branch when a remote is given) and fork point."""
    parent_head = commit_sha(base)
    resolved = []
    for layer in layers:
        head = commit_sha(f"{remote}/{layer.branch}" if remote else layer.branch)
        resolved.append(replace(layer, head=head, fork=git("merge-base", parent_head, head)))
        parent_head = head
    return resolved


@dataclass(frozen=True)
class PullRequest:
    head: str
    base_ref: str


class GitHub:
    """Pull request lookups for one repository, over the REST API through `gh api`."""

    def __init__(self, slug: str):
        self.slug = slug

    @classmethod
    def from_origin(cls, explicit: str | None = None, root: str | os.PathLike = ".") -> GitHub:
        """The repository named by --repo, else by ROOT's origin remote."""
        if explicit:
            return cls(explicit)
        url = git("-C", str(root), "remote", "get-url", "origin")
        match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
        if not match:
            raise StackError(f"origin is not a GitHub repository: {url}")
        return cls(match.group(1))

    def api(self, path: str, *options: str) -> str:
        """`gh api repos/SLUG/PATH OPTIONS...`'s output; StackError with gh's message when it fails."""
        result = subprocess.run(["gh", "api", f"repos/{self.slug}/{path}", *options], capture_output=True, text=True)
        if result.returncode != 0:
            raise StackError(f"gh api repos/{self.slug}/{path}: {(result.stderr or result.stdout).strip()}")
        return result.stdout.strip()

    def open_pr(self, branch: str) -> int | None:
        owner = self.slug.split("/")[0]
        numbers = self.api(f"pulls?head={owner}:{branch}&state=open", "--jq", ".[].number").split()
        return int(numbers[0]) if numbers else None

    def pr(self, number: int) -> PullRequest:
        data = json.loads(self.api(f"pulls/{number}"))
        return PullRequest(head=data["head"]["sha"], base_ref=data["base"]["ref"])


def read_manifest(path: Path) -> Manifest:
    headers, paths = {}, []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        header = re.match(r"#\s*(\w+):\s*(.+)", line)
        if header:
            headers.setdefault(header.group(1), header.group(2).strip())
        elif line and not line.startswith("#"):
            paths.append(line.removeprefix("~"))
    return Manifest(path.name, headers, tuple(paths))


def read_manifests(directory: Path) -> list[Manifest]:
    directory = Path(directory)
    files = sorted(p for p in directory.iterdir() if p.is_file() and not p.name.startswith(".")) \
        if directory.is_dir() else []
    if not files:
        raise StackError(f"no manifests in {directory}")
    return [read_manifest(path) for path in files]


def manifest_branch(manifest: Manifest, prefix: str) -> str:
    if "branch" in manifest.headers:
        return manifest.headers["branch"]
    if not prefix:
        raise StackError(f"{manifest.name}: no '# branch:' header and no --prefix")
    return prefix + manifest.name


def manifest_base(manifests: list[Manifest], explicit: str | None) -> str:
    base = explicit or manifests[0].headers.get("base")
    if not base:
        raise NoBase("no --base and no '# base:' header in the first manifest")
    return base


def chain(base: str, rows: list[tuple[str, str, int | None]]) -> list[Layer]:
    """Layers from (name, branch, pr) rows, each one's parent the branch below it."""
    parents = [base] + [branch for _, branch, _ in rows[:-1]]
    return [Layer(name, branch, parent, pr=pr) for (name, branch, pr), parent in zip(rows, parents)]


@dataclass(frozen=True)
class Stack:
    base: str
    layers: tuple[Layer, ...]

    @classmethod
    def from_manifests(cls, directory, prefix: str = "", base: str | None = None, *,
                       git_refs: bool = True, github=None) -> Stack:
        manifests = read_manifests(directory)
        base = manifest_base(manifests, base)
        rows = [(m.name, manifest_branch(m, prefix), header_pr(m)) for m in manifests]
        layers = with_prs(chain(base, rows), github)
        return cls(base, tuple(resolve(base, layers, None) if git_refs else layers))

    @classmethod
    def from_branches(cls, base: str, branches: list[str], *, remote: str | None = None, github=None) -> Stack:
        layers = with_prs(chain(base, [(branch, branch, None) for branch in branches]), github)
        return cls(base, tuple(resolve(base, layers, remote)))


def with_prs(layers: list[Layer], github) -> list[Layer]:
    """Fill each layer without a `# pr:` header from its branch's open PR."""
    if github is None:
        return layers
    return [layer if layer.pr else replace(layer, pr=github.open_pr(layer.branch)) for layer in layers]


def header_pr(manifest: Manifest) -> int | None:
    pr = manifest.headers.get("pr")
    if not pr:
        return None
    try:
        return int(pr)
    except ValueError:
        raise StackError(f"{manifest.name}: '# pr:' is not a PR number: {pr}") from None


# --- Command line ------------------------------------------------------------------


def optional_github(explicit: str | None, skipped: str) -> GitHub | None:
    """The repository's GitHub, or None after saying why SKIPPED is what happens without it."""
    try:
        return GitHub.from_origin(explicit)
    except StackError as error:
        print(f"no GitHub origin, {skipped}; pass --repo ({error})", file=sys.stderr)
        return None


def print_layers(args) -> int:
    for manifest in read_manifests(args.manifests):
        print(f"{manifest.name}\t{manifest_branch(manifest, args.prefix)}")
    return 0


def print_base(args) -> int:
    try:
        print(manifest_base(read_manifests(args.manifests), args.base))
    except NoBase:
        pass
    return 0


def print_heads(args) -> int:
    github = optional_github(args.repo, "PR column holds branches")
    if args.manifests:
        stack = Stack.from_manifests(args.manifests, args.prefix, args.base, github=github)
    elif args.base and args.branches:
        stack = Stack.from_branches(args.base, args.branches, github=github)
    else:
        raise StackError("heads needs --manifests, or --base and branches")
    for layer in stack.layers:
        print(f"{layer.pr or layer.branch}\t{layer.name}\t{layer.fork}\t{layer.head}")
    return 0


def print_pr_base(args) -> int:
    github = GitHub.from_origin(args.repo)
    number = github.open_pr(args.branch)
    if number is not None:
        print(github.pr(number).base_ref)
    return 0


def parse_args(argv):
    root = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = root.add_subparsers(dest="command", required=True)
    layers = commands.add_parser("layers")
    layers.add_argument("--manifests", required=True)
    layers.add_argument("--prefix", default="")
    layers.set_defaults(run=print_layers)
    base = commands.add_parser("base")
    base.add_argument("--manifests", required=True)
    base.add_argument("--base")
    base.set_defaults(run=print_base)
    heads = commands.add_parser("heads")
    heads.add_argument("--manifests")
    heads.add_argument("--prefix", default="")
    heads.add_argument("--base")
    heads.add_argument("--repo")
    heads.add_argument("branches", nargs="*")
    heads.set_defaults(run=print_heads)
    pr_base = commands.add_parser("pr-base")
    pr_base.add_argument("--branch", required=True)
    pr_base.add_argument("--repo")
    pr_base.set_defaults(run=print_pr_base)
    return root.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return args.run(args)
    except StackError as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
