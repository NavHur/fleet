- Resolve ambiguity (which account, target, environment, or variant) by checking
  my request or asking me before acting, especially before outward-facing
  actions: creating repos, publishing, sending. Pushing follows the Git rules
  below.
- GitHub accounts resolve by the repo's git dir: `~/dca` → work
  (PedroNavHurDCA), `~/dev` → personal (PedroNavHur); worktrees follow their
  parent repo. Let the wrapper pick the account: `gh auth switch` and repo-local
  usernames break parallel work in the other account. Before creating or pushing
  a repo, check `gh auth status` matches the owner; if not, the environment is
  broken: stop and say so. (Machinery: `includeIf "gitdir:"` in ~/.gitconfig
  plus the `~/.local/bin/gh` wrapper, which sets `GH_CONFIG_DIR`.)
