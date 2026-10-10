#!/usr/bin/env python3
"""Score every changed function against Pedro's complexity limits.

Usage: measure_complexity.py BASE [HEAD] [--all | --over-only] [--repo DIR]
                             [--cognitive-limit N] [--cyclomatic-limit N]

  BASE         base revision; the diff starts at merge-base(BASE, HEAD).
               EMPTY measures every tracked file (whole-repository scope).
  HEAD         revision to measure. Omit it to measure the working tree,
               including uncommitted and untracked files.
  --all        list every function in the changed files, not only changed ones.
  --over-only  list only functions over a limit (summary counts still print).
  --repo       repository or worktree to measure (default: current directory).
  --cognitive-limit, --cyclomatic-limit
               a stricter limit the repository documents (AGENTS.md, a custom
               check script). A value looser than Pedro's limit is ignored.

Limits: cognitive above 8 and cyclomatic above 16 are over; equal passes. The
stricter of Pedro's limit and the repository's wins.

Languages and how each is measured:
- JS, TS, Svelte, Vue, Astro: the repository's oxlint and the complexity rules
  of the file's .oxlintrc.json, copied into a temporary config with max 0.
  Configs without a cognitive rule get fleet's `pbp/cognitive-complexity`
  plugin; files no config owns use classic `complexity` plus that plugin, run
  by the repository's oxlint or this skill's own. A second pass with the
  repository's real rules tags each excess `[lint: error]`, `[lint: warning]`,
  or `[lint passes]`, and reports functions the repository's stricter max
  catches.
- Python, GDScript, PHP: this skill's analyzers (complexity_*.py), tagged
  `[not lint-checked]`. GDScript needs a Python with gdtoolkit: the
  repository's virtualenv, PBP_GDTOOLKIT_PYTHON, or the venv the coverage
  note names. Python limits in ruff/flake8 (`max-complexity`) or
  complexipy (`max-complexity-allowed`) config count as repository limits.
  A Godot repository's `.godot-guard.yml` limits count too, and its
  godot-guard lint tags each GDScript excess, honoring the ratchet baseline.
The script never edits the repository: files are copied (or extracted from
HEAD) into a temporary tree. Exit status is 0 whenever measurement succeeds,
over or not; 2 means the measurement itself failed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import godot_guard

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_DIR / "scripts"
PLUGIN = SCRIPTS / "oxlint-plugin" / "pbp.mjs"
GDTOOLKIT_VENV = Path.home() / ".cache" / "pedro-best-practices" / "venv"
PEDRO_LIMITS = {"cognitive": 8, "cyclomatic": 16}
HOST_CHECK = os.path.expanduser("~/.local/bin/host-check")
LANGUAGES = {
    "js": {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts", ".svelte", ".vue", ".astro"},
    "python": {".py"},
    "gdscript": {".gd"},
    "php": {".php"},
}
CATEGORIES = ("correctness", "suspicious", "pedantic", "perf", "style", "restriction", "nursery")
SCORE = re.compile(r"[Cc]omplexity (?:of |from )?(\d+)")
MAXIMUM = re.compile(r"(?:Maximum allowed is|limit of|to the) (\d+)")
NAME = re.compile(r"`([^`]*)`")


def language_of(path: str) -> str | None:
    suffix = PurePosixPath(path).suffix
    return next((name for name, suffixes in LANGUAGES.items() if suffix in suffixes), None)


@dataclass
class Function:
    path: str
    name: str
    line: int
    end_line: int
    cognitive: int | None = None
    cyclomatic: int | None = None
    # metric -> (severity, repository max) for metrics the repository's own lint flags;
    # None when no repository lint was consulted.
    lint: dict[str, tuple[str, int | None]] | None = None
    limits: dict[str, int] = field(default_factory=lambda: dict(PEDRO_LIMITS))

    def score(self, metric: str) -> int | None:
        return self.cognitive if metric == "cognitive" else self.cyclomatic

    def excess(self) -> dict[str, int]:
        """metric -> the limit it exceeds (the stricter of Pedro's and the repository's)."""
        over = {}
        for metric, limit in self.limits.items():
            score = self.score(metric)
            if score is None:
                continue
            flagged = (self.lint or {}).get(metric)
            if flagged and flagged[1] is not None:
                limit = min(limit, flagged[1])
            if score > limit or flagged:
                over[metric] = limit
        return over

    def over(self) -> list[str]:
        return [f"{metric} {self.score(metric)} > {limit}" for metric, limit in self.excess().items()]

    def lint_tag(self) -> str:
        if self.lint is None:
            return " [not lint-checked]"
        severities = {self.lint[m][0] for m in self.excess() if m in self.lint}
        if "error" in severities:
            return " [lint: error]"
        return " [lint: warning]" if severities else " [lint passes]"


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    if result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {result.stderr.decode().strip()}")
    return result.stdout.decode()


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
    if os.environ.get("HOST_CHECK_ACTIVE") != "1" and os.access(HOST_CHECK, os.X_OK):
        command = [HOST_CHECK, *command]
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)


# Revisions and files


def changed_files(root: Path, base: str, head: str | None) -> list[str]:
    files = git(root, "diff", "--name-only", "--diff-filter=d", "-z", base, *([head] if head else [])).split("\0")
    if head is None:
        files += git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    return sorted({f for f in files if f and language_of(f) and "node_modules/" not in f})


def changed_lines(root: Path, base: str, head: str | None, files: list[str]) -> dict[str, set[int] | None]:
    """Map each file to its added or modified lines; None means the whole file."""
    lines: dict[str, set[int] | None] = {}
    current = None
    diff = git(root, "diff", "-U0", "--no-color", "--no-ext-diff", base, *([head] if head else []), "--", *files)
    for row in diff.splitlines():
        if row.startswith("+++ "):
            current = row[6:] if row.startswith("+++ b/") else None
            if current:
                lines.setdefault(current, set())
        elif row.startswith("@@") and current:
            match = re.match(r"@@ -\S+ \+(\d+)(?:,(\d+))? @@", row)
            start, count = int(match.group(1)), int(match.group(2) or 1)
            target = lines[current]
            if target is not None:
                target.update(range(start, start + count) if count else (start, start + 1))
    for path in files:
        lines.setdefault(path, None)  # untracked: every line is new
    return lines


def materialize(root: Path, head: str | None, paths: list[str], tree: Path) -> None:
    if not paths:
        return
    if head:
        archive = subprocess.run(["git", "-C", str(root), "archive", "--format=tar", head, "--", *paths],
                                 capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(tree)], input=archive.stdout, check=True)
        return
    for path in paths:
        source, target = root / path, tree / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("node_modules"))
        elif source.exists():
            shutil.copy2(source, target)


def read_file(root: Path, head: str | None, path: str) -> str | None:
    if head:
        result = subprocess.run(["git", "-C", str(root), "show", f"{head}:{path}"], capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else None
    target = root / path
    return target.read_text(errors="replace") if target.exists() else None


def owning_config(path: str, configs: list[str]) -> str | None:
    best = None
    for config in configs:
        directory = str(PurePosixPath(config).parent)
        if directory == "." or path.startswith(directory + "/"):
            if best is None or len(directory) > len(str(PurePosixPath(best).parent)):
                best = config
    return best


# JS family: oxlint


def strip_jsonc(text: str) -> str:
    """Drop // and /* */ comments outside strings, then trailing commas."""
    out, i, in_string = [], 0, False
    while i < len(text):
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\":
                out.append(text[i + 1])
                i += 1
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            out.append(ch)
        elif text.startswith("//", i):
            i = text.find("\n", i)
            if i < 0:
                break
            continue
        elif text.startswith("/*", i):
            i = text.find("*/", i) + 2
            continue
        else:
            out.append(ch)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def is_complexity_rule(name: str) -> bool:
    return name in ("complexity", "eslint/complexity") or name.endswith("cognitive-complexity")


