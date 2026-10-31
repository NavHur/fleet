---
name: council
description: Three models Pedro names propose alternatives to a question he cannot answer, argue over them once, and hand him one decision.
disable-model-invocation: true
---

# Council

Pedro invokes this when you asked him something and he genuinely does not
know what to do. Read `~/.config/t3-orchestration.md` before dispatching.

## Invocation

- **Members**: three models, each with an optional effort, such as
  `gpt-6.1-sol xhigh, claude-fable-5-1 max, opencode-go/gemini-4-argon high`.
  Ask once if he named fewer than three.
- **Question**: the one in his message, else the last question you asked him.
  Give it a short kebab-case `<slug>` for the task IDs.

## 1. Seat the members

Call `orchestrator_capabilities` and find each model's provider instance. Put
the effort in `target.options` under the option id the catalog lists for that
model. A model or effort the catalog lacks stops the council: report the
mismatch, with no substitute.

Done when every member has a provider instance, model, and options.

## 2. Frame the brief

Write the brief each member gets as its whole context:

- the question, stated as a decision;
- what is known: facts, constraints, and Pedro's preferences that bear on it;
- what is already ruled out, and why;
- the repository path and pinned revision, and the files, docs, or threads
  worth reading;
- read-only: the checkout, branches, and services stay as the member found
  them.

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

Done when all three proposals are in, or a failed member is reported and two
remain. With fewer than two, stop and report.

## 4. Argue

Merge the proposals into one list of distinct alternatives, lettered from A,
with no member names. Add your own objections, each with its evidence. Launch
the one argue round, `clientRequestId` `council-<slug>-argue-<n>`, giving each
member the brief, the full list, and your objections:

> Make the strongest case against every alternative, your own included. Then
> hold or change your pick, with the evidence that decided it. An objection
> without evidence counts for nothing.

Done when every member seated in step 3 has answered or been reported failed.
The verdict follows from this round.

## 5. Decide

Show Pedro one table: each alternative, who picked it (model names now), the
strongest objection standing against it, and the dissent. Note any model that
sat twice: those members share blind spots. Under the table, your
recommendation and the fact it rests on.

Then ask him with `AskUserQuestion`, which takes two to four options: your
recommendation first, then the alternatives with the most picks. He makes the
call; resume the work that raised the question with his answer.
