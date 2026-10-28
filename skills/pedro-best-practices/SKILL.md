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
2. Check every scoped unit's public interface against its language's cap, using that reference's counting rules. More than eight is a violation; seven and eight are allowed, with no warning tier. Trace declarations and callers before reporting a count. Assess interface ownership with the criteria in rules.md, including units already within the cap; a compliant count does not establish a good design.
3. Inspect every scoped conditional expression for nesting using the rule in rules.md. Record each outer expression once. Run `scripts/long_comments.py` with the audit's range for the comment cap.
4. Read [references/construction-rules.md](references/construction-rules.md), then apply its three construction rules: every catch, except, and failure-returning call in scope, every function parameter that selects a mode, and every comment beside a changed line.
5. Measure complexity once with `scripts/measure_complexity.py` (details in [references/complexity.md](references/complexity.md)), passing any stricter limit the repository documents, and check the diff for ways around the limits. For Godot scope, also run `scripts/godot_interface.py` with the same range.
6. Work through each in-scope reference's performance categories in order. Mark categories inapplicable where the code lacks those features. Read the detailed rule before validating a candidate, and trace the affected execution paths.
7. Validate candidates against actual code and configuration. Pedro's explicit preferences govern the audit; performance guidance informs applicable recommendations. A category's impact label is an investigation priority, not automatic finding severity. Account for compiler and engine optimizations, bundler and export configuration, and framework support. Distinguish measured costs from inferred costs. Performance and ownership findings need a concrete consequence or justified opportunity. A syntactically confirmed nested conditional is sufficient for its readability finding, and a measured complexity excess is sufficient for a complexity violation.

Use a language's own compiler or parser when it resolves a hard contract, loading each project once per audit rather than once per file. Keep unresolved contracts visible instead of guessing counts. Use focused checks when they resolve a candidate; turn a static audit into a full build, benchmark, game run, or browser run only for a concrete need.

## Rules

Read [references/rules.md](references/rules.md) before step 2: nested conditional expressions, long comments, and interface ownership.

## Complexity limits

Read [references/complexity.md](references/complexity.md) before step 5: how the audit measures complexity, classifies an excess, and finds the ways around the limits.

## Report and publication

After validating findings, read [references/report.md](references/report.md) before writing the report: it holds each finding's fields and rule IDs, the PR comment template and how to choose its alert, and how to resolve the PR, post, and verify the comment.
