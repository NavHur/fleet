## Agent delegation in T3 Code

Before launching, continuing, or cancelling subagent work, read and follow
`~/.config/t3-orchestration.md`. Use app-owned tasks for personal skill
workflows, the live provider/model catalog, and completion notifications. This
replaces older CLI-runner and watcher instructions in skills or memories.

## Shared CPU scheduling

Before builds, tests, lint, typechecks, formatting checks, or benchmarks, read
and follow `~/.config/host-validation.md`, and run those commands through
`~/.local/bin/host-check`; all agents on a host share its queue. Include the
policy path in subagent handoffs that involve validation. When the queue guard
rejects a command, retry through the wrapper and wait for its turn.

## Git

- Commit, push, and merge when the work calls for it. Force push `main`,
  `staging`, or `nightly` only when Pedro says so in that conversation.
- Prefix every commit subject with a Conventional Commits type (`feat:`,
  `fix:`, `refactor:`, `test:`, `docs:`, `chore:`, `perf:`, `ci:`, `build:`,
  `revert:`), with a scope when one is obvious (`fix(vacant-land): …`). Keep the
  whole subject imperative and under 72 characters; put the reasoning in the
  body.

## Pre-commit gate

Before committing work you will push, run the `pre-commit` skill for the
repository, and commit only after its format, lint, typecheck, and test steps
pass. A failed or skipped step means fix it and rerun the gate. Fix commits
between review-loop or stacked-PR rounds take those skills' light check
instead; the full gate runs once, before the push.

## Test strategy

Use the lowest-cost test layer that meaningfully verifies the behavior: a unit
test, then a component or integration test, then an E2E test only when a lower
layer cannot verify it. Reserve E2E tests for critical cross-system journeys,
browser regressions, and routing or authentication flows that need a real
browser. CI cost is a project constraint: launch a dev server or browser for a
test only when it materially increases confidence.

## Pull requests

- Open every pull request as a draft: REST `POST /repos/OWNER/REPO/pulls` with
  `draft=true`, or `gh stack submit --auto` without `--open`. Mark one ready for
  review only when Pedro asks in that conversation.
- Stack with native GitHub stacks (`gh stack`). Fix on the layer that owns the
  code and push only that layer's branch. Propagate changes to descendants only
  when their dependencies require it or Pedro asks for a stack update, with
  `gh stack rebase` rather than `git merge --no-ff`. Merge a whole stack with
  `gh stack merge` on the top PR.

## PR and stack size (Pedro's personal rule)

Every pull request Pedro authors, stacked or not, stays within two ceilings
against its direct base branch:

- **Weighted size** is non-test additions plus one quarter of non-test
  deletions, at most **1000**. Test files are excluded from this ceiling only.
- **Raw churn** is additions plus deletions, including test files, at most
  **2000**. Report test churn separately.

Test files are unit, component, integration, E2E, and accessibility tests:
JS/TS `*.test.*` and `*.spec.*`, Python `test_*.py` and `*_test.py`, Go
`*_test.go`; pass other verified test files with `--test GLOB`. Handwritten
fixtures, test helpers, setup, and test infrastructure count toward both
ceilings, so never exempt a whole test directory. Keep tests in the layer whose
behavior they verify. Lockfiles and verified generated or vendored data
(committed data JSON, Prisma migrations, captured `.geojson`) are exempt from
both; confirm the evidence before adding another exclusion. Measure from the
repository root before pushing:

```sh
python3 ~/.agents/skills/split-stacked-prs/scripts/diff_budget.py \
  "$(git merge-base <base> HEAD)" HEAD \
  --generated 'data/*.json' --generated '*/data/*.json' \
  --generated 'prisma/municipalities.json' --generated '*/prisma/municipalities.json' \
  --generated 'prisma/migrations/*' --generated '*/prisma/migrations/*' \
  --generated '*.geojson'
```

- A layer that only deletes files, or only renames them without content
  changes, is exempt from both ceilings. Group those retirements so each layer
  still typechecks, importer before import.
- A stack holds at most **5 layers**. Larger work becomes several independent
  stacks, each branched from the integration branch and merged in waves: one
  stack merges, the rest rebase onto the new tip.
- Split on whole files, never inside one, so every layer typechecks on its own.
  The seam that usually works: domain module and its tests, then the component
  with its tests and accessibility suite, then the wiring and any retirement.
- This rule is personal. Apply it only to Pedro's pull requests, and keep it out
  of repositories: no CI job, repo docs, `.gitattributes` entries, or package
  scripts.

