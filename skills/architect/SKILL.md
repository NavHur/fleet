---
name: architect
description: "Design types, signatures, and module boundaries before code, then guide implementation. Use for /architect, 'design this', or non-trivial features where interfaces or ownership come first; not for local edits or debugging."
---

# Architect

For agent dispatch and lifecycle in T3 Code, read
`~/.config/t3-orchestration.md`. It governs provider/model selection,
workspace binding, complete briefs, and automatic completion delivery.

Design before implementing. Sketch types, function signatures, class shapes, and module boundaries with `not implemented` bodies and pseudocode. Synthesize across multiple model perspectives, then fill in code against the chosen sketch. If implementation proves the sketch wrong, throw it out and redesign.

## Start

Track one entry per phase with the available planning mechanism so phase position and completion stay visible.

1. Ground
2. Sketch
3. Agree
4. Implement
5. Scrap

## Phase A: Ground the problem

Build a real mental model of every system the new code touches. Run the **how** skill over the relevant subsystems. Critique mode if existing structure is the constraint or the design must push back on it.

Naming a file isn't grounding. Produce the traced model `how` prescribes. If the design redefines ownership or layering, also run the **why** skill on the existing shape so the rationale becomes a constraint, not a guess.

Skip Phase A only when the work is genuinely greenfield with no surrounding system to integrate.

## Phase B: Sketch

Fan out parallel candidate runners on the design-sketch task, then graft the strongest parts of the losers into the best base.

In T3, launch one `delegate_task` per independent candidate, `role: "design"`,
`mode: "async"`, with the complete runner prompt, grounding artifacts, and its
own output path. Use three different models, resolved from the live catalog: Claude Opus 5.5 and Claude Haiku 5.5, or Sonnet 5.5 when its context will pass 100K tokens, on the Claude provider with the requested effort or inherited options, and `gpt-6.1-sol` on Codex at xhigh.
Keep repository source read-only. Return the sketch as text or write only to a
unique `/tmp/architect-<slug>/runner-<n>/` artifact directory. These directories
separate outputs; all child tasks remain bound to the parent's checkout.
Use a workspace-capable native child tool when actual isolated source edits
are required, following the shared workspace contract. Await automatic results
before synthesis. Model diversity matters; preserve distinct candidates.

Each candidate produces a design package shaped per `references/rationale-template.md`: the caller's usage written first, then the type sketch, function signatures, module map, and prose rationale derived from it.

Once all runners return, pick the base candidate, then graft the strongest parts of the others into it. The result is one synthesized design package. Say which candidate was the base and what you grafted; that populates the rationale's "Synthesis decision" section.

Design it twice. Require at least two structurally distinct candidates before synthesis, even when the first looks sufficient. This is the **exhaust-the-design-space** principle (`~/.agents/skills/principle-exhaust-the-design-space/SKILL.md`) made concrete. Whole-shape alternatives, not point fixes inside one shape.

Screen every candidate against [`references/design-red-flags.md`](references/design-red-flags.md) before synthesis. Reject or revise shallow modules, information leakage, temporal decomposition, and pass-through methods.

Compare viable candidates on interface depth. Prefer the design that hides more complexity behind a smaller, simpler public surface. A rich interface can keep call chains short by concentrating capability instead of scattering it across layers.

## Phase C: Agree (opt-in)

Default: proceed directly to implementation with the synthesized design. No human checkpoint.

Opt in to a checkpoint when the invoker explicitly asks: "/architect with checkpoint," "stop and show me before implementing," or similar. Then surface the synthesized design and pause for sign-off.

The synthesis can ship as its own commit either way. That's the "scaffold first" mode of the **foundational-thinking** principle (`~/.agents/skills/principle-foundational-thinking/SKILL.md`); subsequent commits read as filling in bodies against a stable contract. Planned and scoped breakage during fill-in is fine, per the **outcome-oriented-execution** principle (`~/.agents/skills/principle-outcome-oriented-execution/SKILL.md`). For adversarial pressure on the design before implementing, run the **how** skill in critique mode over the synthesized sketch. In Claude Code you can also ask the user to run `/code-review ultra`; it is user-triggered and billed, so you cannot launch it yourself.

If the human pushes back on the shape (in a checkpoint or after the fact), treat that as Phase A evidence. Re-ground and re-run Phase B before writing more code.

## Phase D: Implement against the sketch

Replace `not implemented` bodies with code, pseudocode with logic. The synthesized sketch is the contract.

Deviations from the sketch are signal worth surfacing, not friction to absorb silently. If a function needs a parameter the sketch didn't anticipate, ask whether the sketch was wrong, the requirement was missed, or the implementation is overreaching. Surface it; don't bolt it on.

## Phase E: Scrap when the architecture is wrong

If implementation keeps producing friction the sketch can't absorb, throw the sketch out. Don't bolt fixes onto a wrong design, per the **redesign-from-first-principles** and **fix-root-causes** principle (`~/.agents/skills/principle-fix-root-causes/SKILL.md`)s.

The signal is a *pattern*, not single instances. Tells:

- The same shape of workaround appearing repeatedly across unrelated code.
- Multiple unrelated edge cases that all need special-case branches.
- Types that need escape hatches (`any`, casts, optional fields always set in practice) to compile.
- The "we need a lock" reflex when the sketch said the state wasn't shared.
- Callers having to know the abstraction's internal rules to use it.
- Two or more independent Phase D deviations of the same shape across the implementation. Surfacing deviations is Phase D's job; a repeated pattern of them is Phase E's trigger.

Use judgment. A few edge cases don't condemn an architecture. Some problems are legitimately complex; complexity in the data is not complexity in the design. The rewrite signal is repeated friction of the same shape, not single hard cases.

When you scrap:

1. Re-run the **how** skill over what's been built. The implementation lessons enter the new design as inputs, not vibes.
2. Redesign as if the new constraints had been day-one assumptions, per the **redesign-from-first-principles** principle (`~/.agents/skills/principle-redesign-from-first-principles/SKILL.md`).
3. Subtract before adding, per the **subtract-before-you-add** principle (`~/.agents/skills/principle-subtract-before-you-add/SKILL.md`). The new sketch should be smaller than the old one before it grows.
4. Return to Phase B and re-run the candidate fan-out.

## Outputs

The caller's usage is written first and the type sketch derived from it. One file with new types and signatures for small changes; module map plus type definitions for larger work. The rationale ships alongside, shaped per `references/rationale-template.md`, including the usage sketch and the synthesis decision.
