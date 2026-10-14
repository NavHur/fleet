---
name: principle-name-the-meaning
description: "Apply when naming a function, variable, constant, or parameter, adding a boolean or mode argument, or editing code that has comments. Names state purpose, units, and effects; magic values get named constants; mode flags become separate functions; comments stay true."
disable-model-invocation: true
---

# Name the Meaning

A reader learns what code means from its names first and its bodies second. Put the meaning in the name, the type, or the constant, where the reader meets it, so they need not reconstruct it from the body or the call sites.

**Why:** A wrong or vague name is a defect waiting for its caller: `timeout` passed as seconds to a function that wants milliseconds, `getUser` that also writes a login timestamp, `render(true)` that nobody can read without opening `render`. Each costs every future reader a trip to the definition. See [Minimize Reader Load](../principle-minimize-reader-load/SKILL.md).

**Names:**

- **Purpose over mechanism.** Name the result or the action (`activeVouchers`, `archiveExpiredListings`), not how it is computed (`filteredList2`, `loopAndUpdate`).
- **Effects in the verb.** `get`, `find`, `compute`, `format`, `is` read as queries with no writes. A function that writes, sends, or mutates says so (`save`, `sync`, `apply`, `send`). When a routine both computes and acts, split the computation into a pure function the action calls.
- **Units in the name or the type.** `timeoutMs`, `priceCents`, `radiusMeters`, `createdAtUtc`. Brand the type where values in different units meet ([Type System Discipline](../principle-type-system-discipline/SKILL.md)).
- **Booleans read as yes/no questions, stated positively.** `isActive`, `hasPhotos`, `canEdit`, `shouldRetry`; `isEnabled`, not `isNotDisabled`.
- **One variable, one meaning.** A local keeps the meaning its name gives it for its whole life. A new meaning gets a new name.

**Constants:** A literal with domain meaning (a limit, a threshold, a status code, a sentinel, a retry count) gets a named constant at the narrowest scope that covers its uses: `MAX_UPLOAD_BYTES`, `INCOME_LIMIT_PERCENT_AMI`. Identities and self-evident literals (`0`, `1`, `-1` as "last", `100` in a percentage, `""` as an empty string) stay literal.

**Mode arguments:** A boolean or string-literal parameter that selects between behaviors (`exportReport(rows, true)`, `fetchListings({ includeArchived: true, mode: "admin" })`) is two or more routines sharing a signature. Split them into named functions (`exportReportCsv`, `exportReportPdf`) or explicit variants, and share the common part as a helper. A boolean that is data, not a mode (`setVisible(isVisible)`, `user.isAdmin`), stays. The tell: a call site that cannot be read without the parameter name, or a body whose first statement branches on the flag.

**Comments:** A comment names what the code cannot say: intent, a constraint, the reason for a surprising choice. It describes the code as it is now. When you change code, read the comments around the change and update or delete the ones it makes false.

**The test:** Could a reader predict what this does, what it changes, and what units its values are in from the names at the call site alone? Is every comment near your change still true?
