"""Refuse pull request merges that squash or rebase, so every commit is kept.

`gh stack merge` without a method reuses the last one used, so it must name
`--merge`. Like guard.py, this recognizes the common spellings and is not a
security boundary: GitHub's repository settings are the backstop. guard.py
hands it the leaves of the shell command (walk.py: past wrappers, `bash -c`,
scripts, and package scripts); this judges each `gh` call among them. A GraphQL query read
from a file (`query=@file`) goes unchecked.
"""
import os
import re

REASON = (
    "Merge with a merge commit so every commit is kept: gh pr merge N --merge --match-head-commit <head>, "
    "or gh stack merge --yes --merge on a stack's top PR. Squash and rebase merges are off; "
    "rebase the branch onto its base first when it needs it."
)
HELP = {"-h", "--help"}
REWRITING = {"squash", "rebase"}
PR_SHORT_METHODS = {"m": "merge", "s": "squash", "r": "rebase"}
# The flags of a short cluster (`-sd`) before one that takes a value (`-tSubject`).
PR_SHORT_CLUSTER = re.compile(r"-([^AbFtR]*)")
# The long flags of `gh pr merge` that take a value; the short ones are AbFtR above.
PR_VALUE_OPTIONS = {"--author-email", "--body", "--body-file", "--subject", "--match-head-commit", "--repo"}
# REST fields (merge_method=squash) and GraphQL inputs (mergeMethod: SQUASH).
API_METHOD = re.compile(r"merge_?method[\"']?\s*[:=]\s*[\"']?(squash|rebase)\b", re.I)


def refuses(command, leaf_words):
    """Whether a shell command squashes or rebases a PR merge, given the words of each leaf it runs."""
    if "api.github.com" in command and API_METHOD.search(command):
        return True
    return any(refuses_gh_call(gh_args(words)) for words in leaf_words)


def gh_args(words):
    """A `gh` call's arguments, or None for another command."""
    if not words or os.path.basename(words[0]) != "gh":
        return None
    return words[1:]


def refuses_gh_call(args):
    """Whether a `gh` call merges a PR by squash or rebase, or leaves `gh stack merge` to reuse its last method."""
    if args is None:
        return False
    if args[:2] == ["pr", "merge"]:
        return pr_merge_refused(args[2:])
    if args[:2] == ["stack", "merge"]:
        return stack_merge_refused(args[2:])
    return args[:1] == ["api"] and HELP.isdisjoint(args) and bool(API_METHOD.search(" ".join(args[1:])))


def pr_merge_refused(args):
    flags = flag_words(args, pr_takes_value)
    return HELP.isdisjoint(flags) and bool(REWRITING & pr_merge_methods(flags))


def stack_merge_refused(args):
    flags = flag_words(args, stack_takes_value)
    return HELP.isdisjoint(flags) and stack_merge_method(args) != "merge"


def flag_words(args, takes_value):
    """The arguments that are not the value of a flag reading its value from the next argument."""
    kept, skip = [], False
    for arg in args:
        if not skip:
            kept.append(arg)
        skip = not skip and takes_value(arg)
    return kept


def pr_takes_value(arg):
    """Whether a `gh pr merge` flag takes the next argument as its value, not inline (`--body=x`, `-tSubject`)."""
    if arg.startswith("--"):
        return arg in PR_VALUE_OPTIONS
    cluster = PR_SHORT_CLUSTER.match(arg)
    return bool(cluster) and len(arg) == cluster.end() + 1


def stack_takes_value(arg):
    return arg == "--merge-method"


def pr_merge_methods(flags):
    """The merge methods named by a `gh pr merge`'s flags, in long flags or short clusters (`-sd`)."""
    return {method for arg in flags for method in flag_methods(arg)}


def flag_methods(arg):
    if arg.startswith("--"):
        name = arg[2:].split("=", 1)[0]
        return [name] if name in PR_SHORT_METHODS.values() else []
    if not arg.startswith("-"):
        return []
    flags = PR_SHORT_CLUSTER.match(arg).group(1)
    return [PR_SHORT_METHODS[flag] for flag in flags if flag in PR_SHORT_METHODS]


def stack_merge_method(args):
    """The method a `gh stack merge` names, or None when it would reuse the last one used."""
    method = None
    for i, arg in enumerate(args):
        if arg in {"--merge", "--squash", "--rebase"}:
            method = arg[2:]
        elif arg == "--merge-method" and i + 1 < len(args):
            method = args[i + 1]
        elif arg.startswith("--merge-method="):
            method = arg.split("=", 1)[1]
    return method
