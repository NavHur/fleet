# Repository setup and gate commands

The scripts default to a pnpm workspace. This file holds what differs by
repository; the scripts' `--help` holds the full option lists.

## Worktree setup

`setup_worktree.sh` prepares a scratch worktree and reruns before every
layer's gates, each step only when its input changed:

1. Removes a symlinked `node_modules` (pnpm aborts on one without a TTY), then
   runs `pnpm install --frozen-lockfile`.
2. Runs `prisma generate` in each package with a tracked `*.prisma` file.
3. Runs the repository hook: `njhomes-sync-env` for nj-homes-choice-next,
   `receipt-hub-test-db --worktree` for receipt-hub. `SETUP_HOOK="command"`
   replaces it; `SETUP_HOOK=skip` turns it off.

## Import alias

`import_graph.py --alias` maps a path alias to its directory. nj-homes-choice-next
uses `--alias '@/=apps/web/src/'`; repeat the flag for each alias a repository
defines in its `tsconfig.json` `paths`.

## Gate commands

`layer_gates.sh` runs each step in `--app` (the package holding the app, such
as `apps/web` in nj-homes-choice-next). Override a step with an environment
variable holding a shell snippet, or `skip`:

| Step | Variable | Default |
| --- | --- | --- |
| typecheck | `TYPECHECK_CMD` | `pnpm typecheck` |
| lint | `LINT_CMD` | `pnpm lint` |
| format | `FORMAT_CMD` | `pnpm exec oxfmt --check` (gets the changed files) |
| tests | `TEST_CMD` | `pnpm exec vitest run --testTimeout=20000 --changed` (gets the stack base) |

For a repository without pnpm, set all four from its own scripts (its
`Makefile` or `package.json`), and pass `--no-setup` when it needs no install.

## Changed-tests command

A fix round's light check runs only the tests the round touched: in a vitest
repository, `vitest run --changed <previous fixed source>`; elsewhere the
repository's test command scoped to the changed files, or the whole suite when
it has no scoping.

## Generated data

`refresh_stack.py` defaults its generated globs to nj-homes-choice-next's data
exemptions (`data/*.json`, Prisma migrations, `*.geojson`); pass `--generated`
in other repositories to replace them.
