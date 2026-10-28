# fleet

- Gate: `host-check make check` (lint, typecheck, tests, the same tools as CI); `make format` formats Rust.
- `config/instructions.md` is the shared part of every machine's global agent instructions (`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`); `bin/sync` writes it there, so edit it here.
