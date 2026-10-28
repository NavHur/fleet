# Pedro's rules

The audit's steps and every rule it applies. A `pedro-best-practices` audit and a review-loop audit reviewer both work from this file; script paths are relative to the skill's directory, one level up.

## Languages

Read the reference for every language in scope before auditing it. Each one holds that language's interface cap, ownership patterns, mappings for the shared rules, and performance categories:

| Files in scope | Reference |
| --- | --- |
| React (`.tsx`, `.jsx`, React hooks and utilities) | [react.md](react.md) |
| Svelte (`.svelte`, runes in `.svelte.ts`) | [svelte.md](svelte.md) |
| Godot (`.gd`, scenes) | [godot.md](godot.md) |
| Python (`.py`) | [python.md](python.md) |
| PHP (`.php`) | [php.md](php.md) |

TypeScript and JavaScript outside React and Svelte get the shared rules below with no interface cap and no performance reference. A language with no reference gets the shared rules and is listed as a coverage gap for its interface and performance checks.

## Audit steps

1. Inspect repository instructions, framework and engine versions, lint and analyzer configuration, documented limits, and existing patterns (data fetching, caching, scene structure). Inventory the units in scope per language: components, routes, hooks, scenes and scripts, modules, classes. Track inspected units and unresolved contracts; a name-based search alone is not a complete inventory.
2. Check every scoped unit's public interface against its language's cap, using that reference's counting rules. More than eight is a violation; seven and eight are allowed, with no warning tier. Trace declarations and callers before reporting a count. Assess interface ownership with the criteria below, including units already within the cap; a compliant count does not establish a good design.
3. Inspect every scoped conditional expression for nesting using the rule below. Record each outer expression once. Run `scripts/long_comments.py` with the audit's range for the comment cap.
4. Read [construction-rules.md](construction-rules.md), then apply its three construction rules: every catch, except, and failure-returning call in scope, every function parameter that selects a mode, and every comment beside a changed line.
5. Measure complexity once with `scripts/measure_complexity.py` (details in [complexity.md](complexity.md)), passing any stricter limit the repository documents, and check the diff for ways around the limits. For Godot scope, also run `scripts/godot_interface.py` with the same range.
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

## Interface ownership

Keep the interface count and interface quality separate. A nested object or structured value still counts as one input. Recommend grouping only when the group is a real concept, and approve a refactor for the coordination it removes rather than for a lower count. Assess whether callers have fewer decisions to make and less implementation detail to coordinate.

Trace values from where callers create them to where the unit consumes them. For a refactor, compare both sides before and after when history is available. For an existing interface, ground the assessment in its current callers rather than guessing why it was written.

- Keep cohesive values: an amount with its period, a link's label with its destination, an existing domain entity, a typed Resource of related settings. Presentation models and copy or style groups can also be useful when they provide a clear contract. Object creation at a call site or immediate destructuring alone is not a defect.
- Investigate bags that merely regroup independent fields while callers still coordinate the same callbacks, signals, references, IDs, or matching settings. Names such as `actions`, `options`, and `appearance` neither prove nor disprove cohesion. Report the concrete burden, not the name or nesting depth.
- Prefer removing dependencies: derive internal IDs and settings inside their owner, pass a resolved value instead of the whole source it came from, combine operations that must happen together, and use explicit variants for fixed combinations.
- Move behavior with its lifecycle. If a unit takes ownership of timers, subscriptions, focus, signal connections, or interaction state, explain how cancellation, cleanup, navigation, freeing, and accessibility remain correct. Introduce shared state (context, stores, autoloads) only when it reduces actual coordination; moving the same bag into shared state is not sufficient.

Before recommending an interface change, answer: **Would we choose this interface without the eight-input limit?** Name the responsibility that moves, the caller work that disappears, or the meaningful concept the grouped value models. If none applies, report the excessive contract as an unresolved design issue rather than proposing a cosmetic fix. Keep the cap and no-warning policy; do not flatten nested fields into a second numerical limit. Each reference shows its language's ownership patterns and examples.

## Findings

Lead with the most consequential confirmed findings. For each, include:

- Category and rule ID: `pedro/eight-prop-cap` for React and Svelte component count violations, `pedro/godot-interface-cap` for Godot script count violations, `pedro/component-ownership` for evidenced interface design findings, `pedro/cognitive-complexity` and `pedro/cyclomatic-complexity` for complexity violations (naming the repository rule, such as `dca/cognitive-complexity`, when lint fails), `pedro/complexity-evasion` for suppressions, loosened config, or splits made only to pass, `pedro/no-nested-ternary` for the advisory readability preference, `pedro/long-comment` for comments over two lines of prose, `pedro/swallowed-error`, `pedro/flag-argument`, and `pedro/stale-comment` for the construction rules, and the reference's rule ID for performance findings.
- Clickable file and line, unit (component, scene script, function), and concrete evidence.
- Impact and a focused recommendation; distinguish policy violations from performance defects or optimization opportunities.

For cap violations, include the exact count and the counted input names, or a proven lower bound when the complete contract is unknown. Order cap violations by count within each rule. For interface recommendations, show a concise proposed caller or before/after contract and explain what responsibility or coordination it removes. Distinguish a count violation from an ownership finding even when they concern the same unit; combine their explanation when the root cause is shared.

## Coverage

Give every check below a status: clean (reviewed with no findings), findings, inapplicable, or incomplete. Finish with inspected unit counts per language, the checks actually performed, and unresolved contracts or coverage gaps. Claim a clean audit only for fully inspected scope with no confirmed findings and no unresolved relevant contracts. An agent audit is not a deterministic enforcement guarantee.

- Interface cap (per language)
- Interface ownership
- Nested conditionals
- Comment length (2 lines of prose): say whether lint enforces it or the audit scanned it
- Swallowed errors: sites inspected per language, and which lint rules the repository enables
- Flag arguments
- Stale comments: the comments beside changed lines checked
- Cognitive complexity (limit 8, or the repository's stricter limit): say whether lint enforces it or the audit measured it
- Cyclomatic complexity (limit 16, or the repository's stricter limit): the same
- Complexity evasion: the suppressions, config changes, and split-only refactors checked
- Each performance category of each in-scope reference
