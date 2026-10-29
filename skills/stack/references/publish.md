# Publish a stack

Open one PR per layer with native GitHub stacks, write every body, and report
the stack. Publishing is done when each PR targets its direct parent, the
bottom PR targets the base, and every body carries current size and gate lines.

## Open the PRs

```bash
gh stack init --base "$base_branch" "$branch_1" "$branch_2" "$branch_3"
gh stack submit --auto
gh stack view
```

`--auto` opens drafts. When the `origin` owner is `PedroNavHur`, add `--open`
so they open ready for review; for any other owner, keep them draft.

## Write the bodies

Write every PR body with the `pr` skill's template. Under Summary, add why the
boundary is atomic and the layer's parent and next layer; under Merge Danger,
add notes on migrations, rollout order, and generated output. Then write the
size and gate lines into every body:

```bash
python3 "$SKILL_DIR/scripts/refresh_stack.py" --manifests "$plan/layers" --prefix "<source>-" \
  --base "$merge_base" --gates "$LOG_DIR" --update-prs
```

Verify each PR targets its direct parent and the bottom PR targets the base.
Close or supersede the original PR only when the user authorized it.

## Report

Return `refresh_stack.py`'s table as it prints it, and add each PR's link and
parent, the reason for any `small` layer, and any `Size-Exception` trailer.
State the disposition of the original PR, the source branch, the temporary
worktree and the safety branch.
