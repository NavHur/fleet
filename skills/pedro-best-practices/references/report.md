# Report and publication

The report gives each finding the fields and rule ID in [rules.md](rules.md) "Findings" and a status for every check in its "Coverage".

## GitHub publication

Use an explicit PR target when supplied; otherwise resolve the open PR for the current branch in its actual GitHub repository. Verify the repository, PR number, base, and head SHA before publishing. If no matching PR exists, return the audit locally and state that no comment was posted. If multiple targets remain plausible, prepare the report and ask which PR to use. Do not create a PR as part of an audit.

Publish the report as a normal PR conversation comment after validating findings. Preserve the requested audit scope: a whole-repository audit attached to a PR is still a whole-repository audit. Clearly separate findings in the PR changes from existing issues elsewhere. Record the reviewed commit, base when relevant, and working-tree state. Label findings that depend on uncommitted changes as local-only evidence; never present them as findings in the pushed PR. Use GitHub source permalinks at the reviewed SHA for committed evidence, not local filesystem links. For local-only evidence, provide the path and line as text with a brief excerpt.

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
| <Each check in rules.md "Coverage", in its order> | <result> |

Inspected: <unit counts per language>. Checks performed: <actual checks>.
Coverage gaps: <unresolved contracts, unmeasured files, languages without a reference, local-only evidence, or unmeasured costs>.
```

Choose the alert from the result: `[!CAUTION]` when a complexity excess, long comment, or swallowed error fails the repository's lint; `[!WARNING]` when other confirmed policy, complexity, ownership, error-handling, stale-comment, or performance findings exist; `[!NOTE]` when the only findings are nested-conditional or flag-argument advisories or long comments that lint does not fail; `[!IMPORTANT]` for incomplete coverage with no findings; and `[!NOTE]` for no findings with complete static coverage. The warning alert is a report summary, not a seven/eight-input warning tier. When no findings exist, say so and omit the findings table rather than inventing rows. Escape pipes inside table cells and keep long evidence outside the table. Avoid implying that a static audit is CI enforcement or a runtime performance measurement.

Use the available GitHub connector or `gh` to post. For `gh`, write the exact Markdown to a temporary file and use `--body-file` with the verified repository and PR number. On an uncertain response or retry, read the PR comments first and reuse the already-published comment for this run rather than duplicating it. A later intentional audit gets a new comment; preserve previous audit history. Verify the published body and return its URL with the main findings in the conversation. If publication fails, retain the prepared report, explain the failure, and do not claim it was posted.
