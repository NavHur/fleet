# fleet

- Gate: `host-check make check` (lint, typecheck, tests, the same tools as CI); `make format` formats Rust.
- `config/instructions.md` is the shared part of every machine's global agent instructions (`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`); `bin/sync` writes it there, so edit it here.
- Resync after a merge: `bin/sync --all --apply` updates every machine. `bin/sync --apply` alone touches only this one, from its own checkout.