def is_off(value: object) -> bool:
    level = value[0] if isinstance(value, list) and value else value
    return level in ("off", 0, "allow")


def measuring(value: object) -> object:
    if is_off(value):
        return "off"
    options = value[1] if isinstance(value, list) and len(value) > 1 and isinstance(value[1], dict) else {}
    return ["warn", {**options, "max": 0}]


def complexity_rules(rules: dict, transform=measuring) -> dict:
    return {name: transform(value) for name, value in rules.items() if is_complexity_rule(name)}


def looser_than_limits(name: str, value: object) -> str | None:
    """Describe how a repo rule definition lets a Pedro-limit excess through."""
    if is_off(value):
        return "turns it off"
    level = value[0] if isinstance(value, list) and value else value
    options = value[1] if isinstance(value, list) and len(value) > 1 and isinstance(value[1], dict) else {}
    limit = PEDRO_LIMITS["cognitive" if name.endswith("cognitive-complexity") else "cyclomatic"]
    reasons = []
    if level not in ("error", 2, "deny"):
        reasons.append(f"level {level!r}")
    if not isinstance(options.get("max"), int):
        reasons.append("no explicit max (rule default)")
    elif options["max"] > limit:
        reasons.append(f"max {options['max']} > {limit}")
    return ", ".join(reasons) or None


