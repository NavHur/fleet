#!/usr/bin/env bash
# Make a stack worktree ready for its gates; rerun after every checkout.
# Each step runs only when its input changed since the last run here, so a
# rerun on an unchanged tree costs a few hashes.
#   1. node_modules: a symlinked node_modules is removed (pnpm aborts on it
#      without a TTY), then `pnpm install --frozen-lockfile` when the lockfile
#      changed or node_modules is missing.
#   2. Prisma: `pnpm exec prisma generate` in each package holding a tracked
#      *.prisma file, when those files changed (a stale client breaks typecheck).
#   3. Repository hook, on the first run and when the schema changed:
#      nj-homes-choice-next  njhomes-sync-env DIR
#      receipt-hub           receipt-hub-test-db --worktree DIR (if installed)
#      SETUP_HOOK="command" replaces it ("skip" turns it off); it gets DIR as $1.
# Stamps live in $(git rev-parse --git-path split-stack-setup), per worktree.
#
# Usage: setup_worktree.sh [DIR]   (default: the current worktree)
set -euo pipefail

[[ ${1:-} == -h || ${1:-} == --help ]] && { sed -n '2,17p' "$0"; exit 0; }
root=$(git -C "${1:-.}" rev-parse --show-toplevel)
cd "$root"
stamps=$(git rev-parse --path-format=absolute --git-path split-stack-setup)
mkdir -p "$stamps"

changed() { # NAME FINGERPRINT: true (and records it) when it differs from the stamp
  [[ -f $stamps/$1 && $(<"$stamps/$1") == "$2" ]] && return 1
  printf '%s' "$2" >"$stamps/$1"
}

installed=0
if [[ -f pnpm-lock.yaml ]]; then
  [[ -L node_modules ]] && { echo "setup: removing symlinked node_modules"; rm node_modules; }
  lock=$(git hash-object pnpm-lock.yaml)
  if [[ ! -d node_modules ]] || changed install "$lock"; then
    echo "setup: pnpm install --frozen-lockfile"
    pnpm install --frozen-lockfile --config.confirm-modules-purge=false >"$stamps/install.log" 2>&1 ||
      { tail -20 "$stamps/install.log" >&2; rm -f "$stamps/install"; exit 1; }
    printf '%s' "$lock" >"$stamps/install"
    installed=1
  fi
fi

schema=$(git ls-files -s -- '*.prisma' | git hash-object --stdin)
schema_changed=0
if [[ -n $(git ls-files -- '*.prisma') ]] && { changed prisma "$schema" || ((installed)); }; then
  schema_changed=1
  for pkg in $(git ls-files -- '*.prisma' | while read -r f; do
      d=$(dirname "$f"); while [[ $d != . && ! -f $d/package.json ]]; do d=$(dirname "$d"); done; echo "$d"
    done | sort -u); do
    echo "setup: prisma generate in $pkg"
    if ! (cd "$pkg" && DATABASE_URL=${DATABASE_URL:-postgresql://placeholder@localhost:1/placeholder} \
        pnpm exec prisma generate >"$stamps/prisma.log" 2>&1); then
      tail -20 "$stamps/prisma.log" >&2; rm -f "$stamps/prisma"; exit 1
    fi
  done
fi

hook=${SETUP_HOOK:-}
if [[ -z $hook ]]; then
  remote=$(git remote get-url origin 2>/dev/null || git rev-parse --path-format=absolute --git-common-dir)
  repo=$(basename "${remote%.git}")
  [[ $repo == .git || $repo == git ]] && repo=$(basename "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")")
  case $repo in
    nj-homes-choice-next) hook=njhomes-sync-env ;;
    receipt-hub) command -v receipt-hub-test-db >/dev/null && hook="receipt-hub-test-db --worktree" ;;
  esac
fi
if [[ -n $hook && $hook != skip ]] && { [[ ! -f $stamps/hook ]] || ((schema_changed)); }; then
  echo "setup: $hook $root"
  $hook "$root"
  printf 'done' >"$stamps/hook"
fi
