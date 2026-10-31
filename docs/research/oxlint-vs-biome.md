# oxlint + oxfmt vs Biome for personal web repos

State as of 2026-10-31 for TanStack Start + Vite + bun. Sources: first-party
docs, repos, and npm metadata; local findings are marked.

## Decision

**Adopted 2026-10-31: oxlint + oxfmt in every personal web repo, through
Vite+ (`vp lint`, `vp fmt`, `vp check`) where a repo adopts it.** Type
checking: [tsrs](tsrs.md).

- Complexity: oxlint has a native cyclomatic rule (`complexity`), and fleet's
  `pbp/cognitive-complexity` JS plugin covers cognitive. Biome has cognitive
  and no cyclomatic rule, so it can enforce only half of the 8/16 cap.
- Type-aware linting: tsgolint is stable and covers 59 of typescript-eslint's
  61 type-aware rules. Biome's equivalents (`noFloatingPromises`,
  `noMisusedPromises`) are still nursery.
- Vite+ wraps oxlint, oxfmt, and tsgolint, and its docs never mention Biome.
- Svelte and Astro during the transition: oxfmt formats them through a bundled
  Prettier, and oxlint lints their script blocks, including with JS plugins
  (tested locally). Biome marks Svelte and Astro experimental behind an opt-in
  flag.
- Four of the five local repos already use oxlint and oxfmt, and the
  `pedro-best-practices` complexity measurer is built on oxlint.

Risks: oxfmt is still 0.x (beta), oxlint JS plugins are alpha, and one
company (VoidZero, now Cloudflare) backs the whole chain. Biome is safer on
governance and formatter maturity, and loses on complexity, type-aware
coverage, plugin compatibility, and Vite+ integration.

## Comparison