def measure_config(config: dict) -> tuple[dict, dict | None, list[str], list[str]]:
    """Return the max-0 config, the repo-rules config, the plugin paths they need, and coverage notes."""
    notes: list[str] = []
    top = complexity_rules(config.get("rules", {}))
    lint_top = complexity_rules(config.get("rules", {}), transform=lambda value: value)
    overrides, lint_overrides = [], []
    for name, value in lint_top.items():
        if reason := looser_than_limits(name, value):
            notes.append(f"top-level `{name}` {reason}; lint does not enforce Pedro's limit there")
    for override in config.get("overrides", []):
        rules = complexity_rules(override.get("rules", {}))
        if rules:
            overrides.append({"files": override["files"], "rules": rules})
            lint_rules = complexity_rules(override["rules"], transform=lambda value: value)
            lint_overrides.append({"files": override["files"], "rules": lint_rules})
            for name, value in lint_rules.items():
                if reason := looser_than_limits(name, value):
                    notes.append(f"override {override['files']} `{name}` {reason}; "
                                 "lint does not enforce Pedro's limit for those files")
    names = set(top) | {name for o in overrides for name in o["rules"]}
    plugins, plugin_paths = [], []
    if not any(name == "complexity" or name == "eslint/complexity" for name in names):
        top["complexity"] = ["warn", {"max": 0, "variant": "classic"}]
        notes.append("config has no cyclomatic `complexity` rule; measured with oxlint classic `complexity`")
    if not any(name.endswith("cognitive-complexity") for name in names):
        top["pbp/cognitive-complexity"] = ["warn", {"max": 0}]
        plugins.append(str(PLUGIN))
        notes.append("config has no cognitive-complexity rule; measured with fleet's pbp plugin (whitepaper v1.7)")
    if "extends" in config:
        notes.append("config uses `extends`; complexity rules defined in extended files were not copied")
    prefixes = {name.split("/")[0] for name in names if "/" in name}
    for plugin in config.get("jsPlugins", []):
        specifier = plugin if isinstance(plugin, str) else plugin.get("specifier", "")
        if isinstance(plugin, dict) and plugin.get("name") not in prefixes:
            continue
        plugins.append(plugin)
        if specifier.startswith("."):
            plugin_paths.append(specifier)
    measured = {
        "categories": {category: "off" for category in CATEGORIES},
        "ignorePatterns": config.get("ignorePatterns", []),
        "rules": top,
        "overrides": overrides,
    }
    if plugins:
        measured["jsPlugins"] = plugins
    enforced = None
    if lint_top or lint_overrides:
        enforced = {**measured, "rules": lint_top, "overrides": lint_overrides}
        repo_plugins = [p for p in plugins if p != str(PLUGIN)]
        enforced.pop("jsPlugins", None)
        if repo_plugins:
            enforced["jsPlugins"] = repo_plugins
    return measured, enforced, plugin_paths, notes


def find_oxlint(root: Path, config_dir: Path) -> Path | None:
    directory = config_dir
    while True:
        candidate = directory / "node_modules/.bin/oxlint"
        if candidate.exists():
            return candidate
        if directory == root or directory == directory.parent:
            break
        directory = directory.parent
    own = SKILL_DIR / "node_modules/.bin/oxlint"
    return own if own.exists() else None


