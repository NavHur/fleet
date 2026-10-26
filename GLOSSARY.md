# Fleet

Pedro's machines, the agent skills and hooks they share, and the host-check
queue that keeps validation from starving interactive work.

## Command walk

**Leaf**:
One command a shell string runs, in the directory it runs in, reached past
wrappers, runners, shell strings, scripts, and package scripts.
_Avoid_: segment, unwrapped command

**Walk**:
The reading of a shell string into its leaves. There is one walk; every judge
reads its leaves.
_Avoid_: parser, walker, unwrapper

**Wrapper**:
A command that runs its arguments as a command (`env`, `timeout`, `setsid`,
`host-check`, `bg-job start`).
_Avoid_: prefix

**Runner**:
A command whose verb runs another command (`uv run`, `uvx`, `poetry run`).
Package runners (`pnpm`, `npx`, `turbo`) run package scripts and executables
and stay leaves of their own.
_Avoid_: launcher

**Opaque leaf**:
A leaf whose commands the walk cannot see: `eval`, an unexpanded `$` command,
a shell reading stdin, a script it cannot read or parse, the depth limit.
_Avoid_: unknown command

**Expanded leaf**:
A script or package runner whose commands the walk also yields as the leaves
after it.

**Judge**:
A check that answers one question of each leaf: needs the queue, starts a dev
server, job class, merge method, commit size, agent launch, migration, runs
tests.
_Avoid_: walker, guard (for the check itself)
