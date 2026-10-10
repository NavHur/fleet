---
name: pedro-best-practices
description: Manually audit repositories or PRs in React, Svelte, Godot (GDScript), Python, or PHP against Pedro's eight-input interface cap, component ownership, complexity limits, two-line comment cap, readability preferences, and each language's performance guidance. Report evidence-backed findings and coverage gaps in the conversation and on the matching GitHub pull request.
---

# Pedro best practices

Audit code without modifying it, combining Pedro's interface, ownership, complexity, comment-length, and readability preferences with performance guidance for each language in scope. Return findings in the conversation and publish one summary comment on the matching GitHub PR. Explicit invocation authorizes that comment unless the user requests a local-only audit. Code changes, commits, pushes, and review approval or change-request submissions remain outside this workflow.

## PR size requests

For an audit or explanation of Pedro's PR or layer size rule, read the "PR and
stack size" section in `~/.codex/AGENTS.md` and the installed
`split-stacked-prs` skill and its `scripts/diff_budget.py`. This is a separate
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
4. Measure complexity once with `scripts/measure_complexity.py` (details under "Complexity limits"), passing any stricter limit the repository documents, and check the diff for ways around the limits. For Godot scope, also run `scripts/godot_interface.py` with the same range.
5. Work through each in-scope reference's performance categories in order. Mark categories inapplicable where the code lacks those features. Read the detailed rule before validating a candidate, and trace the affected execution paths.
6. Validate candidates against actual code and configuration. Pedro's explicit preferences govern the audit; performance guidance informs applicable recommendations. A category's impact label is an investigation priority, not automatic finding severity. Account for compiler and engine optimizations, bundler and export configuration, and framework support. Distinguish measured costs from inferred costs. Performance and ownership findings need a concrete consequence or justified opportunity. A syntactically confirmed nested conditional is sufficient for its readability finding, and a measured complexity excess is sufficient for a complexity violation.

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

It lists each long comment touching a changed line (`--all` for the rest of the changed files) with its prose count, `(file header)` when it sits above the first line of code, and `[lint: <rule>]` when the file's `.oxlintrc.json` enables a `no-long-comment` rule, otherwise `[not lint-checked]`. Read each one before reporting it: the scanner works line by line outside Python, so a `//` line inside a template literal can be a false positive.

- A tagged comment is a **High / lint failure** when the repository's lint fails it; name the rule.
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
- **Python, GDScript, PHP**: the skill's analyzers, tagged `[not lint-checked]`. GDScript needs a Python with gdtoolkit (the repository's virtualenv, `PBP_GDTOOLKIT_PYTHON`, or the setup the coverage note prints); PHP needs `php` on `PATH`. In a Godot repository with a `.godot-guard.yml`, its limits tighten GDScript's and each excess is tagged by godot-guard's lint: `[lint passes]` when the ratchet baseline still allows it, `[lint: error]` otherwise. Lambdas, property accessors, and repeated names stay `[not lint-checked]`, because godot-guard keys them differently.

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

## Combined report

Lead with the most consequential confirmed findings. For each, include:

- Category and rule ID: `pedro/eight-prop-cap` for React and Svelte component count violations, `pedro/godot-interface-cap` for Godot script count violations, `pedro/component-ownership` for evidenced interface design findings, `pedro/cognitive-complexity` and `pedro/cyclomatic-complexity` for complexity violations (naming the repository rule, such as `dca/cognitive-complexity`, when lint fails), `pedro/complexity-evasion` for suppressions, loosened config, or splits made only to pass, `pedro/no-nested-ternary` for the advisory readability preference, `pedro/long-comment` for comments over two lines of prose, and the reference's rule ID for performance findings.
- Clickable file and line, unit (component, scene script, function), and concrete evidence.
- Impact and a focused recommendation; distinguish policy violations from performance defects or optimization opportunities.

For cap violations, include the exact count and the counted input names, or a proven lower bound when the complete contract is unknown. Order cap violations by count within each rule. For interface recommendations, show a concise proposed caller or before/after contract and explain what responsibility or coordination it removes. Distinguish a count violation from an ownership finding even when they concern the same unit; combine their explanation when the root cause is shared.

