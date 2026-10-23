---
name: council
description: Three models Pedro names propose alternatives to a question he cannot answer, argue over them once, and hand him one decision.
disable-model-invocation: true
---

# Council

Pedro invokes this when you asked him something and he genuinely does not
know what to do. Three members, each on a model he names, look for
alternatives independently, then argue once over all of them; he gets one
table and one question. Read `~/.config/t3-orchestration.md` before
dispatching.

## Invocation

- **Members**: three models, each with an optional effort, such as
  `gpt-6.1-sol xhigh, claude-fable-5-1 max, opencode/gemini-4-argon high`.
  Ask once if he named fewer than three.
- **Question**: the one in his message, else the last question you asked him.

## 1. Seat the members

Call `orchestrator_capabilities` and find each model's provider instance. Put
the effort in `target.options` under that model's own option id (Codex
`reasoningEffort`, Claude `effort`, OpenCode `variant`). A model or effort the
catalog lacks stops the council: report the mismatch, with no substitute. The
same model in two seats is allowed; say in the final table that those members
share blind spots.

Done when every member has a provider instance, model, and options.

## 2. Frame the brief

Write the brief each member gets as its whole context:

- the question, stated as a decision;
- what is known: facts, constraints, and Pedro's preferences that bear on it;
- what is already ruled out, and why;
- the repository path and pinned revision, and the files, docs, or threads
  worth reading;
- the rules: read-only (the checkout, branches, and services stay as found);
  checks only through `~/.local/bin/host-check`.

Done when a member who has seen none of this conversation could answer from
the brief alone.

## 3. Propose

Launch the three at once with `delegate_task`, `mode: "async"`,
`role: "research"`, `clientRequestId` `council-<slug>-propose-<n>`, and the
brief plus this ask:

> Give two or three alternatives, at least one of them removing the need for
> this decision rather than answering it. For each: what it is, what it costs,
> what it risks, and the evidence (code, docs, or a check you ran) behind
> that. End with your pick and the one fact that would change it.

Members see no sibling's work. End the turn; completions wake you. Done when
all three proposals are in, or a failed member is reported and two remain.
With fewer than two, stop and report.

## 4. Argue

Merge the proposals into one list of distinct alternatives, labelled A, B, C,
with no member names. Add your own objections, each with its evidence. Launch
one round, `clientRequestId` `council-<slug>-argue-<n>`, giving each member
the brief, the full list, and your objections:

> Make the strongest case against every alternative, your own included. Then
> hold or change your pick, with the evidence that decided it. An objection
> without evidence counts for nothing.

Done when every seated member has answered. There is no second round.

## 5. Decide

Show Pedro one table: each alternative, who picked it (model names now), the
strongest objection standing against it, and the dissent. Under it, your
recommendation and the fact it rests on. Then ask him with
`AskUserQuestion`, your recommendation first. He makes the call; resume the work
that raised the question with his answer.
