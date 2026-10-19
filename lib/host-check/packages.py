"""Package scripts for the host-check guard: the package.json script bodies a
package-manager command runs, through the nearest package, workspace filters
(`pnpm --filter X test`, `pnpm -r lint`), and turbo tasks.
"""
import fnmatch
import functools
import glob
import json
import os
import re
import shlex


@functools.lru_cache(maxsize=None)
def manifest(directory):
    """The parsed package.json in a directory, or None."""
    try:
        with open(os.path.join(directory, "package.json")) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def scripts(directory):
    found = (manifest(directory) or {}).get("scripts")
    return found if isinstance(found, dict) else {}


def package_name(directory):
    name = (manifest(directory) or {}).get("name")
    return name if isinstance(name, str) else ""


def nearest_package(cwd):
    directory = os.path.abspath(cwd)
    while manifest(directory) is None:
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent
    return directory


def workspace_patterns(directory):
    """The package globs of a pnpm, npm, or yarn workspace rooted here, or None."""
    try:
        with open(os.path.join(directory, "pnpm-workspace.yaml")) as handle:
            text = handle.read()
    except OSError:
        found = (manifest(directory) or {}).get("workspaces")
        found = found.get("packages") if isinstance(found, dict) else found
        return [p for p in found if isinstance(p, str)] if isinstance(found, list) else None
    # Only the top-level `packages:` list matters, so no YAML parser is needed.
    patterns, inside = [], False
    for line in text.splitlines():
        if re.match(r"^packages\s*:", line):
            inside = True
        elif inside and (item := re.match(r"^\s*-\s*['\"]?([^'\"#\s]+)", line)):
            patterns.append(item.group(1))
        elif inside and line.strip() and not line[0].isspace():
            inside = False
    return patterns


@functools.lru_cache(maxsize=None)
def workspace(cwd):
    """(root, package directories) of the workspace containing cwd, or None."""
    directory = os.path.abspath(cwd)
    while (patterns := workspace_patterns(directory)) is None:
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent
    found = [directory]
    for pattern in patterns:
        if not pattern.startswith("!"):
            found += [os.path.normpath(match) for match in sorted(glob.glob(os.path.join(directory, pattern), recursive=True))
                      if manifest(os.path.normpath(match)) is not None]
    return directory, tuple(dict.fromkeys(found))


def selected(cwd, selectors, recursive):
    """Package directories a selection names (pnpm/turbo filters, npm/yarn workspaces); the nearest package by default."""
    found = workspace(cwd) if selectors or recursive else None
    if not found:
        home = nearest_package(cwd)
        return [home] if home else []
    root, directories = found
    members = [d for d in directories if d != root] or [root]
    chosen = []
    for selector in selectors:
        if selector.startswith("!"):
            continue
        if "[" in selector:
            return members  # changed-since selections: any package may run
        pattern = re.sub(r"^\.\.\.\^?|\^?\.\.\.$", "", selector).strip("{}")
        if pattern.startswith((".", "/")) or ("/" in pattern and not pattern.startswith("@")):
            path = os.path.normpath(os.path.join(cwd, pattern))
            chosen += [d for d in directories if fnmatch.fnmatch(d, path)]
        else:
            chosen += [d for d in directories if fnmatch.fnmatch(package_name(d), pattern)]
    return list(dict.fromkeys(chosen)) if selectors else members


# Value-taking options, then those that select packages, set the directory, or recurse.
MANAGER_OPTIONS = {
    "pnpm": ({"-F", "--filter", "--filter-prod", "-C", "--dir", "--reporter", "--workspace-concurrency", "--loglevel",
              "--test-pattern", "--changed-files-ignore-pattern", "--resume-from"},
             {"-F", "--filter", "--filter-prod"}, {"-C", "--dir"}, {"-r", "--recursive"}),
    "npm": ({"-w", "--workspace", "--prefix", "--loglevel", "--script-shell"},
            {"-w", "--workspace"}, {"--prefix"}, {"--workspaces", "-ws"}),
    "yarn": ({"--cwd"}, set(), {"--cwd"}, set()),
    "bun": ({"--cwd", "-F", "--filter"}, {"-F", "--filter"}, {"--cwd"}, set()),
}
RUN_VERBS = {"run", "run-script", "rum", "urn"}
SCRIPT_VERBS = {"test": "test", "t": "test", "tst": "test", "start": "start", "stop": "stop", "restart": "restart"}
EXEC_VERBS = {"pnpm": {"exec", "dlx"}, "npm": {"exec", "x"}, "yarn": {"exec", "dlx"}, "bun": {"x"}}
# Built-in commands that never name a package script.
BUILTINS = {
    "add", "install", "i", "ci", "update", "up", "upgrade", "remove", "rm", "uninstall", "link", "unlink",
    "import", "rebuild", "rb", "prune", "fetch", "patch", "patch-commit", "audit", "list", "ls", "ll",
    "outdated", "why", "licenses", "create", "init", "publish", "pack", "store", "root", "bin", "config",
    "c", "setup", "env", "deploy", "doctor", "server", "help", "info", "cache", "workspaces", "version",
    "set", "node", "approve-builds", "self-update", "login", "logout", "whoami", "view", "search",
}
TURBO_VALUE_OPTIONS = {"--concurrency", "--cache-dir", "--output-logs", "--log-order", "--env-mode", "--cache",
                       "--log-prefix", "--profile", "--ui", "--token", "--team", "--api", "--cwd"}


