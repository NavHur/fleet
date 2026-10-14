---
name: typescript-best-practices
description: TypeScript best practices. Use whenever reading or editing `.ts` or `.tsx` files, or when the user asks for TypeScript implementation or review. Do not use for JavaScript-only work.
---

# TypeScript best practices

Apply the **type-system-discipline** principle (`~/.agents/skills/principle-type-system-discipline/SKILL.md`) first; this skill grounds it in TypeScript syntax.

Repository lint outranks this skill where it is stricter. NJ Homes Next, Receipt Hub, and DCAid run the `anti-slop` oxlint plugin: no `unknown` parameters or returns, `typeof` only inside type guards, and a `SAFETY:` comment before every `as`. The examples in `references/patterns.md` pass it.

| Rule | Summary |
|------|---------|
| Discriminated unions | Model variants with a `kind` literal discriminant so impossible states can't be represented. No optional-field bags. |
| Branded types | Brand primitives with `& { readonly __brand: "X" }` so they can't be mixed up. Validate once at creation. |
| Constructive modeling | Build the shape so the illegal value can't be constructed. `[T, ...T[]]` for non-empty, `[T, T][]` for even length, `start` plus `duration` for a range. Not a runtime guard, not a wish for refinement types. |
| Simplest total type | Keep `T[]` while every operation on it stays total. Strengthen to `NonEmpty<T>` only where the loose type forces `!`, a cast, or a "should never happen" throw. |
| `unknown` over `any` | External data is `unknown` only where it enters: decode it there with the repository's schema library (zod in the DCA repos) and pass the domain type inward. `any` disables type checking everywhere it touches. |
| No `as` casts | Every `as` is a runtime crash waiting. Cast only after validation, with a `SAFETY:` comment stating the invariant that was checked. |
| Narrowing hierarchy | Discriminant switch > `in` operator > `instanceof` > user-defined type guard (where `typeof` lives) > `as`. |
| Type guards | Must verify the claim. A lying guard is worse than `as` because the bug hides behind a name that says it's safe. Name them `isX` or `hasX`. |
| Exhaustiveness | Inline `const _exhaustive: never = x;` in default arms so the compiler errors when a new variant is added. |
| `satisfies` over `as` | Validates the value without widening literal types. |
| Boundary validation | Validate where data crosses in; trust types inside. See the **boundary-discipline** principle (`~/.agents/skills/principle-boundary-discipline/SKILL.md`). |
| Schema-derived types | Reach for `Pick`/`Omit`/`Parameters`/`ReturnType`/`Awaited`/`typeof` before declaring a new interface. |
| Object args | Pass objects, not positional, so argument order is self-documenting. Skip on hot paths (per-frame render, tokenizers, parsers). |
| Real tests | Don't mock what you can run. Prefer the framework's real test primitives with leak/disposable checks, and verify UI in a running build. Mock only what you can't run locally. |
| Errors | Throw `Error` subclasses with `{ cause }`; return a result union for expected outcomes; no fallback value standing in for a required one. See the **fail-loudly** principle (`~/.agents/skills/principle-fail-loudly/SKILL.md`). |
| Structured telemetry | Prefer structured logger diagnostics with enough context to debug from an id. No `console.log` in shipped code. |

Examples: `references/patterns.md`.
