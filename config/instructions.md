## Agent delegation in T3 Code

Before launching, continuing, or cancelling subagent work, read and follow
`~/.config/t3-orchestration.md`.

## Shared CPU scheduling

Run builds, tests, lint, typechecks, formatting checks, and benchmarks through
`~/.local/bin/host-check`, following `~/.config/host-validation.md`; all agents
on a host share its queue. Pass that path to subagents that validate. When the
guard rejects a command, retry through the wrapper.

## Git

- Commit, push, and merge when the work calls for it. Force push `main`,
  `staging`, or `nightly` only when Pedro says so in that conversation.
- Commit subjects use a Conventional Commits type, with a scope when obvious
  (`fix(vacant-land): …`), imperative and under 72 characters. Put the
  reasoning in the body.
- Before committing work you will push, run the `pre-commit` skill and commit
  only after its steps pass. Between review-loop or stacked-PR rounds, take
  those skills' light check; the full gate runs once, before the push.

## Tests

Use the cheapest test layer that verifies the behavior: unit, then component or
integration, then E2E only for cross-system journeys, browser regressions, and
routing or auth flows. Start a dev server or browser only when it materially
adds confidence.

## Pull requests

- Open every PR as a draft (REST `POST /repos/OWNER/REPO/pulls` with
  `draft=true`, or `gh stack submit --auto` without `--open`). Mark it ready
  only when Pedro asks in that conversation.
- Stack with `gh stack`. Fix on the layer that owns the code and push only that
  branch; `gh stack rebase` descendants only when their dependencies need it or
  Pedro asks. Merge a stack with `gh stack merge` on the top PR.
- Pedro's PRs stay within his size ceilings: 1000 weighted, 2000 raw churn, 5
  layers per stack. Before pushing one, measure it as
  `~/.agents/skills/split-stacked-prs/references/size-policy.md` says. The rule
  is personal: keep it out of repositories.

## GitHub API

Use REST through `gh api` whenever it supports the operation; `gh` porcelain
and `--json` may still use GraphQL. Use GraphQL only for draft/ready switches,
resolving review threads, auto-merge, the merge queue, and marking files
viewed; `gh stack` is exempt. If GraphQL is exhausted, wait for the reset;
never close and recreate a PR. On a rate-limit error, check
`gh api rate_limit` once and honor the reset. Reuse fetched results instead of
polling again.

## Instruction files

Global instructions live only in `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`,
and `~/.config/opencode/AGENTS.md`. Never add an AGENTS.md or CLAUDE.md inside a
repository.

## Code preferences (React, Svelte, Godot, Python, PHP)

- At most eight application-defined props per UI component, or configuration
  inputs per Godot scene script (exports, signals, `_init`/`setup`/`configure`
  parameters; Resource scripts excluded). Don't bundle independent inputs just
  to meet the cap: ask whether you'd choose the interface without it.
- Cognitive complexity at most 8 and cyclomatic at most 16 per function, or the
  repository's stricter limit. Simplify control flow; never suppress the rule or
  split code only to move the number.
- No nested conditional expressions; use early returns, named helpers,
  `if`/`switch`/`match`, or lookup tables.
- Follow each language's performance guidance: the Vercel React rules for
  React, the `pedro-best-practices` references for Svelte and Godot.
- Audits run only when Pedro invokes `pedro-best-practices`; follow that skill.