| | oxlint 1.90.0 + oxfmt 0.75.0 | Biome 2.6.4 |
|---|---|---|
| Latest release | oxlint 2026-10-27, oxfmt 2026-10-27, tsgolint 7.0.2005 2026-10-22 [npm] | 2026-10-28 [npm] |
| Lint rules | 872 total, 111 on by default [oxc rules] | 670 across all languages [biome linter] |
| Type-aware | tsgolint on typescript-go, 59/61 typescript-eslint rules, stable since 2026-07-22 | own inference engine (rewritten in 2.6); floating/misused-promise rules are nursery |
| Cyclomatic (16) | `complexity` (eslint), native | none |
| Cognitive (8) | not native; JS plugin (fleet `pbp`, govstructure's own) | `noExcessiveCognitiveComplexity`, native |
| Custom rules | ESLint v9-compatible JS plugins (alpha) | GritQL (no semantic model); JS plugins (developer preview, Biome-specific API) |
| Formatter | Prettier-compatible; 100% of Prettier JS/TS conformance tests (Feb 2026) | "97% compatibility with Prettier" |
| Tailwind sort | in the formatter (`sortTailwindcss`) | nursery lint rule `useTailwindSortedClasses` |
| Import sort | in the formatter (`sortImports`) | assist action `organizeImports` |
| Svelte/Astro | format: full (bundled Prettier, needs compiler pkg); lint: script blocks only | parse/format/lint all experimental, opt-in |
| Vite+ | wrapped by `vp lint`/`vp fmt` | not mentioned |
| Editors | VS Code, Zed, JetBrains (first-party), LSP | VS Code, Zed, JetBrains (first-party), LSP |
| Backing | VoidZero (Accel-funded, joined Cloudflare Jun 2026) | volunteer-led, sponsors + Open Collective |

## 1. Lint rule coverage

**oxlint.** The rules page lists 872 rules, 111 on by default, 334 with fixes,
in seven categories (correctness, suspicious, pedantic, perf, restriction,
style, nursery) ([rules](https://oxc.rs/docs/guide/usage/linter/rules.html)).
Built-in plugins include eslint, typescript, unicorn, react (which also covers
react-hooks, react-refresh, and React Compiler), react-perf, nextjs, oxc,
import (also matching import-x), jsdoc, jsx-a11y, node, promise, jest, vitest,
and vue ([plugins](https://oxc.rs/docs/guide/usage/linter/plugins.html)).
Rule files in `crates/oxc_linter/src/rules/` on `main`, counted by me from the
[oxc tree](https://github.com/oxc-project/oxc/tree/main/crates/oxc_linter/src/rules)
(a few may be helpers): eslint 187, unicorn 138, typescript 112, react 85,
jsx-a11y 36, import 33. The React Compiler rules (22 of them) arrived on
2026-08-18
([post](https://oxc.rs/blog/2026-08-18-react-compiler-support)).

Type-aware linting runs in `oxlint-tsgolint`, a Go binary built on
typescript-go. It reached v7 (stable) on 2026-07-22 with 59 of 61
typescript-eslint type-aware rules, including `no-floating-promises`,
`no-misused-promises`, and the `no-unsafe-*` family. It can also report
`tsc` errors (`--type-check`), which can replace `tsc --noEmit`
([post](https://oxc.rs/blog/2026-07-22-type-aware-linting-stable),
[docs](https://oxc.rs/docs/guide/usage/linter/type-aware.html)). Its version
pins a TypeScript 7 release (`7.0.2005` is patch 5 on TS 7.0.2), so a project
has to type-check under TS 7.

**Biome.** 670 rules in eight groups (a11y, complexity, correctness, nursery,
performance, security, style, suspicious) across JS, CSS, JSON, GraphQL, HTML,
Markdown, and YAML ([linter](https://biomejs.dev/linter/)). On `main` there are
554 JS rule files, 143 of them nursery
([source](https://github.com/biomejs/biome/tree/main/crates/biome_js_analyze/src/lint)).
Type-aware rules depend on Biome's own inference, which scans `.d.ts` files in
`node_modules`. Biome's own table shows it raising lint time from about 0.8 s
to 2 s on 2k files and from 1 s to 8 s on 5k files
([linter](https://biomejs.dev/linter/)). 2.6 rewrote the engine on salsa
([v2.6](https://biomejs.dev/blog/biome-v2-6/)). `noFloatingPromises` and
`noMisusedPromises` are still in `lint/nursery`
([rule](https://biomejs.dev/linter/rules/no-floating-promises/),
[source](https://github.com/biomejs/biome/tree/main/crates/biome_js_analyze/src/lint/nursery)).
The [rule sources page](https://biomejs.dev/linter/rules-sources/) lists
react 14, react-hooks 2, jsx-a11y 33, import 4, unicorn 21, typescript-eslint
44, sonarjs 2, and no `no-unsafe-*` type rules. **Unverified:** it seems to
omit nursery rules (`noFloatingPromises` isn't on it), so these are lower
bounds.

govstructure enables about 30 tsgolint rules (`no-unsafe-*`, `unbound-method`,
`restrict-template-expressions`, `prefer-nullish-coalescing`, and others).
Biome has no counterpart for most of them.

## 2. Complexity enforcement (cognitive 8, cyclomatic 16)

- **oxlint, cyclomatic:** the native `complexity` rule (restriction, since
  1.37.0) takes `max` and `variant: "classic"`
  ([rules](https://oxc.rs/docs/guide/usage/linter/rules.html)). govstructure
  already sets `max: 16`.
- **oxlint, cognitive:** no native rule; none exists in the
  [source tree](https://github.com/oxc-project/oxc/tree/main/crates/oxc_linter/src/rules/eslint).
  There are two routes. One is a local JS plugin: fleet's `pbp.mjs` and
  govstructure's `cognitive-complexity.js` both exist. The other is
  `eslint-plugin-sonarjs` as a JS plugin, which passes 99.6% of its tests
  excluding type-aware rules
  ([JS plugins alpha](https://oxc.rs/blog/2026-03-11-oxlint-js-plugins-alpha)).
- **Biome, cognitive:** `noExcessiveCognitiveComplexity` (complexity group,
  since v1.0.0, not recommended, `maxAllowedComplexity` default 15). Its docs
  list it as "Same as `sonarjs/cognitive-complexity`" and document no
  deviations
  ([rule](https://biomejs.dev/linter/rules/no-excessive-cognitive-complexity/)).
- **Biome, cyclomatic:** none. The complexity group has no such rule
  ([source](https://github.com/biomejs/biome/tree/main/crates/biome_js_analyze/src/lint/complexity)),
  and ESLint `complexity` has no mapping on the rule sources page. You could
  approximate it only with a Biome JS plugin (developer preview), whose docs
  list no rule options.

**Local test** (oxlint 1.87.0 from `skills/pedro-best-practices`, temp dir):
`complexity` and `pbp/cognitive-complexity` both reported functions inside a
`.svelte` `<script lang="ts">` block and an `.astro` frontmatter block. JS
plugins therefore run on SFC script blocks, even though the docs list "Custom
file formats and parsers (e.g. Svelte, Vue, Angular)" as unsupported
([JS plugins](https://oxc.rs/docs/guide/usage/linter/js-plugins.html)). That
limit concerns templates and custom parsers.

## 3. Formatting

**oxfmt** went beta on 2026-02-24. The beta post says it passes 100% of
Prettier's JS/TS conformance tests, with the remaining differences reported
upstream ([beta](https://oxc.rs/blog/2026-02-24-oxfmt-beta),
[#18717](https://github.com/oxc-project/oxc/issues/18717)). It is still 0.x
(0.75.0, [npm](https://registry.npmjs.org/oxfmt)), and the blog index has no
stable announcement
([blog source](https://github.com/oxc-project/website/tree/main/src/blog)).
Tailwind class sorting (a built-in replacement for prettier-plugin-tailwindcss),
import sorting, and package.json sorting are part of the formatter
([sorting](https://oxc.rs/docs/guide/usage/formatter/sorting.html)). It doesn't
support Prettier plugins, `experimentalTernaries`, or the `prettier` key in
package.json. Its default `printWidth` is 100, not 80
([unsupported](https://oxc.rs/docs/guide/usage/formatter/unsupported-features.html)).

**Biome** claims "97% compatibility with Prettier"
([home](https://biomejs.dev/)). Import sorting is the `organizeImports` assist
action. Tailwind sorting is the nursery lint rule `useTailwindSortedClasses`,
which moved to Tailwind v4 semantics in 2.6
([v2.6](https://biomejs.dev/blog/biome-v2-6/)). The 2.6 Markdown formatter is
"~92% compatible with Prettier", and the YAML formatter claims 100%.

## 4. Non-JS files

| | oxfmt | oxlint | Biome (parse / format / lint) |
|---|---|---|---|
| CSS/SCSS/Less | native | no | CSS ✅✅✅, SCSS ✅✅✅ (new in 2.6), Less not listed |
| JSON/JSONC | native (also JSON5) | no | ✅✅✅ |
| GraphQL | native | no | ✅✅✅ |
| Markdown | native (MDX via Prettier) | no | ✅✅✅ (2.6) |
| YAML/TOML | native | no | YAML ✅✅✅ (one lint rule); TOML not listed |
| Svelte | bundled Prettier; needs `svelte` pkg + `svelte: true` | script blocks, no template lint | 🟡🟡🟡 opt-in |
| Astro | bundled Prettier; needs `@astrojs/compiler-rs` + `astro: true` | script blocks, no template lint | 🟡🟡🟡 opt-in |
| Vue | bundled Prettier | script blocks + vue plugin | 🟡🟡🟡 |

Sources: [oxfmt languages](https://oxc.rs/docs/guide/usage/formatter/language-support.html),
[oxc compat data](https://github.com/oxc-project/website/blob/main/.vitepress/data/compat/oxlint.ts)
(Svelte/Astro/SvelteKit "partial: No template linting yet",
[#15761](https://github.com/oxc-project/oxc/issues/15761)),
[Biome language support](https://biomejs.dev/internals/language-support/).
Without full HTML support, Biome advises disabling `useConst`,
`useImportType`, `noUnusedVariables`, and `noUnusedImports` for these files.
Prettier-backed oxfmt formats need the npm package and Node.js; the standalone
binary skips them.

Neither linter checks Svelte or Astro templates; keep `svelte-check` /
`astro check` during the transition.

## 5. Custom rules

**oxlint JS plugins** are alpha and ESLint v9-compatible. They implement AST
traversal, selectors, scope analysis, code paths, tokens, fixes, suggestions,
and LSP diagnostics. Custom type-aware rules and custom parsers are not
supported yet ([JS plugins](https://oxc.rs/docs/guide/usage/linter/js-plugins.html)).
The alpha post reports conformance of 100% on ESLint's built-in rule tests,
100% on react-hooks, 99.99% on @stylistic, and 99.6% on SonarJS. It also lists
Windows out-of-memory as a known issue
([alpha](https://oxc.rs/blog/2026-03-11-oxlint-js-plugins-alpha)). The open
tracking issue is
[#19918](https://github.com/oxc-project/oxc/issues/19918). Under Vite+, plugin
authors import from `vite-plus/lint/plugins`
([vp lint](https://viteplus.dev/guide/lint)).

**Biome** has two plugin systems
([plugins](https://biomejs.dev/linter/plugins/)):
- GritQL plugins can match, report, and (since 2.5) fix, on JS, CSS, and JSON.
  They have no semantic model and no file kind, and they run on every file.
- JS plugins reached developer preview in 2.6. They run on the Boa runtime
  against Biome's CST, with an API "completely different" from ESLint's, and
  can break in patch releases
  ([v2.6](https://biomejs.dev/blog/biome-v2-6/)).

govstructure's three plugins (15 `anti-slop` rules plus `govstructure` and
`design`) and fleet's `pbp` would all need rewrites on Biome.

## 6. Speed (first-party, read with care)

- **Oxc linter bench** ([bench-linter](https://github.com/oxc-project/bench-linter),
  last commit 2026-10-28): "~2x faster than Biome". On the VS Code repo it
  measured 2.72x on an M2 Max (139 ms vs 377 ms) and 2.49x on an M4 Max.
  `package.json` pins `@biomejs/biome ^2.3.8` and `oxlint ^1.51.0`, older than
  current releases. The README doesn't show whether the two run equivalent
  rule sets, so the ratio partly measures configuration.
- **Oxc formatter bench** ([bench-formatter](https://github.com/oxc-project/bench-formatter),
  run 2026-10-27, oxfmt 0.75.0, Biome 2.6.2, Prettier 3.9.10): oxfmt was 1.61x
  faster than Biome on one 13.7k-line file and 3.16x on Outline's JS/TS. The
  embedded-language and Tailwind/import-sort suites compare only against
  Prettier.
- **Biome** claims ~35x faster than Prettier on 171,127 lines
  ([home](https://biomejs.dev/)); the linked `benchmark/` directory 404s on
  `main`.

At personal-repo scale, type-aware cost (tsgolint vs Biome's scanner) matters
more than these ratios, and neither project publishes a head-to-head for it.

## 7. Migration tools

- `npx @oxlint/migrate [eslint.config.js]` converts flat configs (rules,
  options, overrides, globals, ignores). `--type-aware` adds tsgolint rules.
  Unsupported plugins become `jsPlugins` by default, but local plugins have to
  be added by hand
  ([guide](https://oxc.rs/docs/guide/usage/linter/migrate-from-eslint.html)).
  There is also a `migrate-oxlint` agent skill.
- `oxfmt --migrate prettier` and `oxfmt --migrate biome` migrate formatter
  config ([beta](https://oxc.rs/blog/2026-02-24-oxfmt-beta)). I found no
  documented migrator from a Biome *lint* config to oxlint.
- `biome migrate eslint --write` reads legacy and flat configs;
  `--include-inspired` adds non-identical rules; plugins exporting cyclic
  objects need manual setup. `biome migrate prettier` and `stylelint` (2.6)
  also exist ([guide](https://biomejs.dev/guides/migrate-eslint-prettier/)).

## 8. Vite+ integration

vite-plus 1.0.0 shipped 2026-09-28, and 1.4.0 (2026-10-23) is current
([npm](https://registry.npmjs.org/vite-plus),
[1.0 post](https://voidzero.dev/posts/announcing-vite-plus-1-0)). 1.4.0
depends on pinned versions: `oxlint =1.89.0`, `oxfmt =0.74.0`,
`oxlint-tsgolint =7.0.2004`, and `@oxlint/plugins =1.89.0`, one release
behind the latest of each. `vp lint` "lints code with Oxlint" and `vp fmt`
"formats code with Oxfmt". Configuration goes in `lint` / `fmt` blocks of the
root `vite.config.ts`, and the docs say "We do not recommend using
`oxlint.config.ts` or `.oxlintrc.json` with Vite+". `vp check` runs format,
lint, and type-check together
([vp lint](https://viteplus.dev/guide/lint),
[vp fmt](https://viteplus.dev/guide/fmt)). Neither page mentions Biome. The 1.0
post doesn't mention bun; it says `vp install` uses "the project's package
manager".

TanStack's scaffolder offers only `biome` and `eslint` toolchains for React
([TanStack/cli](https://github.com/TanStack/cli/tree/main/packages/create/src/frameworks/react/toolchains)),
hence slopsubs on Biome.

## 9. Editors, LSP, CI

Both ship first-party VS Code (Marketplace and Open VSX), Zed, and JetBrains
extensions ([oxlint](https://oxc.rs/docs/guide/usage/linter/editors.html),
[oxfmt](https://oxc.rs/docs/guide/usage/formatter/editors.html),
[Biome](https://biomejs.dev/guides/editors/first-party-extensions/)). Oxc runs
`oxlint --lsp` and `oxfmt --lsp` from one extension (`oxc.oxc-vscode`);
`oxc.typeAware` enables tsgolint in the editor. Biome runs `biome lsp-proxy`.
CI is a plain CLI call for both.

## 10. Maturity

| | Stable releases 2026-05-01 → 10-31 | Major line |
|---|---|---|
| oxlint | 28 (1.63.0 → 1.90.0), weekly | 1.0.0 on 2025-06-10 |
| oxfmt | 28 (0.48.0 → 0.75.0) | 0.x; beta since 2026-02-24 |
| oxlint-tsgolint | 9 (0.23.0 → 7.0.2005) | v7 stable 2026-07-22 |
| Biome | 24 (2.4.14 → 2.6.4); 2.5.0 on 2026-06-12, 2.6.0 on 2026-10-21 | 2.0.0 on 2025-06-17 |

Counts come from the npm registry `time` fields
([oxlint](https://registry.npmjs.org/oxlint),
[oxfmt](https://registry.npmjs.org/oxfmt),
[tsgolint](https://registry.npmjs.org/oxlint-tsgolint),
[biome](https://registry.npmjs.org/@biomejs/biome)).

**Backing.** VoidZero raised a $12.5M Accel-led Series A in Oct 2025
([post](https://voidzero.dev/posts/announcing-series-a)) and joined Cloudflare
on 2026-06-04; Oxc and Vite+ "will remain open-source and MIT-licensed", led
by the same team ([post](https://voidzero.dev/posts/voidzero-cloudflare)).
Biome is "a project led by volunteers", sponsored by Depot and CodSpeed
([v2.6](https://biomejs.dev/blog/biome-v2-6/)), with written governance
([GOVERNANCE.md](https://github.com/biomejs/biome/blob/main/GOVERNANCE.md)).

## Local repos: what each needs

| Repo | Today | To stay on / move to Oxc | To move to Biome |
|---|---|---|---|
| govstructure (Next, pnpm) | oxlint 1.86 + tsgolint 7.0.2003 + oxfmt 0.71; 3 JS plugins; `complexity` 16 + own cognitive 8 | bump; on TanStack Start drop the `nextjs` plugin and rules; optionally move config into `vite.config.ts` | lose cyclomatic and most tsgolint rules; rewrite 3 plugins; nursery promise rules |
| HiveFront (Next pages) | oxlint 1.76, oxfmt 0.67, minimal config | bump; add `complexity` + `pbp` cognitive | small config; still no cyclomatic |
| pnav (Astro+Svelte, bun) | oxlint 1.79; oxfmt 0.64 with `svelte`, `sortImports`, `sortTailwindcss` | bump; add `astro: true` + `@astrojs/compiler-rs` if `.astro` formatting is wanted | experimental HTML full support for `.svelte`/`.astro`; Tailwind sort becomes a nursery lint rule |
| slopsubs (TanStack Start) | Biome 2.4.5, `recommended`, tabs, double quotes, `organizeImports` | `oxfmt --migrate biome`; oxlint with `react`, `jsx-a11y`, `import`, type-aware; add complexity rules | bump only |
| pedro-best-practices | oxlint 1.87 runner; reads `.oxlintrc.json` | **gap:** `measure_js.py` discovers only `.oxlintrc.json` (line 207), so a Vite+ `lint` block is ignored and files fall back to the skill's oxlint | Biome repos already fall back; Biome limits are never read |

## Migration sketch (Oxc via Vite+)

1. **Fix the measurer first:** teach `measure_js.py` to read the `lint` block
   of `vite.config.*`. Otherwise Vite+ repos lose enforced-limit tagging.
2. **One shared config,** based on govstructure's minus `nextjs`: plugins
   `typescript`, `unicorn`, `oxc`, `import`, `react`, `jsx-a11y`, `vitest`;
   `options.typeAware: true`; `complexity` `{max: 16, variant: "classic"}`;
   `pbp/cognitive-complexity` `{max: 8}` via `jsPlugins` (package or vendor
   `pbp.mjs`).
3. **Per repo:** `vp` repos put this in the `vite.config.ts` `lint`/`fmt`
   blocks; others keep `.oxlintrc.json` / `.oxfmtrc.json`. Pin oxlint, oxfmt,
   and tsgolint to vite-plus's versions.
4. **slopsubs:** `oxfmt --migrate biome`, write the lint config by hand,
   remove `biome.json` and `@biomejs/biome`, and make one reformat commit.
5. **Svelte repos:** keep `svelte: true` (and `astro: true` for pnav) plus
   `svelte-check` until they move to React.
6. **CI:** let `vp check` (or `oxlint --type-aware --type-check`) replace
   `tsc --noEmit` only once the repo type-checks under TS 7.

## Open questions

- Does each repo type-check cleanly under TypeScript 7 (required by tsgolint
  7.x)? Not checked.
- When does oxfmt reach 1.0? No date is published.
- Does `vp lint` load `jsPlugins` given as relative paths from
  `vite.config.ts` the same way `.oxlintrc.json` does? The docs show
  `lint.jsPlugins` but not path resolution. Untested.
- Does Biome's cognitive score match fleet's `pbp-complexity`? Its docs claim
  "Same as sonarjs" without parity tests.
- bun with Vite+: the 1.0 post doesn't name bun as a supported package manager.
  Check the `vp install` docs before relying on it.
