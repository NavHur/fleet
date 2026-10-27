# The guard does not queue what it cannot see

The catalogue (lib/host-check/jobclass.py) gives each leaf a job class, and
the guard sends a command to host-check when a leaf has any class but none.
Opaque leaves are the one exception. `eval`, an unexpanded `$` command, a
shell reading stdin, and a script the walk cannot read are heavy when
host-check admits a job, because it cannot tell what they cost. The guard lets
them run unqueued.

## Considered options

- **Queue opaque leaves too**, so the guard and the queue agree with no
  exception: the guard would then deny `eval "$(ssh-agent -s)"`, a bare
  `bash`, `"$EDITOR" file`, and every script it cannot read. That is a hook
  guessing that a command validates and blocking the agent on the guess.
- **Rate opaque leaves light, or none, in the queue too**: a hidden full suite
  would then take a light slot, which is the starvation the queue exists to
  prevent.

## Consequences

A job class is a question about cost; needing the queue is a question about
validation the guard can see. The two answers match on every leaf the walk
can see. Validation hidden behind an opaque leaf is covered by the policy in
host-validation.md, not by the hook, in line with ADR 0001: the guards are
habit guards, not security boundaries.
