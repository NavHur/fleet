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
5. Measure complexity once with `scripts/measure_complexity.py` (details in [references/complexity.md](references/complexity.md)), passing any stricter limit the repository documents, and check the diff for ways around the limits. For Godot scope, also run `scripts/godot_interface.py` with the same range.
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

Read [references/complexity.md](references/complexity.md) before step 5: how the audit measures complexity, classifies an excess, and finds the ways around the limits.

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
