# Fix rounds on an existing stack

Review rounds **converge locally, push once**. A round costs review and fix
time only; the per-layer gates, the push, its pre-push gates and the PR-body
refresh run once, after the last round. Gating every layer and pushing after
each round costs 25 to 75 minutes on this host, even for a three-line fix.

## Steps

1. **Manifests.** Reuse the build's, or derive them as in `SKILL.md`'s "Find
   the stack".
2. **Review.** Review the local layer heads (`git rev-parse` of each stack
   branch), not the pushed ones. Run `pedro-best-practices` audits
   local-only; a review loop posts its results after the push
   (`review-loop`'s finish step).
3. **Carry fixes down.** Make all fixes on one branch off the top (the fixed
   source), then carry them down into their layers from a worktree where no
   stack branch is checked out:

   ```bash
   bash "$SKILL_DIR/scripts/fix_layers.sh" --source "$fixed" --manifests "$plan/layers" --fix-msgs "$plan/fix-msgs"
   ```

   One commit per changed layer (message `fix-msgs/<layer>`, else
   `fix-msgs/default`), the layers above rebased along. A fix to a `~path`
   without a hook goes into the lowest layer it merges into cleanly. On a
   conflict it stops mid-rebase: resolve, `git rebase --continue`, rerun with
   `--from <next layer>`.
4. **Light check.** Between rounds, check the fixed source only (its tree
   equals the top layer): typecheck, lint and format on the round's changed
   files, and the repository's changed-tests command from
   [`repos.md`](repos.md), as one host-check job. The other layers wait for
   the publish step. A preview rebuild for the user also comes from the fixed
   source.
5. **Publish.** When the user asks to push or a round comes back without
   accepted findings: run `layer_gates.sh` under `bg-job` (see
   `host-validation.md`), then `refresh_stack.py --gates "$LOG_DIR"
   --update-prs`, then `gh stack push` once.

For a single later fix, change and push only the layer that owns the code;
restack descendants only when their dependency changed or the user asks.
