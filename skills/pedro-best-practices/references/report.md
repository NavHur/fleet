# Report and publication

## Combined report

Lead with the most consequential confirmed findings. For each, include:

- Category and rule ID: `pedro/eight-prop-cap` for React and Svelte component count violations, `pedro/godot-interface-cap` for Godot script count violations, `pedro/component-ownership` for evidenced interface design findings, `pedro/cognitive-complexity` and `pedro/cyclomatic-complexity` for complexity violations (naming the repository rule, such as `dca/cognitive-complexity`, when lint fails), `pedro/complexity-evasion` for suppressions, loosened config, or splits made only to pass, `pedro/no-nested-ternary` for the advisory readability preference, `pedro/long-comment` for comments over two lines of prose, `pedro/swallowed-error`, `pedro/flag-argument`, and `pedro/stale-comment` for the construction rules, and the reference's rule ID for performance findings.
- Clickable file and line, unit (component, scene script, function), and concrete evidence.
- Impact and a focused recommendation; distinguish policy violations from performance defects or optimization opportunities.

For cap violations, include the exact count and the counted input names, or a proven lower bound when the complete contract is unknown. Order cap violations by count within each rule. For interface recommendations, show a concise proposed caller or before/after contract and explain what responsibility or coordination it removes. Distinguish a count violation from an ownership finding even when they concern the same unit; combine their explanation when the root cause is shared.

Finish with inspected unit counts per language, a compact status for every performance category of every in-scope reference, checks actually performed, and unresolved contracts or coverage gaps. Categories may be reviewed with no findings, have findings, be inapplicable, or remain incomplete. Claim a clean audit only for fully inspected scope with no confirmed findings and no unresolved relevant contracts. An agent audit is not a deterministic enforcement guarantee.

## GitHub publication

Use an explicit PR target when supplied; otherwise resolve the open PR for the current branch in its actual GitHub repository. Verify the repository, PR number, base, and head SHA before publishing. If no matching PR exists, return the audit locally and state that no comment was posted. If multiple targets remain plausible, prepare the report and ask which PR to use. Do not create a PR as part of an audit.

Publish the combined report as a normal PR conversation comment after validating findings. Preserve the requested audit scope: a whole-repository audit attached to a PR is still a whole-repository audit. Clearly separate findings in the PR changes from existing issues elsewhere. Record the reviewed commit, base when relevant, and working-tree state. Label findings that depend on uncommitted changes as local-only evidence; never present them as findings in the pushed PR. Use GitHub source permalinks at the reviewed SHA for committed evidence, not local filesystem links. For local-only evidence, provide the path and line as text with a brief excerpt.

Recheck the remote head before posting. If it changed, label the report as reviewing the earlier snapshot, or review the new changes before claiming current coverage. Do not silently attribute results to an unreviewed commit.

Use this comment structure, replacing the placeholders with actual results:

```markdown
## Pedro best practices

> [!WARNING]
> Found N confirmed findings: X interface-cap violations, Y ownership findings, C complexity violations (L failing lint), E complexity evasions, K long comments, S swallowed errors, T stale comments, Z readability advisories (nested conditionals and flag arguments), and W performance findings. Coverage: complete/incomplete.

Reviewed `<sha>` · Scope: <repo/path/PR changes> · Languages: <languages in scope> · Base: <base if applicable>
Working tree: <clean or local changes included>

| ID | Priority / kind | Rule | Location | Finding and recommendation |
| --- | --- | --- | --- | --- |
| PBP-1 | Medium / ownership | `pedro/component-ownership` | [Component](permalink) | Concrete evidence and the responsibility the proposed change removes. |

### Evidence

<Counted input names, focused before/after examples, and measured versus inferred performance costs, keyed to finding IDs. Omit this section if the table contains all necessary evidence.>

### Coverage

| Check | Result |
| --- | --- |
| Interface cap (per language) | <result> |
| Interface ownership | <result> |
| Nested conditionals | <result> |
| Comment length (2 lines of prose) | <result; say whether lint enforces it or the audit scanned it> |
| Swallowed errors | <sites inspected per language; which lint rules the repository enables> |
| Flag arguments | <result> |
| Stale comments | <comments beside changed lines checked> |
| Cognitive complexity (limit 8, or the repository's stricter limit) | <result; say whether lint enforces it or the audit measured it> |
| Cyclomatic complexity (limit 16, or the repository's stricter limit) | <result; same> |
| Complexity evasion | <suppressions, config changes, and split-only refactors checked> |
| <Each performance category of each in-scope reference> | <result> |

Inspected: <unit counts per language>. Checks performed: <actual checks>.
Coverage gaps: <unresolved contracts, unmeasured files, languages without a reference, local-only evidence, or unmeasured costs>.
```

Choose the alert from the result: `[!CAUTION]` when a complexity excess, long comment, or swallowed error fails the repository's lint; `[!WARNING]` when other confirmed policy, complexity, ownership, error-handling, stale-comment, or performance findings exist; `[!NOTE]` when the only findings are nested-conditional or flag-argument advisories or long comments that lint does not fail; `[!IMPORTANT]` for incomplete coverage with no findings; and `[!NOTE]` for no findings with complete static coverage. The warning alert is a report summary, not a seven/eight-input warning tier. When no findings exist, say so and omit the findings table rather than inventing rows. Escape pipes inside table cells and keep long evidence outside the table. Avoid implying that a static audit is CI enforcement or a runtime performance measurement.

Use the available GitHub connector or `gh` to post. For `gh`, write the exact Markdown to a temporary file and use `--body-file` with the verified repository and PR number. On an uncertain response or retry, read the PR comments first and reuse the already-published comment for this run rather than duplicating it. A later intentional audit gets a new comment; preserve previous audit history. Verify the published body and return its URL with the main findings in the conversation. If publication fails, retain the prepared report, explain the failure, and do not claim it was posted.
