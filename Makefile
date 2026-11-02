# fleet's gate: the checks CI runs. The pre-commit skill reads these targets;
# `make check` runs all but format. Run it through host-check.
# BASE=origin/main limits the Python suites to those the changes since BASE touch.
SCRIPTS := bin/sync bin/test skills/t3-remote/scripts/t3-remote $(shell git ls-files '*.sh')

.PHONY: check format lint typecheck test
check: lint typecheck test

format:
	cargo fmt --all

lint:
	@command -v ruff >/dev/null || { echo "ruff is missing: run bin/sync --apply" >&2; exit 127; }
	ruff check
	cargo fmt --all --check
	cargo clippy --locked --all-targets -- -D warnings
	@for script in $(SCRIPTS); do bash -n "$$script" || exit 1; done

typecheck:
	cargo check --locked --all-targets

test:
	bin/test $(if $(BASE),--changed $(BASE))
	cargo test --locked
