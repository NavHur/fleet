# The command walk recognizes spellings instead of parsing shell

The walk (lib/host-check/walk.py, over shell.py's lexing) reads a shell
string with the standard library: shlex, plus passes for heredocs, comments,
and `$(...)`. It recognizes the spellings agents write rather than parsing
the shell grammar. Every hook runs it on each tool call under the host's
system python3, with no virtualenv or installed packages, on macOS and Linux
alike, so a dependency such as bashlex or tree-sitter-bash would have to be
installed on every host and every python before any guard could load, and a
guard that fails to import stops guarding.

## Considered options

- **bashlex or tree-sitter-bash**: a real grammar, but a package on every host
  and every python3, and a hook that does nothing where it is missing.
- **A walker per judge**: what came before. Each judge recognized its own
  spellings, and fixes landed in one walker while the others drifted.

## Consequences

Each spelling the walk misses is fixed in walk.py once, with a test in
test_walk.py, and every judge picks it up. The guards are habit guards, not
security boundaries: a command written to evade them still can.
