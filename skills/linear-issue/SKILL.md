---
name: linear-issue
description: "Create a Linear issue from the request and conversation. Use when asked to create, file, or open a Linear issue or ticket; not for reading or updating existing issues."
---

# Linear Issue

Create the requested issue through the connected Linear tools. A clear request to create an issue authorizes that creation; do not ask for a second confirmation.

## Defaults

Apply these only when the user does not override them:

- Workspace: the connected NJ DCA workspace.
- Team: `Engineering`.
- Assignee: `me`.
- State: omit it so Linear uses the team's default state.
- Priority: `Medium` when omitted.
- Estimate: calculate the closest standard estimate from the described scope and complexity when omitted (`XS=1`, `S=2`, `M=3`, `L=5`, `XL=8`).
- Labels: always add the existing labels that match the issue's product area and kind of work. Infer them from the request, conversation, project, and affected code. Use the smallest useful set.
- Project: infer it only from an explicit project name, a recognized alias, or an unambiguous active repository. Otherwise ask for the project with the native question UI.

Resolve names through Linear at runtime; never hardcode UUIDs. Recognize these common aliases:

| User or repository wording | Linear project |
| --- | --- |
| DCAid, `dcaid` | DCAid Website |
| receipt, receipts, `receipt-hub` | Receipts Project |
| NJ Homes Choice, `nj-homes-choice`, `nj-homes-choice-next` | NJ HOMES Choice Tool |
| photo submission, `njhomes-photo-submission` | NJ HOMES Property Picture Submission form |
| tooling, developer tooling | Developer Platform |

When the user explicitly says `tooling` and gives no more specific project, use `Developer Platform` and add the existing `DevOps` label. A named project always wins over the repository mapping.

## Prepare the issue

1. Extract the requested team, project, assignee, priority, estimate, due date, labels, relations, and issue count. Accept common misspellings such as `stimate` as `estimate`.
2. Use the current conversation and relevant repository evidence when the user says `this`, `our findings`, `what we did`, or similar. Inspect the relevant diff or files if needed. Do not invent findings or completed work.
3. When the user omits them, set priority to `Medium`, calculate an estimate from the work's scope and complexity, and select related existing labels. Never leave priority, estimate, or labels unset.
4. Write a short, specific, imperative title. Improve rough wording without changing the requested scope.
5. Write a useful Markdown description. Preserve concrete details, source links, affected paths or URLs, constraints, and rationale. Use only the sections that help, commonly `Context`, `Work`, `Findings`, `Sites`, `Deadline`, and `Done when`.
6. Turn explicit success conditions into unchecked task-list items. Do not invent acceptance criteria. Never mark work complete merely because the conversation says code was changed; use checked items only when the user is explicitly documenting completed work.

## Dates and deadlines

- Interpret business dates and unqualified times in `America/New_York` unless the user specifies another timezone.
- Resolve relative dates to an exact calendar date before creation.
- Linear issue due dates are date-only. Set `dueDate` to `YYYY-MM-DD`; include the exact time and timezone in the description.
- Preserve timing instructions such as same-day execution, meeting cutoffs, or invalidation windows under `Deadline` or `Operational constraints`.
- If a relative date is genuinely ambiguous, ask one concise question with the native question UI.

## Create and verify

1. Resolve the team, project, `me`, and related labels with Linear. Let Linear match the standard numeric estimate (`XS=1`, `S=2`, `M=3`, `L=5`, `XL=8`) and priority (`Urgent=1`, `High=2`, `Medium=3`, `Low=4`). Use only labels that already exist. If no existing label credibly fits, ask the user to choose one instead of creating the issue without labels.
2. Search narrowly for an obvious open duplicate using the proposed title's distinctive terms. Ask through the native question UI only when a likely duplicate exists; otherwise continue.
3. Create exactly the requested number of issues. Prefer one `save_issue` call per issue with all known fields set at once.
4. Fetch each created issue and verify its title, team, project, assignee, priority, estimate, due date, labels, and description. Correct a mismatched field on that same issue rather than creating another.
5. Do not create sub-issues, reminders, cycles, labels, or relations unless the user requested them. Do not silently replace an unavailable project or label with a different one.

Report each issue's identifier, linked title, project, assignee, priority, estimate, and due date. Keep the handoff concise.