def run_oxlint(root: Path, oxlint: Path, config: Path, files: list[Path]) -> list[dict]:
    result = run([str(oxlint), "-c", str(config), "--format", "json", *map(str, files)], root)
    try:
        return json.loads(result.stdout[result.stdout.find("{"):])["diagnostics"]
    except (json.JSONDecodeError, KeyError):
        sys.stderr.write(result.stdout + result.stderr)
        sys.exit(f"oxlint did not return JSON (exit {result.returncode}) for config {config}")


def collect(diagnostics: list[dict], tree: Path) -> dict[tuple[str, int, int], Function]:
    functions: dict[tuple[str, int, int], Function] = {}
    for diagnostic in diagnostics:
        code, message = diagnostic.get("code", ""), diagnostic.get("message", "")
        score, name, labels = SCORE.search(message), NAME.search(message), diagnostic.get("labels") or []
        if not score or not labels:
            continue
        span = labels[0]["span"]
        file = Path(diagnostic["filename"])
        path = str(file.relative_to(tree)) if file.is_absolute() else diagnostic["filename"]
        key = (path, span["offset"], span["length"])
        if key not in functions:
            body = (tree / path).read_bytes()[span["offset"]: span["offset"] + span["length"]]
            functions[key] = Function(path, name.group(1) if name else "<anonymous>", span["line"],
                                      span["line"] + body.count(b"\n"))
        metric = "cognitive" if "cognitive-complexity" in code else "cyclomatic" if code.endswith("(complexity)") else None
        if metric is None:
            continue
        setattr(functions[key], metric, int(score.group(1)))
        maximum = MAXIMUM.search(message)
        functions[key].lint = {**(functions[key].lint or {}),
                               metric: (diagnostic.get("severity", ""), int(maximum.group(1)) if maximum else None)}
    return functions


def measure_js(root: Path, head: str | None, files: list[str], tree: Path, notes: list[str],
               unmeasured: list[str]) -> list[Function]:
    if head:
        listing = git(root, "ls-tree", "-r", "--name-only", "-z", head)
    else:  # the working tree, including configs not committed yet
        listing = git(root, "ls-files", "-z") + git(root, "ls-files", "--others", "--exclude-standard", "-z")
    configs = [p for p in listing.split("\0") if PurePosixPath(p).name == ".oxlintrc.json" and "node_modules/" not in p]
    groups: dict[str | None, list[str]] = {}
    for path in files:
        groups.setdefault(owning_config(path, configs), []).append(path)
    functions: list[Function] = []
    for config_path, group in groups.items():
        if config_path:
            config_dir = str(PurePosixPath(config_path).parent)
            text = read_file(root, head, config_path) or "{}"
            config = json.loads(strip_jsonc(text))
            label = config_path
        else:
            config_dir, config, label = ".", {}, "(no .oxlintrc.json)"
        measured, enforced, plugin_paths, config_notes = measure_config(config)
        notes += [f"{label}: {note}" for note in config_notes]
        plugin_dirs = [os.path.normpath(str(PurePosixPath(config_dir, p).parent)) for p in plugin_paths]
        materialize(root, head, group + plugin_dirs, tree)
        for directory in {".", config_dir}:
            if (root / directory / "node_modules").exists() and not (tree / directory / "node_modules").exists():
                (tree / directory).mkdir(parents=True, exist_ok=True)
                (tree / directory / "node_modules").symlink_to(root / directory / "node_modules")
        oxlint = find_oxlint(root, root / config_dir)
        if oxlint is None:
            notes.append(f"{label}: no oxlint in the repository or in this skill (run `pnpm install` in "
                         f"{SKILL_DIR}); {len(group)} JS/TS file(s) not measured")
            unmeasured += group
            continue
        temp_config = tree / config_dir / ".pbp-measure.oxlintrc.json"
        temp_config.parent.mkdir(parents=True, exist_ok=True)
        temp_config.write_text(json.dumps(measured, indent=2))
        print(f"Config: {label} -> {len(group)} JS-family file(s); rules: "
              + ", ".join(sorted(set(measured["rules"]) | {n for o in measured["overrides"] for n in o["rules"]})))
        found = collect(run_oxlint(root, oxlint, temp_config, [tree / p for p in group]), tree)
        for function in found.values():
            function.lint = None
        if enforced is not None:  # second pass: the repository's real levels and maxes
            temp_config.write_text(json.dumps(enforced, indent=2))
            scored = sorted({f.path for f in found.values()})
            real = collect(run_oxlint(root, oxlint, temp_config, [tree / p for p in scored]), tree) if scored else {}
            for key, function in found.items():
                function.lint = real[key].lint if key in real else {}
        functions += found.values()
        unscored = [path for path in group if path not in {f.path for f in found.values()}]
        if unscored:
            notes.append(f"{label}: {len(unscored)} file(s) got no scores (outside the config's complexity scope, "
                         f"e.g. ignored tests, or no functions): {', '.join(unscored)}")
    return functions


