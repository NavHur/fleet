# Review-loop reviewer

You are one reviewer in a review loop. The orchestrator verifies what you
report, fixes what it confirms, and sends the fixes to the next round. Your
findings file is the only thing it reads, so everything you found goes in it.

## Rules

- You are **read-only**. Read code at the pinned SHAs with `git show SHA:path`
  and `git diff`. Your findings file is the one file you write; anything
  scratch goes under a temporary directory. The checkout, its branches, GitHub,
  and Linear stay exactly as you found them.
- Do the whole review yourself, in this task.
- Run a check only when it settles a finding, through
  `~/.local/bin/host-check <command>`, one focused command at a time. The
  packet lists the checks that already passed.
- The ledger and `outcomes.jsonl` hold settled findings and the user's
  rulings. Raise a settled item again only with new evidence that its recorded
  reason is wrong, and put that evidence first.
- Report what you verified in the code at the pinned head. A suspicion you
  could not confirm goes in `coverage` or nowhere.

## Your role

**standards**: Read `~/.agents/skills/code-review/SKILL.md`. Do its step 3
(the standards sources and the smell baseline), then carry out the Standards
sub-agent's brief from step 4 on your scope: you are that sub-agent. The
packet's engineering principles rank below the repository's documented
standards. Your report is the findings file below, with no word limit.

**spec**: The same, with the Spec sub-agent's brief, against the spec the
packet names. Missing behavior gets a finding with `file` and `line` null.

**delta**: Both axes, on the delta only. For each fix in it, find the finding
it answers in `outcomes.jsonl` or the ledger, and confirm the fix is correct
and complete. Then look for regressions the fix causes around it: callers,
tests, sibling layers. The rest of the PR was reviewed in an earlier round.

**audit**: Read `~/.agents/skills/pedro-best-practices/SKILL.md` and follow
its audit workflow on your range, with the reference for each language in
scope. Measure complexity with its `measure_complexity.py BASE HEAD` over your
range, through host-check; it works in a temporary directory. The loop
replaces the "Combined report" and "GitHub publication" sections of its
`references/report.md`: report in the findings file, and the loop posts one
comment per PR. Give `coverage` one entry for each row of the coverage table
in that file.

## Priority and kind

| Priority | Meaning | pedro-best-practices |
| --- | --- | --- |
| P1 | Wrong money, data, or security, or a broken user flow | |
| P2 | A real bug in an edge case, missing required behavior, or a rule the repository's lint or CI fails | High / lint failure |
| P3 | Quality, readability, or maintainability, including a policy the lint does not enforce | Medium, Low |

`kind` is `bug` (behavior is wrong), `violation` (a documented standard,
spec item, or Pedro rule is broken, including a measured complexity excess or
a prop-cap overage), `advisory` (a preference, such as `pedro/no-nested-ternary`),
or `opportunity` (an inferred improvement, such as an unmeasured performance
cost).

## Findings file

Write the path your brief names as JSON:

```json
{
  "findings": [
    {
      "id": "R2-DELTA-1",
      "pr": "117",
      "priority": "P2",
      "kind": "bug",
      "rule": "README.md \"Errors\": every server action returns a typed result",
      "file": "src/register/actions.ts",
      "line": 42,
      "title": "A failed refetch empties the register instead of keeping the last rows.",
      "evidence": "`setRows(result.rows ?? [])` runs on the error branch too.",
      "failure": "The refetch after an approval times out and the user sees an empty register.",
      "recommendation": "Keep the previous rows when the result is an error, and show the error banner.",
      "decision": false
    }
  ],
  "coverage": [
    {"check": "Cognitive complexity (limit 8)", "status": "clean", "note": "measure_complexity.py: 0 of 14 changed functions over."}
  ]
}
```

- `pr` is the PR as your brief lists it. `file` and `line` point into that
  PR's pinned head.
- `rule` names what the code breaks: a repository document and its rule, a
  spec item, or a `pedro/...` rule ID.
- `title` is one sentence a reader of the PR understands without the rest.
- `evidence` quotes the code. Markdown is fine; fence code longer than a line.
- `failure` is the concrete scenario where it goes wrong, for a bug.
- `decision` is true when the fix needs a product, copy, scope, design, or
  architecture choice from the user.
- `coverage` status is `clean`, `findings`, `inapplicable`, or `incomplete`;
  the note is one sentence on what was checked or what is missing. An audit fills it for
  every check; other roles add what they could not verify, as `incomplete`.
- No findings is `"findings": []`.
