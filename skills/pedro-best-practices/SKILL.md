---
name: pedro-best-practices
description: "Audit a repo or PR (React, Svelte, Godot, Python, PHP) against Pedro's interface cap, ownership, complexity, comment, error-handling, readability, and performance rules, and post the report on the PR."
---

# Pedro best practices

Audit code without modifying it, combining Pedro's interface, ownership, complexity, comment, error-handling, and readability preferences with performance guidance for each language in scope. Return findings in the conversation and publish one summary comment on the matching GitHub PR. Explicit invocation authorizes that comment unless the user requests a local-only audit. Code changes, commits, pushes, and review approval or change-request submissions remain outside this workflow.

## PR size requests

For an audit or explanation of Pedro's PR or layer size rule, read the
installed `split-stacked-prs` skill, its `references/size-policy.md`, and its
`scripts/diff_budget.py`. This is a separate
personal policy from the code audit below. For a policy-only request, return
findings in the conversation without running the audit or posting a PR
comment. Claude's installed wrapper reads this same canonical skill.

## Scope and languages

With no scope argument, audit the current repository's first-party application code, including relevant working-tree changes. Accept a path, explicit base, or PR scope; use a PR's actual base and follow changed shared contracts to affected consumers. Record the scope, revisions, and working-tree state reviewed. Exclude dependencies, generated output, vendored add-ons, and fixtures unless requested.

When the user requests a reviewer model or agent, follow `~/.config/t3-orchestration.md` and include the applicable audit instructions, references, scope, and requested role in its complete brief. Delegate read-only investigation; the invoking thread validates findings and owns any authorized PR comment. Preserve requested model and effort choices.

## Audit

Read [references/rules.md](references/rules.md) and carry out its audit steps on the scope. Every rule in it applies, and its steps say when to read [references/complexity.md](references/complexity.md) and [references/construction-rules.md](references/construction-rules.md).

## Report and publication

After validating findings, read [references/report.md](references/report.md) before writing the report: it holds the PR comment template and how to choose its alert, and how to resolve the PR, post, and verify the comment. Each finding carries the fields and rule ID in rules.md's "Findings", and the report covers every check in its "Coverage".
