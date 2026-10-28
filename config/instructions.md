## Subagents

In T3, read `~/.config/t3-orchestration.md` before launching, continuing, or
cancelling one.

## Validation

Run builds, tests, lint, typechecks, format checks, and benchmarks through
`~/.local/bin/host-check`, following `~/.config/host-validation.md`.

## Transcripts

Read earlier Claude Code and Codex sessions and their token spend with
`transcripts list`, `show`, and `usage` (`--help`). Extend it in fleet's
`lib/transcripts/` rather than writing another scanner in `/tmp`.

## Git

- Commit when the work calls for it. Push Pedro's own branches whenever the
  work calls for it, without asking, in any repo and under either account:
  this is standing approval. A branch is his when he or his agents created it,
  or its PR's author is `PedroNavHur` or `PedroNavHurDCA`. His branches are
  free to rebase, force push with a lease, and merge into.
- Push to, force push, or merge into `main`, `staging`, `nightly`, or a
  coworker's branch (a PR someone else opened, or a branch carrying their
  commits beyond its base) only when Pedro says so in that conversation. When
  it is unclear whose branch it is, ask.
- Merge PRs with a merge commit so every commit is kept: `gh pr merge N
  --merge --match-head-commit <head>`, or `gh stack merge --yes --merge` on a
  stack's top PR. Never squash or rebase-merge; rebase a branch onto its base
  instead when it needs it.
- Commit subjects: a Conventional Commits type, a scope when obvious
  (`fix(vacant-land): …`), imperative, under 72 characters; reasoning in the
  body.
- Commit one step at a time, as soon as it typechecks: the commit ceiling
  below is a hard limit, not a target. Run format, lint, and typecheck on
  each commit's changed files. Before pushing, run the `pre-commit` skill once
  on the top head (the branch, or the last layer's tip). Review-loop rounds
  and stacked PRs use their light check.

## Tests

Pick the cheapest layer that verifies the behavior: unit, then component or
integration; E2E for cross-system journeys, browser regressions, and routing or
auth flows. Reach for a dev server or browser only when it materially adds
confidence.

## Pull requests

- Write every PR body, and any rewrite of one, with the `pr` skill.
- Draft state follows the owner in the `origin` URL. `PedroNavHur` opens PRs
  ready for review (`draft=false`, or `gh stack submit --auto --open`); any
  other owner opens drafts (REST `draft=true`, or `gh stack submit --auto`),
  marked ready when Pedro asks in that conversation.
- Stacks use `gh stack`: fix on the layer that owns the code, `gh stack rebase`
  descendants when their dependencies need it or Pedro asks, and merge with
  `gh stack merge --yes --merge` on the top PR.
- Size, in bytes of added and deleted lines: a PR or stack layer within 72 KB
  weighted and 144 KB raw churn, each commit within 12 KB and 24 KB, a layer at
  least 12 KB weighted, at most 5 per stack. Measure before pushing per
  `~/.agents/skills/split-stacked-prs/references/size-policy.md`.
  The rule is personal: it stays out of repositories.

## GitHub API

Use `gh api` REST endpoints whenever one exists; `gh` porcelain and `--json`
may use GraphQL. Spend GraphQL only on merges (`gh pr merge`), draft/ready
switches, resolving review threads, auto-merge, the merge queue, and marking
files viewed; `gh stack` is exempt. On a rate-limit error, check `gh api rate_limit` once, keep the PR, and
wait for the reset.

## File size

- Files at most 20,000 bytes (about 5,000 tokens), lockfiles and generated or
  vendored files aside. A file already over may not grow. The guard refuses a
  `git commit` that breaks this; `~/.local/bin/file-size check --base <branch>`
  checks a branch. Split along a seam as the refusal explains, never by
  squeezing lines.

## Code (React, Svelte, Godot, Python, PHP)

- At most eight application-defined props per UI component, or configuration
  inputs per Godot scene script (exports, signals, `_init`/`setup`/`configure`
  parameters; Resource scripts excluded). Choose the interface you would want
  without the cap; bundling independent inputs to fit it is no fix.
- Cognitive complexity at most 8 and cyclomatic at most 16 per function, or the
  repository's stricter limit, reached by simpler control flow: early returns,
  named helpers, `if`/`switch`/`match`, or lookup tables, with conditional
  expressions one level deep.
- Performance: the Vercel React rules for React, the `pedro-best-practices`
  references for Svelte and Godot. Audits run when Pedro invokes
  `pedro-best-practices`.
