## Subagents

In T3, read `~/.config/t3-orchestration.md` before launching, continuing, or
cancelling one.

## Validation

Run builds, tests, lint, typechecks, format checks, and benchmarks through
`~/.local/bin/host-check`, following `~/.config/host-validation.md`.

## Git

- Commit, push, and merge when the work calls for it. Force push `main`,
  `staging`, or `nightly` only when Pedro says so in that conversation.
- Commit subjects: a Conventional Commits type, a scope when obvious
  (`fix(vacant-land): …`), imperative, under 72 characters; reasoning in the
  body.
- Commit in small steps within the commit ceiling below, running format, lint,
  and typecheck on each commit's changed files. Before pushing, run the
  `pre-commit` skill once on the top head (the branch, or the last layer's
  tip). Review-loop rounds and stacked PRs use their light check.

## Tests

Pick the cheapest layer that verifies the behavior: unit, then component or
integration; E2E for cross-system journeys, browser regressions, and routing or
auth flows. Reach for a dev server or browser only when it materially adds
confidence.

## Pull requests

- Draft state follows the owner in the `origin` URL. `PedroNavHur` opens PRs
  ready for review (`draft=false`, or `gh stack submit --auto --open`); any
  other owner opens drafts (REST `draft=true`, or `gh stack submit --auto`),
  marked ready when Pedro asks in that conversation.
- Stacks use `gh stack`: fix on the layer that owns the code, `gh stack rebase`
  descendants when their dependencies need it or Pedro asks, and merge with
  `gh stack merge` on the top PR.
- Size: a PR within 1000 weighted and 2000 raw churn, each commit within 300
  and 600, stack layers 400 to 1000 weighted, at most 5 per stack. Measure
  before pushing per `~/.agents/skills/split-stacked-prs/references/size-policy.md`.
  The rule is personal: it stays out of repositories.

## GitHub API

Use `gh api` REST endpoints whenever one exists; `gh` porcelain and `--json`
may use GraphQL. Spend GraphQL only on draft/ready switches, resolving review
threads, auto-merge, the merge queue, and marking files viewed; `gh stack` is
exempt. On a rate-limit error, check `gh api rate_limit` once, keep the PR, and
wait for the reset.

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
