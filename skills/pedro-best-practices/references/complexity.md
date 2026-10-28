# Complexity limits

How the audit measures complexity and classifies an excess; [rules.md](rules.md) step 5 runs it.

Cognitive complexity above **8** and cyclomatic complexity above **16** are violations; eight and sixteen pass. Where the repository sets a stricter limit, the stricter limit wins: NJ Homes Next and Receipt Hub fail lint on `dca/cognitive-complexity` max 8 and classic `complexity` max 16; Godot repositories set theirs in `.godot-guard.yml` (hexstead and wingmen: cognitive 6, cyclomatic 12). Never call an excess advisory or optional. Cognitive complexity follows the SonarSource whitepaper (v1.7) in every language; cyclomatic follows ESLint's classic `complexity`. Each reference lists its language's mappings. Measure with the bundled script instead of scoring by hand:

```sh
<this skill's directory>/scripts/measure_complexity.py BASE HEAD   # committed range
<this skill's directory>/scripts/measure_complexity.py BASE        # working tree vs BASE
<this skill's directory>/scripts/measure_complexity.py EMPTY HEAD  # whole repository
```

Pass `--cognitive-limit N` or `--cyclomatic-limit N` for a stricter limit the repository documents outside lint configuration (an `AGENTS.md` rule, a custom check script); the script ignores a looser value. It reads oxlint configs and Python's ruff, flake8, and complexipy limits itself. It diffs from `merge-base(BASE, HEAD)`, sends each changed file to its language's measurer, and prints every changed function's scores against the effective limits:

- **JS, TS, Svelte, Vue, Astro**: the repository's oxlint with the complexity rules from the file's `.oxlintrc.json` at max 0. A config with no cognitive rule gets fleet's `pbp/cognitive-complexity` plugin, which scores identically to `dca/cognitive-complexity`; files no config owns use the skill's own oxlint. A second pass with the repository's real rules tags each excess `[lint: error]`, `[lint: warning]`, or `[lint passes]`.
- **Python, GDScript, PHP**: Rust analyzers, tagged `[not lint-checked]`: fleet's `pbp-complexity` scores Python and PHP, and godot-guard 0.6+'s `complexity --json` scores GDScript. `bin/sync` installs both; without one, the coverage note lists its files as not measured. In a Godot repository with a `.godot-guard.yml`, the script asks godot-guard 0.2+ (`PBP_GODOT_GUARD`, the repository's `.venv/bin/godot-guard`, or `PATH`) to `check --json` the changed scripts, and never reads its config itself: godot-guard's limits tighten GDScript's, and each excess in a script it checks takes its verdict, `[lint: error]`, `[lint: warning]`, or `[lint passes]` (the ratchet baseline allows it, or the rule is off). Scripts it excludes or does not scan stay `[not lint-checked]`. Without godot-guard 0.2+, every GDScript excess stays `[not lint-checked]` and the coverage note says the repository's limits were not applied.

Run it once through the host's validation queue, never inside another host-check. It ends with `Result: N functions over threshold among M changed functions in F changed source files (...)`, followed by an `INCOMPLETE:` line when any changed file went unmeasured; `0 functions over threshold` with no `INCOMPLETE:` line is a complete measurement. Use `--over-only` for a large range and `--all` to include unchanged functions in changed files. If the script fails or a coverage note says files were not measured, report it and mark complexity coverage incomplete rather than estimating a score.

Classify each excess by its tag, recording the actual score, limit, function, and location. If both limits are exceeded in one function, report one finding naming both rules and scores.

- `[lint: error]`, or `[lint: warning]` where the lint script runs `--deny-warnings` (NJ Homes Next does): a **High / lint failure**. The PR fails lint until it is fixed; name the failing rule and point to the lint result rather than re-arguing the score.
- `[lint passes]` or `[not lint-checked]`: a **Medium / violation**. When the repository's own check also fails it, it is a High / lint failure. When the repository's checker scores the same function differently, report the skill's measurement and name the difference. godot-guard scores GDScript exactly as this skill does. For `[lint passes]`, the coverage notes name the config gap (a looser max such as DCAid's 12 and 24, a warning-level rule); report it alongside the finding.
- Files the script could not score are not passes. A repository's deliberate scope exclusion, such as Receipt Hub turning both rules off for tests, evals, and generated code, is listed as out of scope in coverage. A file with no measurer is a coverage gap.

Lint guarantees the number where it runs, so the audit's main job in an enforced repository is the ways around it. Inspect the diff for each, and report each as `pedro/complexity-evasion` at the priority of the excess it hides:

- New suppressions naming a complexity or file-length rule (`complexity`, `*/cognitive-complexity`, `max-lines`, `C901`, gdlint's `max-file-lines`): `oxlint-disable`, `eslint-disable`, `# noqa`, `# gdlint: disable=`, `@phpstan-ignore`, including file-level suppressions and ones that name no rule.
- Configuration changes that raise a complexity max, lower its level, turn it off, narrow its file scope, add ignore patterns covering application code, or add entries to a complexity allowlist.
- Splits made only to pass: a helper that receives the caller's state and returns a flag the caller branches on again, branches that move into a lookup or callback map without becoming simpler, or one-use functions whose names restate their bodies. Compare the before and after control flow; a split that leaves the reader tracing the same decisions across more functions is evasion even though both scores pass.

Recommend a smaller named function or flatter control flow (early returns, a domain helper that owns a decision, a lookup that replaces a real case analysis) that preserves behavior, branch laziness, and type narrowing. Recommend a split only when it simplifies the reader's path, never to lower a number.