# Python, GDScript, PHP: this skill's analyzers


def python_version(binary: str) -> tuple[int, int] | None:
    try:
        result = subprocess.run([binary, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                                capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    parts = result.stdout.split()
    return (int(parts[0]), int(parts[1])) if result.returncode == 0 and len(parts) == 2 else None


def has_gdtoolkit(binary: str) -> bool:
    try:
        return subprocess.run([binary, "-c", "import gdtoolkit"], capture_output=True, timeout=20).returncode == 0
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def python_candidates(root: Path) -> list[str]:
    names = [str(root / d / "bin" / "python") for d in (".venv", "venv", "env")]
    names += [f"python3.{minor}" for minor in range(20, 7, -1)] + ["python3", sys.executable]
    found = []
    for name in names:
        path = name if os.path.isabs(name) else shutil.which(name)
        if path and os.path.exists(path) and path not in found:
            found.append(path)
    return found


def pick_python(root: Path) -> str:
    """The newest Python available: it parses every older syntax."""
    versioned = [(python_version(p), p) for p in python_candidates(root)]
    versioned = [(v, p) for v, p in versioned if v]
    return max(versioned)[1] if versioned else sys.executable


def pick_gdtoolkit_python(root: Path) -> str | None:
    candidates = [os.environ.get("PBP_GDTOOLKIT_PYTHON", ""), str(GDTOOLKIT_VENV / "bin" / "python")]
    candidates += python_candidates(root)
    return next((p for p in candidates if p and os.path.exists(p) and has_gdtoolkit(p)), None)


def repo_python_limits(root: Path, head: str | None) -> tuple[dict[str, int], list[str]]:
    """Complexity maxes a Python repository configures for ruff, flake8, or complexipy."""
    limits, notes = {}, []
    patterns = {"cyclomatic": r"^\s*max-complexity\s*=\s*(\d+)", "cognitive": r"^\s*max-complexity-allowed\s*=\s*(\d+)"}
    for name in ("pyproject.toml", "ruff.toml", ".ruff.toml", "setup.cfg", ".flake8", "tox.ini"):
        text = read_file(root, head, name)
        if not text:
            continue
        for metric, pattern in patterns.items():
            match = re.search(pattern, text, re.M)
            if match and int(match.group(1)) < limits.get(metric, 10**6):
                limits[metric] = int(match.group(1))
                notes.append(f"{name}: repository {metric} max {match.group(1)}")
    return limits, notes


def measure_external(language: str, root: Path, head: str | None, files: list[str], tree: Path,
                     notes: list[str], unmeasured: list[str]) -> list[Function]:
    if language == "python":
        interpreter = pick_python(root)
        command = [interpreter, str(SCRIPTS / "complexity_python.py")]
    elif language == "gdscript":
        interpreter = pick_gdtoolkit_python(root)
        if interpreter is None:
            notes.append(f"GDScript: no Python with gdtoolkit; {len(files)} file(s) not measured. Use the "
                         "repository's lint setup, or run: python3 -m venv "
                         f"{GDTOOLKIT_VENV} && {GDTOOLKIT_VENV}/bin/pip install 'gdtoolkit==4.*'")
            unmeasured += files
            return []
        command = [interpreter, str(SCRIPTS / "complexity_gdscript.py")]
    else:
        php = shutil.which("php")
        if php is None:
            notes.append(f"PHP: no `php` on PATH; {len(files)} file(s) not measured")
            unmeasured += files
            return []
        command = [sys.executable, str(SCRIPTS / "complexity_php.py"), "--php", php]
    materialize(root, head, files, tree)
    result = run([*command, *[str(tree / f) for f in files]], tree)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        notes.append(f"{language}: analyzer failed ({result.stderr.strip()[:300]}); {len(files)} file(s) not measured")
        unmeasured += files
        return []
    print(f"Analyzer: {language} -> {len(files)} file(s) with {command[0]}")
    functions = []
    for absolute, value in report.items():
        path = str(Path(absolute).relative_to(tree))
        if isinstance(value, dict):
            notes.append(f"{path}: not measured ({value.get('error')})")
            unmeasured.append(path)
            continue
        for item in value:
            functions.append(Function(path, item["name"], item["line"], item["end_line"],
                                      item["cognitive"], item["cyclomatic"]))
    return functions


# Report


def effective_limits(args, root: Path, head: str | None, has_python: bool, notes: list[str],
                     guard: godot_guard.GodotGuard | None = None) -> dict[str, dict[str, int]]:
    """Limits per language: Pedro's, tightened by flags and repository config."""
    base = dict(PEDRO_LIMITS)
    for metric in base:
        value = getattr(args, f"{metric}_limit")
        if value is None:
            continue
        if value < base[metric]:
            base[metric] = value
            notes.append(f"--{metric}-limit {value}: stricter than Pedro's {PEDRO_LIMITS[metric]}; applied")
        else:
            notes.append(f"--{metric}-limit {value} is looser than Pedro's {PEDRO_LIMITS[metric]}; ignored")
    limits = {language: dict(base) for language in LANGUAGES}
    if has_python:
        repo, repo_notes = repo_python_limits(root, head)
        notes += repo_notes
        for metric, value in repo.items():
            limits["python"][metric] = min(limits["python"][metric], value)
    tighten_for_guard(limits["gdscript"], guard, notes)
    return limits


def tighten_for_guard(limits: dict[str, int], guard: godot_guard.GodotGuard | None, notes: list[str]) -> None:
    if guard is None:
        return
    for metric in PEDRO_LIMITS:
        limits[metric] = min(limits[metric], guard.limits[metric])
    notes.append(f"{godot_guard.CONFIG}: repository cognitive max {guard.limits['cognitive']}, "
                 f"cyclomatic max {guard.limits['cyclomatic']}, with the godot-guard baseline")


def load_guard(root: Path, head: str | None, by_language: dict[str, list[str]]) -> godot_guard.GodotGuard | None:
    if "gdscript" not in by_language:
        return None
    return godot_guard.load(lambda path: read_file(root, head, path))


GUARD_RULES = {"cognitive": "cognitive-complexity", "cyclomatic": "cyclomatic-complexity"}


def guard_lint(function: Function, guard: godot_guard.GodotGuard) -> dict[str, tuple[str, int | None]]:
    """The metrics godot-guard fails for this function, after its baseline allowance."""
    flagged = {}
    for metric, rule in GUARD_RULES.items():
        severity, score = guard.severity(rule), function.score(metric)
        key = f"{function.path}::{function.name}"
        if severity and score is not None and score > max(guard.limits[metric], guard.allowance(rule, key)):
            flagged[metric] = (severity, guard.limits[metric])
    return flagged


def tag_with_guard(functions: list[Function], guard: godot_guard.GodotGuard | None) -> None:
    """Lambdas, accessors, and repeated names have keys this skill's names can't match: left untagged."""
    if guard is None:
        return
    functions = [f for f in functions if language_of(f.path) == "gdscript"]
    names = [(f.path, f.name) for f in functions]
    for function in functions:
        unique = names.count((function.path, function.name)) == 1
        if unique and function.name.split(".")[-1] not in ("<lambda>", "set", "get"):
            function.lint = guard_lint(function, guard)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base")
    parser.add_argument("head", nargs="?")
    listing = parser.add_mutually_exclusive_group()
    listing.add_argument("--all", action="store_true", help="list unchanged functions in changed files too")
    listing.add_argument("--over-only", action="store_true", help="list only functions over a limit")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--cognitive-limit", type=int)
    parser.add_argument("--cyclomatic-limit", type=int)
    args = parser.parse_args()

    root = Path(git(Path(args.repo), "rev-parse", "--show-toplevel").strip())
    if args.base == "EMPTY":  # whole-repository scope: diff from the empty tree
        merge_base = git(root, "hash-object", "-t", "tree", "/dev/null").strip()
    else:
        merge_base = git(root, "merge-base", args.base, args.head or "HEAD").strip()
    files = changed_files(root, merge_base, args.head)
    by_language: dict[str, list[str]] = {}
    for path in files:
        by_language.setdefault(language_of(path), []).append(path)
    notes: list[str] = []
    guard = load_guard(root, args.head, by_language)
    limits = effective_limits(args, root, args.head, "python" in by_language, notes, guard)
    print(f"Complexity of {root} {args.base}..{args.head or 'working tree'} (merge-base {merge_base[:10]})")
    print(f"Pedro's limits: cognitive > {PEDRO_LIMITS['cognitive']}, cyclomatic > {PEDRO_LIMITS['cyclomatic']} "
          "(equal passes; a stricter repository limit wins)")
    if not files:
        print("No changed source files.\nResult: 0 functions over threshold (nothing to measure).")
        return 0

    lines = changed_lines(root, merge_base, args.head, files)
    functions: list[Function] = []
    unmeasured: list[str] = []
    with tempfile.TemporaryDirectory(prefix="measure-complexity-") as tmp:
        tree = Path(tmp)
        for language, group in sorted(by_language.items()):
            if language == "js":
                found = measure_js(root, args.head, group, tree, notes, unmeasured)
            else:
                found = measure_external(language, root, args.head, group, tree, notes, unmeasured)
            for function in found:
                function.limits = dict(limits[language])
            functions += found
    tag_with_guard(functions, guard)

    def is_changed(function: Function) -> bool:
        touched = lines.get(function.path)
        return touched is None or any(function.line <= n <= function.end_line for n in touched)

    changed = [f for f in functions if is_changed(f)]
    shown = functions if args.all else changed
    if args.over_only:
        shown = [f for f in shown if f.over()]
    trivial = [f for f in shown if (f.cyclomatic or 0) <= 1 and not f.cognitive and not f.over()]
    shown = [f for f in shown if f not in trivial]
    print()
    current = None
    for function in sorted(shown, key=lambda f: (f.path, f.line)):
        if function.path != current:
            current = function.path
            print(current)
        cognitive = "-" if function.cognitive is None else str(function.cognitive)
        cyclomatic = "-" if function.cyclomatic is None else str(function.cyclomatic)
        flag = "  OVER: " + "; ".join(function.over()) + function.lint_tag() if function.over() else ""
        mark = "" if not args.all or is_changed(function) else " (unchanged)"
        print(f"  L{function.line}-{function.end_line} {function.name}{mark}: "
              f"cognitive {cognitive}, cyclomatic {cyclomatic}{flag}")
    if not shown:
        print("(no functions to list)")
    if trivial:
        print(f"({len(trivial)} trivial functions with cyclomatic 1 and cognitive 0 not listed)")
    if notes:
        print("\nCoverage notes:")
        for note in notes:
            print(f"  {note}")
    print("\n'-' cognitive: score 0, or counted inside the enclosing function (nested functions).")
    over = [f for f in changed if f.over()]
    tags = [f.lint_tag() for f in over]
    failing = sum(tag.startswith(" [lint:") for tag in tags)
    passing = tags.count(" [lint passes]")
    unchecked = tags.count(" [not lint-checked]")
    counts = ", ".join(f"{len(group)} {language}" for language, group in sorted(by_language.items()))
    print(f"Result: {len(over)} function{'s' if len(over) != 1 else ''} over threshold among {len(changed)} "
          f"changed functions in {len(files)} changed source files ({counts}): {failing} fail the repository's "
          f"lint, {passing} pass it, {unchecked} not lint-checked.")
    if unmeasured:
        print(f"INCOMPLETE: {len(unmeasured)} changed file(s) not measured; see the coverage notes.")
    for function in over:
        print(f"  {function.path}:{function.line} {function.name}: {'; '.join(function.over())}{function.lint_tag()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
