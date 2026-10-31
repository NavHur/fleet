# tsrs as the type checker for personal web repos

State as of 2026-10-31, tsrs 0.20.1. Sources: the
[oxc-project/tsrs](https://github.com/oxc-project/tsrs) repo and npm metadata.
Linting and formatting: [oxlint-vs-biome.md](oxlint-vs-biome.md).

## Decision

**Adopted 2026-10-31: tsrs replaces `tsc --noEmit` wherever a repo
type-checks under TypeScript 7.** Pin the exact version and run the default
mode in gates (CI, `make check`). `--fast` stays out of gates; `TSRS_FAST=1`
for the editor's language server is fine.

## What it is

A Rust port of the TypeScript 7 compiler and language server, ported
function by function from Microsoft's Go implementation (tsgo), maintained by
oxc-project ([README](https://github.com/oxc-project/tsrs#readme),
[announcement](https://blog.cloudflare.com/typescript-rust-port/)). 0.20.1
targets TypeScript 7.1 beta, pinned to upstream commit `3e9236361fa9`
([COMPATIBILITY.md](https://github.com/oxc-project/tsrs/blob/main/docs/COMPATIBILITY.md)).

## Maturity

- Repo created 2026-10-01. Releases every few days: 0.14.0 on 2026-10-11,
  0.20.1 on 2026-10-28
  ([releases](https://github.com/oxc-project/tsrs/releases)).
- Pull requests are closed to outside contributors; issues are open (8 open
  on 2026-10-31).
- Apache-2.0, a derivative of TypeScript; not affiliated with Microsoft.

## Correctness

Default mode treats tsgo as the spec: any difference in diagnostics, their
order, message text or exit code is a tsrs bug. The recorded beta validation
matches all 13,700 upstream error baselines, 12,998 `.types` and `.symbols`
baselines, and 13,626 JavaScript/declaration emit baselines, and it has been
run on a large private monorepo
([COMPATIBILITY.md](https://github.com/oxc-project/tsrs/blob/main/docs/COMPATIBILITY.md)).

## Speed and memory (first-party)

Measured on an Apple M3 Max against TypeScript 7.1 beta, medians of 10 runs
([bench/RESULTS.md](https://github.com/oxc-project/tsrs/blob/main/bench/RESULTS.md)):
about 2-4x faster in default mode and 3-6x with `--fast`, at roughly half the
peak memory. Example: `t3code-server` checks in 7.20 s with TypeScript 7.1,
1.73 s with tsrs and 1.19 s with `--fast`. The personal repos are small, so
expect seconds saved; none has been measured.

## `--fast`

`--fast` or `TSRS_FAST=1` trades exact tsgo parity for speed and memory
([USAGE.md](https://github.com/oxc-project/tsrs/blob/main/docs/USAGE.md#performance-options)):

| Setting | Default | `--fast` |
| --- | --- | --- |
| Checker threads | 4, like tsgo | One per core up to 16, at most 32; fewer for small programs; `--build` keeps 4 per project |
| Scheduling | tsgo's file assignment and order | Directory locality, work stealing, file splitting |
| Checker history | tsgo's | Canonical handling of some order-dependent cases |
| Extra checker caches | Off | Three more on |
| Type members | Eager | Lazy |
| `.d.ts` parsing | Eager | Lazy, with `skipLibCheck` or `noCheck` |
| Finished files | Kept | Freed on one-off `--noEmit` runs |

Why gates stay on the default:

- In known recursive-type and instantiation-limit cases, `--fast` can add or
  remove diagnostics, move them, or change the exit status.
- Its thread count scales with the machine, which fights host-check's
  per-job CPU budgets on shared hosts. Default mode's four checkers do not.
- Switching the preset rejects existing `.tsbuildinfo` caches.
- Peak memory can go either way: `--fast` used more than default tsrs on
  several benchmark projects.

It is a CLI option, not a `tsconfig.json` option. `--lsp` has no flag but
reads `TSRS_FAST=1` and enables part of the preset.

## Gaps

- **oxlint does not use it yet.** `oxlint --type-aware` runs the Go-based
  tsgolint. tsrs ships `tsrs-lint`, which passes all 61 pinned tsgolint
  rules, but the oxlint integration is open as
  [#378](https://github.com/oxc-project/tsrs/issues/378). Until it lands,
  each repo runs two TypeScript 7 implementations with different upstream
  pins.
- **Svelte and Astro.** Like tsc and tsgo, tsrs checks TS/JS only, so those
  repos keep `svelte-check` or `astro check` until they move to React.
- **CLI.** No `--init`, `--showConfig`, `--generateTrace` or translated
  messages; Ctrl-C stops a run at once
  ([DEFAULTS.md](https://github.com/oxc-project/tsrs/blob/main/docs/DEFAULTS.md)).
- **Language server.** Same protocol as `tsgo --lsp`; VS Code uses it through
  the TypeScript 7 extension with `js/ts.tsdk.path` pointed at the package.
  File watching works on macOS and Windows and is off on Linux, as in tsgo
  ([LSP.md](https://github.com/oxc-project/tsrs/blob/main/docs/LSP.md#editor-setup)).

## Rollout

1. Check each repo under TypeScript 7; tsgolint needs that anyway.
2. Replace the `typecheck` script with `tsrs --noEmit`, pinning the exact
   version (slopsubs is on `0.18.0-ts7.1.0-dev.20260929`).
3. Keep `@typescript/native-preview` (tsgo) as the fallback: swapping back is
   a one-line script change.

## Open questions

- Time saved per repo against tsgo, measured through host-check.
- Whether #378 lands, letting tsrs replace tsgolint behind
  `oxlint --type-aware`.
