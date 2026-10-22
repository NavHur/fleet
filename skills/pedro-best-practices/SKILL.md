---
name: pedro-best-practices
description: "Audit a repo or PR (React, Svelte, Godot, Python, PHP) against Pedro's interface cap, ownership, complexity, comment, error-handling, readability, and performance rules, and post the report on the PR."
---

# Pedro best practices

Audit code without modifying it, combining Pedro's interface, ownership, complexity, comment, error-handling, and readability preferences with performance guidance for each language in scope. Return findings in the conversation and publish one summary comment on the matching GitHub PR. Explicit invocation authorizes that comment unless the user requests a local-only audit. Code changes, commits, pushes, and review approval or change-request submissions remain outside this workflow.

## PR size requests

For an audit or explanation of Pedro's PR or layer size rule, read the
installed `split-stacked-prs` skill, its `references/size-policy.md`, and its
`scripts/diff_budget.py`. This is a separate
personal policy from the code audit below. For a policy-only request, return
findings in the conversation without running the audit or posting a PR
comment. Claude's installed wrapper reads this same canonical skill.

## Scope and languages

With no scope argument, audit the current repository's first-party application code, including relevant working-tree changes. Accept a path, explicit base, or PR scope; use a PR's actual base and follow changed shared contracts to affected consumers. Record the scope, revisions, and working-tree state reviewed. Exclude dependencies, generated output, vendored add-ons, and fixtures unless requested.

Read the reference for every language in scope before auditing it. Each one holds that language's interface cap, ownership patterns, mappings for the shared rules, and performance categories:

| Files in scope | Reference |
| --- | --- |
| React (`.tsx`, `.jsx`, React hooks and utilities) | [references/react.md](references/react.md) |
| Svelte (`.svelte`, runes in `.svelte.ts`) | [references/svelte.md](references/svelte.md) |
| Godot (`.gd`, scenes) | [references/godot.md](references/godot.md) |
| Python (`.py`) | [references/python.md](references/python.md) |
| PHP (`.php`) | [references/php.md](references/php.md) |

TypeScript and JavaScript outside React and Svelte get the shared rules below with no interface cap and no performance reference. A language with no reference gets the shared rules and is listed as a coverage gap for its interface and performance checks.

When the user requests a reviewer model or agent, follow `~/.config/t3-orchestration.md` and include the applicable audit instructions, references, scope, and requested role in its complete brief. Delegate read-only investigation; the invoking thread validates findings and owns any authorized PR comment. Preserve requested model and effort choices.

## Audit

1. Inspect repository instructions, framework and engine versions, lint and analyzer configuration, documented limits, and existing patterns (data fetching, caching, scene structure). Inventory the units in scope per language: components, routes, hooks, scenes and scripts, modules, classes. Track inspected units and unresolved contracts; a name-based search alone is not a complete inventory.
2. Check every scoped unit's public interface against its language's cap, using that reference's counting rules. More than eight is a violation; seven and eight are allowed, with no warning tier. Trace declarations and callers before reporting a count. Assess interface ownership with the criteria below, including units already within the cap; a compliant count does not establish a good design.
3. Inspect every scoped conditional expression for nesting using the rule below. Record each outer expression once. Run `scripts/long_comments.py` with the audit's range for the comment cap.
4. Read [references/construction-rules.md](references/construction-rules.md), then apply its three construction rules: every catch, except, and failure-returning call in scope, every function parameter that selects a mode, and every comment beside a changed line.
5. Measure complexity once with `scripts/measure_complexity.py` (details under "Complexity limits"), passing any stricter limit the repository documents, and check the diff for ways around the limits. For Godot scope, also run `scripts/godot_interface.py` with the same range.
6. Work through each in-scope reference's performance categories in order. Mark categories inapplicable where the code lacks those features. Read the detailed rule before validating a candidate, and trace the affected execution paths.
7. Validate candidates against actual code and configuration. Pedro's explicit preferences govern the audit; performance guidance informs applicable recommendations. A category's impact label is an investigation priority, not automatic finding severity. Account for compiler and engine optimizations, bundler and export configuration, and framework support. Distinguish measured costs from inferred costs. Performance and ownership findings need a concrete consequence or justified opportunity. A syntactically confirmed nested conditional is sufficient for its readability finding, and a measured complexity excess is sufficient for a complexity violation.

Use a language's own compiler or parser when it resolves a hard contract, loading each project once per audit rather than once per file. Keep unresolved contracts visible instead of guessing counts. Use focused checks when they resolve a candidate; turn a static audit into a full build, benchmark, game run, or browser run only for a concrete need.

## Nested conditional expressions