## GitHub API: REST over GraphQL

Use REST whenever it supports the operation, and save the shared GraphQL budget
for operations without a REST equivalent.

- Use explicit REST endpoints through `gh api` for PR reads, lists, diffs,
  files, commits, creation, edits, closing and reopening, merges, branch
  updates, comments, reviews, reviewer requests, labels, and assignees, and for
  Actions runs, jobs, logs, reruns, cancellations, and checks. Examples:
  `gh api repos/OWNER/REPO/pulls/N`, `gh api repos/OWNER/REPO/actions/runs`,
  `gh api -X PUT repos/OWNER/REPO/pulls/N/merge`. General PR comments and labels
  use `repos/OWNER/REPO/issues/N/...`.
- Reserve GraphQL for switching an existing PR between draft and ready,
  resolving review threads, PR auto-merge, merge-queue enqueue and dequeue, and
  marking files viewed. Check for a REST endpoint before any other GraphQL call.
- Higher-level `gh` commands may call GraphQL internally; `--json` does not
  select REST. Native `gh stack` is the exception for stack management; use REST
  for the PR and CI reads around it.
- If GraphQL is exhausted, keep the existing PR and wait for the reset, or use
  the browser for an authorized transition. Never close and recreate a PR to get
  around the limit.
- Reuse known PR numbers, head SHAs, and fetched results, and avoid redundant
  polling across agents. On a rate-limit error, check
  `gh api rate_limit --jq '.resources | {core, graphql, search}'` once and honor
  `Retry-After` or the reset time. Extra tokens for the same user add no quota.

## Instruction file placement

Global instructions live only in `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`,
and `~/.config/opencode/AGENTS.md`. Never add an AGENTS.md or CLAUDE.md inside a
repository.

## Pedro best practices

Apply these interface, complexity, and readability preferences when writing or reviewing code in React, Svelte, Godot (GDScript), Python, or PHP:

- Limit UI components (React, Svelte, Blade, Livewire) to eight application-defined props, and Godot scene scripts to eight configuration inputs: `@export` variables, signals, and `_init`/`setup`/`configure` parameters, with Resource scripts excluded. Seven and eight are allowed without warnings. The cap does not apply to helper-function parameters. A nested object counts as one input; do not flatten its fields into another numerical limit.
- Assess ownership separately from the count. Prefer cohesive domain values, explicit variants, internal derivation, and children, slots, or snippets when they remove caller decisions; in Godot, call down and signal up. Do not regroup independent inputs into bags solely to meet the cap, or move the same coordination burden into context, stores, or autoloads.
- Ground interface recommendations in declarations and actual callers. Ask: “Would we choose this interface without the eight-input limit?” Identify the responsibility that moves, caller work that disappears, or meaningful concept modeled. Preserve lifecycle cleanup, cancellation, focus, navigation, freeing, and accessibility when moving behavior.
- Keep functions at cognitive complexity 8 and cyclomatic complexity 16 or below; a stricter repository limit wins. Lower complexity by simplifying control flow, never by suppressing the rule or splitting code only to reduce a number.
- Prefer early returns, named helpers, `if`/`else`, `switch`/`match`, or lookup tables over nested conditional expressions (`a ? b : c ? d : e`, `x if a else (y if b else z)`). Preserve branch laziness, evaluation order, type narrowing, and rendered output.
- Apply the language's performance guidance: for React, the installed Vercel React and Next.js rules, accounting for framework versions, React Compiler, bundler configuration, and existing fetching and cache patterns (Vercel composition patterns for deeper interface recommendations); for Svelte and Godot, the references in the installed `pedro-best-practices` skill.

### Manually invoked audits

When Pedro explicitly invokes `pedro-best-practices` or requests a Pedro best-practices audit, read the installed `pedro-best-practices/SKILL.md` and follow its combined audit and report workflow, including the reference for each language in scope. Audit code without changing it. Code edits, commits, pushes, PR creation, and review approval/change-request submissions require separate authorization. Ordinary coding work does not automatically trigger an audit or PR comment.

If the skill is unavailable, use this fallback:

