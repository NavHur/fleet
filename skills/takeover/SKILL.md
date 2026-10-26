---
name: takeover
description: Take over existing work. Use when the user asks to take over a PR, branch, or agent thread, or requests a takeover.
---

# Takeover

Take responsibility for finishing the original goal while preserving the
original contributors' credit. Do not defend an implementation just because
another agent already built it.

Read the source PR, branch, or thread, including review findings and the user's
later corrections. Resolve the handoff to the actual code and current head,
and account for uncommitted work. Treat the handoff as context, not proof.

For a replacement PR, import the original commits onto a new branch and add
your fixes separately. Honor an explicitly requested in-place or stacked
continuation instead. Do not overwrite unrelated work or change the original
PR without authorization.

Preserve Git authorship and existing co-author trailers. Model attribution is
not a substitute for contributor credit.

Bring the continuation current with its intended base. Fetch the base and the
source head, then read what landed on the base since the branch diverged until
every change touching the branch's paths or behavior is accounted for: the same
problem solved another way, moved APIs or ownership, deleted or simplified
code, old behavior the branch would bring back. A clean rebase only proves the
lines merge. When the base has already made the goal moot, stop and report that
as the remaining decision. Otherwise rebase, resolve each conflict toward the
goal and the base's newer invariants, and compare the series before and after
with `git range-diff` to confirm every intended behavior survived. Rework what
is necessary to finish the same goal, not unrelated features. Simplify the implementation without dropping intended
behavior or surfaces. Recheck the source PR too: it may have improved while
you were working.

Independently verify the original failure and realistic workflows, following
repository guidance and permissions. Green mocked tests do not prove the user
experience works. State what remains unverified.

When the requested finish includes a PR, write up the work with the `pr` skill.
On a replacement PR, that write-up is its description: credit the original
contributors there and link the original PR. When you continue on a PR someone
else opened, leave their description as they wrote it and post the write-up as
a comment on that PR. Merge or close the original PR only when authorized.

Report what you inherited, what you changed, how you verified it, how credit
was preserved, and any remaining decision.
