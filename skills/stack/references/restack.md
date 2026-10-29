# Restack onto a moved base

When the base moved ("we fell behind nightly"), restack every open layer at
once, chained stacks included, bottom to top:

```bash
python3 "$SKILL_DIR/scripts/restack.py" start --base origin/nightly "$branch_1" "$branch_2" "$branch_3" --push
```

It rebases each layer onto the new tip of the one below in a scratch worktree,
which also moves seams `gh stack rebase` skips, reports any layer whose own
diff changed, runs `layer_gates.sh` (add `--tests` for the top layer's tests), and pushes
every branch in one atomic leased push only when the gates pass. Exit 3 is a
conflict: resolve it in the printed worktree, `git rebase --continue`, then
`restack.py resume STATE_DIR --push`. Pass `--old-base` when a lower layer was
squash-merged into the base. Finish with `restack.py clean STATE_DIR`.

The restack is done when the push lands; report any layer whose own diff
changed.