Flag `pedro/no-nested-ternary` whenever one conditional expression contains
another in its condition or either branch: `a ? b : c ? d : e` in JS, TS, and
PHP, `x if a else (y if b else z)` in Python and GDScript, nested JSX or
Svelte template expressions, and nesting hidden by parentheses. Independent
conditionals in one statement are not nested unless one contains another.
Shorthand operators (`??`, PHP's `?:`) are not conditional expressions.

This is Pedro's readability preference, not a repository standard or a claim
about the team's conventions. Report it as Low-priority advisory feedback and
never call it a merge blocker. If the expression also causes incorrect behavior
or a measured performance problem, report that separately under the applicable
rule.

Recommend the smallest clearer form for the surrounding code: an early return,
named helper, `if`/`else`, `switch`/`match`, or lookup table. Preserve branch
laziness, evaluation order, type narrowing, and rendered output. Record one
finding for the outer expression rather than one finding per nested node.

## Long comments

A comment holds at most **two lines of prose**; three or more is `pedro/long-comment`. A comment is a block comment or an unbroken run of line comments that each own their line, so a run of ten `//` lines is one finding. Blank lines, separator rules, lone references (a URL, `See docs/...`, a ticket ID), and tooling directives are not prose. Doc comments (`/** */`, Python docstrings, GDScript `##`), comments after code on the same line, and license headers are exempt. NJ Homes Next, Receipt Hub, and govstructure lint the same cap (`*/no-long-comment`); Godot repositories with a `.godot-guard.yml` do too (godot-guard's `long-comment`, which exempts a file's header block). Find them with the bundled script, which takes the same ranges as `measure_complexity.py`:

```sh
<this skill's directory>/scripts/long_comments.py BASE HEAD   # BASE alone for the working tree, EMPTY HEAD for every file
```

It lists each long comment touching a changed line (`--all` for the rest of the changed files) with its prose count, `(file header)` when it sits above the first line of code, and `[lint: <rule>]` when the file's `.oxlintrc.json` enables a `no-long-comment` rule, otherwise `[not lint-checked]`. In a Godot repository with a `.godot-guard.yml`, godot-guard itself judges each GDScript comment in the scripts it checks (as `measure_complexity.py` finds it, below): `[lint: godot-guard/long-comment]` when its `check` reports the comment (`, warning` at warn level), `[lint passes: godot-guard/long-comment]` when it does not, because of its header exemption, a looser `comment-lines` cap, or the ratchet baseline. Read each one before reporting it: the scanner works line by line outside Python, so a `//` line inside a template literal can be a false positive.

- A tagged comment is a **High / lint failure** when the repository's lint fails it; name the rule.
- `[lint passes: <rule>]` is a **Low / violation** the repository's lint accepts; name why in coverage.
- Any other long comment is a **Low / violation**. A file header in a repository that exempts headers is out of scope; list it in coverage.
- Ways around the cap are `pedro/long-comment` too: one comment split into short runs with blank code lines, prose moved into a doc comment that documents no API, or a long trailing comment.

Recommend by what the comment does. Rationale for why the code is this way moves to the repository's docs or an ADR, leaving a one-line pointer; a comment that narrates what the code does becomes a better name, an extracted function, or simpler code; a warning about a silent failure mode stays, compressed to two lines.

## Complexity limits

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

## Interface ownership

Keep the interface count and interface quality separate. A nested object or structured value still counts as one input. Recommend grouping only when the group is a real concept, and approve a refactor for the coordination it removes rather than for a lower count. Assess whether callers have fewer decisions to make and less implementation detail to coordinate.

Trace values from where callers create them to where the unit consumes them. For a refactor, compare both sides before and after when history is available. For an existing interface, ground the assessment in its current callers rather than guessing why it was written.

- Keep cohesive values: an amount with its period, a link's label with its destination, an existing domain entity, a typed Resource of related settings. Presentation models and copy or style groups can also be useful when they provide a clear contract. Object creation at a call site or immediate destructuring alone is not a defect.
- Investigate bags that merely regroup independent fields while callers still coordinate the same callbacks, signals, references, IDs, or matching settings. Names such as `actions`, `options`, and `appearance` neither prove nor disprove cohesion. Report the concrete burden, not the name or nesting depth.
- Prefer removing dependencies: derive internal IDs and settings inside their owner, pass a resolved value instead of the whole source it came from, combine operations that must happen together, and use explicit variants for fixed combinations.
- Move behavior with its lifecycle. If a unit takes ownership of timers, subscriptions, focus, signal connections, or interaction state, explain how cancellation, cleanup, navigation, freeing, and accessibility remain correct. Introduce shared state (context, stores, autoloads) only when it reduces actual coordination; moving the same bag into shared state is not sufficient.

Before recommending an interface change, answer: **Would we choose this interface without the eight-input limit?** Name the responsibility that moves, the caller work that disappears, or the meaningful concept the grouped value models. If none applies, report the excessive contract as an unresolved design issue rather than proposing a cosmetic fix. Keep the cap and no-warning policy; do not flatten nested fields into a second numerical limit. Each reference shows its language's ownership patterns and examples.

## Report and publication

After validating findings, read [references/report.md](references/report.md) before writing the report: it holds each finding's fields and rule IDs, the PR comment template and how to choose its alert, and how to resolve the PR, post, and verify the comment.