Finish with inspected unit counts per language, a compact status for every performance category of every in-scope reference, checks actually performed, and unresolved contracts or coverage gaps. Categories may be reviewed with no findings, have findings, be inapplicable, or remain incomplete. Claim a clean audit only for fully inspected scope with no confirmed findings and no unresolved relevant contracts. An agent audit is not a deterministic enforcement guarantee.

## GitHub publication

Use an explicit PR target when supplied; otherwise resolve the open PR for the current branch in its actual GitHub repository. Verify the repository, PR number, base, and head SHA before publishing. If no matching PR exists, return the audit locally and state that no comment was posted. If multiple targets remain plausible, prepare the report and ask which PR to use. Do not create a PR as part of an audit.

Publish the combined report as a normal PR conversation comment after validating findings. Preserve the requested audit scope: a whole-repository audit attached to a PR is still a whole-repository audit. Clearly separate findings in the PR changes from existing issues elsewhere. Record the reviewed commit, base when relevant, and working-tree state. Label findings that depend on uncommitted changes as local-only evidence; never present them as findings in the pushed PR. Use GitHub source permalinks at the reviewed SHA for committed evidence, not local filesystem links. For local-only evidence, provide the path and line as text with a brief excerpt.

Recheck the remote head before posting. If it changed, label the report as reviewing the earlier snapshot, or review the new changes before claiming current coverage. Do not silently attribute results to an unreviewed commit.

Use this comment structure, replacing the placeholders with actual results:

```markdown
## Pedro best practices

> [!WARNING]
> Found N confirmed findings: X interface-cap violations, Y ownership findings, C complexity violations (L failing lint), E complexity evasions, K long comments, Z readability advisories, and W performance findings. Coverage: complete/incomplete.

Reviewed `<sha>` · Scope: <repo/path/PR changes> · Languages: <languages in scope> · Base: <base if applicable>
Working tree: <clean or local changes included>

| ID | Priority / kind | Rule | Location | Finding and recommendation |
| --- | --- | --- | --- | --- |
| PBP-1 | Medium / ownership | `pedro/component-ownership` | [Component](permalink) | Concrete evidence and the responsibility the proposed change removes. |

### Evidence

<Counted input names, focused before/after examples, and measured versus inferred performance costs, keyed to finding IDs. Omit this section if the table contains all necessary evidence.>

### Coverage

| Check | Result |
| --- | --- |
| Interface cap (per language) | <result> |
| Interface ownership | <result> |
| Nested conditionals | <result> |
| Comment length (2 lines of prose) | <result; say whether lint enforces it or the audit scanned it> |
| Cognitive complexity (limit 8, or the repository's stricter limit) | <result; say whether lint enforces it or the audit measured it> |
| Cyclomatic complexity (limit 16, or the repository's stricter limit) | <result; same> |
| Complexity evasion | <suppressions, config changes, and split-only refactors checked> |
| <Each performance category of each in-scope reference> | <result> |

Inspected: <unit counts per language>. Checks performed: <actual checks>.
Coverage gaps: <unresolved contracts, unmeasured files, languages without a reference, local-only evidence, or unmeasured costs>.
```

Choose the alert from the result: `[!CAUTION]` when a complexity excess or long comment fails the repository's lint; `[!WARNING]` when other confirmed policy, complexity, ownership, or performance findings exist; `[!NOTE]` when the only findings are nested-conditional advisories or long comments that lint does not fail; `[!IMPORTANT]` for incomplete coverage with no findings; and `[!NOTE]` for no findings with complete static coverage. The warning alert is a report summary, not a seven/eight-input warning tier. When no findings exist, say so and omit the findings table rather than inventing rows. Escape pipes inside table cells and keep long evidence outside the table. Avoid implying that a static audit is CI enforcement or a runtime performance measurement.

Use the available GitHub connector or `gh` to post. For `gh`, write the exact Markdown to a temporary file and use `--body-file` with the verified repository and PR number. On an uncertain response or retry, read the PR comments first and reuse the already-published comment for this run rather than duplicating it. A later intentional audit gets a new comment; preserve previous audit history. Verify the published body and return its URL with the main findings in the conversation. If publication fails, retain the prepared report, explain the failure, and do not claim it was posted.
