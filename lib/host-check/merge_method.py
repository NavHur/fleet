"""Refuse pull request merges that squash or rebase, so every commit is kept.

`gh stack merge` without a method reuses the last one used, so it must name
`--merge`. Like guard.py, this recognizes the common spellings and is not a
security boundary: GitHub's repository settings are the backstop. A GraphQL
query read from a file (`query=@file`) goes unchecked.
"""
import os
import re

REASON = (
    "Merge with a merge commit so every commit is kept: gh pr merge N --merge, "
    "gh stack merge --yes --merge, or REST merge_method=merge. Squash and rebase merges are off; "
    "rebase the branch onto its base first when it needs it."
)
HELP = {"-h", "--help"}
REWRITING = {"squash", "rebase"}
PR_SHORT_METHODS = {"m": "merge", "s": "squash", "r": "rebase"}
# The flags of a short cluster (`-sd`) before one that takes a value (`-tSubject`).
PR_SHORT_CLUSTER = re.compile(r"-([^AbFtR]*)")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*=")
# REST fields (merge_method=squash) and GraphQL inputs (mergeMethod: SQUASH).
API_METHOD = re.compile(r"merge_?method[\"']?\s*[:=]\s*[\"']?(squash|rebase)\b", re.I)


def refuses(command, commands):
    """Whether the shell command, split into its simple commands' words, squashes or rebases a PR merge."""
    if "api.github.com" in command and API_METHOD.search(command):
        return True
    return any(rewrites(gh_args(words)) for words in commands)


def gh_args(words):
    """A `gh` call's arguments after any NAME=value prefixes, or None for another command."""
    words = list(words)
    while words and ASSIGNMENT.match(words[0]):
        words.pop(0)
    if not words or os.path.basename(words[0]) != "gh":
        return None
    return words[1:]


def rewrites(args):
    if args is None or HELP & set(args):
        return False
    if args[:2] == ["pr", "merge"]:
        return bool(REWRITING & pr_merge_methods(args[2:]))
    if args[:2] == ["stack", "merge"]:
        return stack_merge_method(args[2:]) != "merge"
    return args[:1] == ["api"] and bool(API_METHOD.search(" ".join(args[1:])))


def pr_merge_methods(args):
    """The methods a `gh pr merge` names, in long flags or short clusters (`-sd`)."""
    return {method for arg in args for method in flag_methods(arg)}


def flag_methods(arg):
    if arg.startswith("--"):
        return [arg[2:].split("=", 1)[0]]
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