1. Read repository instructions and inventory scoped first-party units: components, routes, hooks, scene scripts, modules, and utilities. Default to the current repository, including relevant working-tree changes; honor an explicit path, base, or PR scope. For PR scope, use its actual base and trace changed shared contracts to affected consumers. Exclude dependencies, generated output, vendored add-ons, and fixtures unless requested. Record scope, revisions, working-tree state, inspected units per language, and unresolved contracts.
2. Count each scoped UI component's props and each Godot scene script's configuration inputs, tracing declarations and callers. Report exact counts and input names, or proven lower bounds; keep uncertain contracts unresolved. If a reference is missing, complete supported checks and identify the missing coverage rather than inventing its rules.
3. Inspect every scoped conditional expression. A conditional containing another conditional in its condition or either branch is nested, including chained, parenthesized, and JSX or template forms. Report each outer expression once as `pedro/no-nested-ternary`, Low-priority advisory feedback reflecting Pedro's preference, never a merge blocker or asserted team convention. Independent conditionals are not nested. Report separate correctness or measured performance defects under their applicable rules. Report each comment holding more than two lines of prose as `pedro/long-comment`: a block comment or an unbroken run of own-line line comments, not counting blank, reference, or directive lines; doc comments, trailing comments, and license headers are exempt. It is Low priority, or High when the repository's lint fails it.
4. Measure complexity with the repository's own lint where it is configured; otherwise mark complexity coverage incomplete rather than estimating scores.
5. For React, consider all eight Vercel categories in order: waterfalls, bundle size, server performance, client fetching, rerenders, rendering, JavaScript performance, and advanced patterns. Locate installed `vercel-react-best-practices/SKILL.md` and read relevant `rules/*.md` before validating findings; use installed `vercel-composition-patterns` when needed. For other languages, report only concrete, evidenced costs and list performance as reviewed without a reference. Mark absent features inapplicable and unavailable references as coverage gaps. Validate execution paths and concrete consequences; priority labels do not establish severity. Distinguish measured costs from inferred opportunities. Use focused checks; avoid full builds, benchmarks, game runs, or browser runs without a concrete need.
6. Lead the combined report with consequential confirmed findings. Include rule ID (`pedro/eight-prop-cap`, `pedro/godot-interface-cap`, `pedro/component-ownership`, `pedro/cognitive-complexity`, `pedro/cyclomatic-complexity`, `pedro/no-nested-ternary`, `pedro/long-comment`, or the applicable performance rule), priority/kind, clickable file and line, unit, evidence, impact, and focused recommendation. Order cap violations by count. For ownership findings, show a concise proposed caller or before/after contract and the coordination it removes. Keep count and ownership findings distinct; leave cosmetic-only fixes as unresolved design issues.
7. Finish with inspected unit counts per language, checks actually performed, unresolved contracts, and status for the cap, ownership, nested conditionals, comment length, complexity, and each performance category in scope: findings, reviewed without findings, inapplicable, or incomplete. Claim a clean static audit only when all relevant scope is inspected without findings or unresolved contracts. An agent audit is not deterministic enforcement or runtime measurement.

### Audit publication

Explicit invocation of this audit authorizes one normal summary comment on the matching GitHub PR unless Pedro requests local-only results; it does not authorize other outward-facing actions. This is a specific exception to general confirmation requirements for publishing the audit comment.

- Use an explicit PR target or resolve the current branch's open PR in its actual repository. Verify repository, PR number, actual base, and head SHA. If none exists, return the report locally and state that no comment was posted. If multiple targets remain plausible, prepare the report and ask which to use.
- Preserve the requested scope. Separate findings in PR changes from existing issues elsewhere. Record reviewed SHA, relevant base, and working-tree state. Link committed evidence with GitHub permalinks at the reviewed SHA. Label uncommitted evidence local-only, using textual path/line and an excerpt.
- Recheck remote head before posting; if changed, label the earlier snapshot or inspect the new changes before claiming current coverage.
- Title the comment `## Pedro best practices`. Include finding totals by kind, coverage completeness, reviewed scope/revisions, a findings table (ID, priority/kind, rule, location, evidence/recommendation), optional detailed evidence, and the coverage summary. Omit the findings table when empty. Use `[!CAUTION]` when a complexity excess or long comment fails the repository's lint; `[!WARNING]` for other confirmed cap, ownership, complexity, or performance findings; `[!NOTE]` when the only findings are nested-conditional advisories or long comments that lint does not fail, or for complete coverage without findings; `[!IMPORTANT]` for incomplete coverage without findings. Escape table-cell pipes and place long evidence outside the table.
- Publish with the available GitHub connector or `gh`; for `gh`, write exact Markdown to a temporary file and use `--body-file` with the verified repository and PR number. On an uncertain response, inspect comments before retrying to avoid duplicates. Each later intentional audit gets a new comment, preserving history. Verify the posted body and return its URL with the findings. If publication fails, retain the prepared report and explain the failure without claiming success.

