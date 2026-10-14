---
name: principle-fail-loudly
description: "Apply when writing or reviewing catch/except blocks, fallback values, or a function's failure contract. Classify each failure as bad input, an expected outcome, or a bug; handle it where something can act on it, keep its cause, and let bugs crash loudly instead of returning a plausible default."
disable-model-invocation: true
---

# Fail Loudly

A failure is either seen or hidden. Every failure that matters ends where someone sees it, carrying enough context to debug it from one log line or error message.

**Why:** A swallowed error turns one visible bug into a distant, silent one: the empty list renders as "no results", the `0` lands in a total, and the report that should have failed ships wrong. Code agents write these fallbacks by reflex because they make the happy path run.

**Classify the failure first:**

1. **Bad input at a boundary** (a form, a request, a file, an API response). Validate it there and return or raise an error the caller can show or act on. See [Boundary Discipline](../principle-boundary-discipline/SKILL.md).
2. **An expected outcome** (not found, already taken, permission denied, rate-limited). It belongs in the function's contract: a result union, a domain error type, a documented exception. Callers handle it as an ordinary case.
3. **A bug or impossible state** (a broken invariant, an unhandled variant, a value that should exist). Throw or assert with the facts that broke. Let it crash; it is not recoverable here.

**Handling:**

- **Catch with a purpose.** A catch block does one of three things: adds context and rethrows, translates the error to the caller's abstraction at a layer boundary, or recovers with a real alternative (a retry, a cached copy, a degraded mode the user can see). Anything else propagates.
- **Keep the cause.** Rethrow with the original attached (`new Error(msg, { cause })`, `raise ... from err`, `throw new X(msg, previous: $e)`) and the identifiers needed to debug: the record id, the path, the request.
- **A default is a decision.** `?? ""`, `|| 0`, `catch { return [] }`, `except Exception: pass` each claim the absence is normal. Write a default only where the absence is a legitimate case with a meaningful value; where the value is required, fail.
- **Log or rethrow, once.** One layer reports a failure: logging at every level duplicates it; logging and continuing hides it.
- **Keep the normal path in front.** Error handling sits at the edges of a routine (guard clauses, one catch at the boundary), not woven through every line. One failure convention per module.

**The test:** If this fails in production, who sees it, and does what they see name the cause? Can a caller tell an empty result from a failed one?