def manager_options(name, args, cwd, selectors, recursive):
    """Consume leading package-manager options: (rest, cwd, selectors, recursive)."""
    values, selects, directories, recursives = MANAGER_OPTIONS[name]
    selectors, i = list(selectors), 0
    while i < len(args) and args[i].startswith("-") and args[i] != "--":
        key, eq, value = args[i].partition("=")
        if key in values and not eq:
            value = args[i + 1] if i + 1 < len(args) else ""
            i += 1
        if key in selects:
            selectors.append(value)
        elif key in directories:
            cwd = os.path.join(cwd, os.path.expanduser(value))
        elif key in recursives:
            recursive = True
        i += 1
    return args[i:], cwd, selectors, recursive


def script_runs(name, args, cwd):
    """The commands `pnpm|npm|yarn|bun [OPTIONS] [run] SCRIPT [ARGS]` runs, each with its directory.

    Arguments are appended to the script body as the package manager does.
    `exec`, `dlx`, and pnpm or yarn names without a script run an executable.
    An unresolved script gives [], leaving its name to decide.
    """
    args, cwd, selectors, recursive = manager_options(name, args, cwd, [], False)
    if not args:
        return []
    verb, rest = args[0], args[1:]
    if name == "yarn" and verb == "workspace" and len(rest) >= 2:
        selectors, verb, rest = selectors + [rest[0]], rest[1], rest[2:]
    if verb in EXEC_VERBS[name]:
        while rest and rest[0].startswith("-"):
            rest = rest[1:]
        return [(shlex.join(rest), d) for d in selected(cwd, selectors, recursive) or [cwd]] if rest else []
    if verb in RUN_VERBS:
        rest, cwd, selectors, recursive = manager_options(name, rest, cwd, selectors, recursive)
        if not rest:
            return []
        script, extra = rest[0], rest[1:]
    elif verb in SCRIPT_VERBS:
        script, extra = SCRIPT_VERBS[verb], rest
    elif name in {"npm", "bun"} or verb in BUILTINS:
        return []
    else:
        script, extra = verb, rest
    extra = extra[1:] if extra[:1] == ["--"] else extra
    suffix = "".join(" " + shlex.quote(arg) for arg in extra)
    runs = [(scripts(d)[script] + suffix, d) for d in selected(cwd, selectors, recursive)
            if isinstance(scripts(d).get(script), str)]
    if runs or selectors or recursive or verb in RUN_VERBS or verb in SCRIPT_VERBS or name not in {"pnpm", "yarn"}:
        return runs
    return [(shlex.join([script] + extra), cwd)]  # `pnpm vitest run` runs the executable


def turbo_runs(args, cwd):
    """The package scripts `turbo run TASK... [--filter X]` runs, each with its directory."""
    selectors, tasks, i = [], [], 0
    while i < len(args) and args[i] != "--":
        key, eq, value = args[i].partition("=")
        if key.startswith("-"):
            if (key in TURBO_VALUE_OPTIONS or key in {"-F", "--filter"}) and not eq:
                value = args[i + 1] if i + 1 < len(args) else ""
                i += 1
            if key in {"-F", "--filter"}:
                selectors.append(value)
            elif key == "--cwd":
                cwd = os.path.join(cwd, value)
        elif tasks or args[i] != "run":
            tasks.append(args[i])
        i += 1
    found = workspace(cwd)
    if not found:
        return []
    directories = selected(found[0], selectors, True)
    runs = []
    for task in tasks:
        package, _, task = task.rpartition("#")
        runs += [(scripts(d)[task], d) for d in directories
                 if isinstance(scripts(d).get(task), str) and package in {"", package_name(d)}]
    return runs


def expansions(name, args, cwd):
    """What a package runner runs, as (command, directory) pairs; [] when unknown."""
    if name in MANAGER_OPTIONS:
        return script_runs(name, args, cwd)
    if name == "turbo":
        return turbo_runs(args, cwd)
    if name in {"npx", "bunx"}:
        while args and args[0].startswith("-"):
            args = args[2:] if args[0] in {"-p", "--package"} else args[1:]
        return [(shlex.join(args), cwd)] if args else []
    return []
