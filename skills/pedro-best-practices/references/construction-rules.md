# Construction rules

These three rules apply the **fail-loudly** (`~/.agents/skills/principle-fail-loudly/SKILL.md`) and **name-the-meaning** (`~/.agents/skills/principle-name-the-meaning/SKILL.md`) principles; read both before auditing. In a PR or range audit they cover the changed code; in a whole-repository audit, the units inspected for the other rules.

## `pedro/swallowed-error`

A failure that disappears: a catch or except that neither rethrows, translates, nor recovers with a real alternative; a rethrow that drops the original (no `cause`, no `from`, no `previous`); a fallback (`?? []`, `|| 0`, `catch { return null }`) standing in for a value the code requires; a failure logged at one layer and then ignored; an unchecked error return. Find the sites, then read each one:

| Language | Sites | Repository lint that catches some |
| --- | --- | --- |
| JS, TS, Svelte | `catch` blocks, `.catch(` handlers, promises neither awaited nor returned, `??`/`\|\|` defaults on required values | `preserve-caught-error`, `no-empty`, `no-useless-catch`, `typescript/no-floating-promises`, `typescript/only-throw-error` |
| Python | `except` clauses, `contextlib.suppress` | ruff `BLE001`, `S110`, `S112`, `B904`, `TRY` |
| PHP | `catch` blocks, `@` error suppression, ignored `false` returns | PHPStan's exception rules where configured |
| GDScript | `Error` returns left unchecked (`FileAccess.open`, `load`, `connect`, `ResourceSaver.save`), `push_error` followed by carrying on | none |

Record the failure that goes unseen and who would have seen it: "a database outage renders as 'no listings in this county'." A catch that recovers on purpose, or a default where absence is a legitimate case, is not a finding; check the call sites to tell which. **Medium / violation**; **High / lint failure** when the repository's lint fails it (name the rule). Recommend the smallest honest form: rethrow with context and the cause, move the expected outcome into the return type, or delete the catch and let the error reach the boundary that reports it.

## `pedro/flag-argument`

A boolean or string-literal parameter of a function, method, or hook that selects between behaviors: the body branches on it to do different work, and call sites read `exportReport(rows, true)`. A boolean that is data (`setVisible(isVisible)`) is not one. Component boolean props belong to the React reference (Vercel's `architecture-avoid-boolean-props`) and the ownership rule, not here; report each case once. Python's ruff `FBT` rules flag boolean positional parameters, a superset to read through. **Low / advisory**, like nested conditionals: Pedro's readability preference, never a merge blocker. Recommend named functions or explicit variants that share a helper, showing the call sites before and after.

## `pedro/stale-comment`

A comment beside changed code that the code now contradicts: it names a parameter, value, branch, or behavior that no longer exists, or states an invariant the change broke. Read each comment within a few lines of a changed line, plus doc comments on changed functions, and confirm the contradiction against the code; report only comments that are false, not ones that are vague. **Medium / violation**: the next change trusts it. Quote the comment and the line that contradicts it, and recommend the corrected text or deletion.
