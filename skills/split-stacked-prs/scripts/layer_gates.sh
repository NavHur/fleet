#!/usr/bin/env bash
# Run the checks on every layer, bottom to top, each against its own parent.
# Tests run once, on the top layer, against the stack base: that covers every
# layer's changes. --tests-each runs them on every layer against its parent,
# to find the layer that broke one; otherwise lower layers report tests=deferred.
#
# Outside the shared CPU queue it re-executes itself once under
# `HOST_CHECK_CLASS=heavy host-check`; do not wrap it yourself. It prints the
# log directory first. Follow LOG_DIR/progress (one line per step, written as
# it happens; the last line starts with "done"); LOG_DIR/<name>.log holds the
# output and LOG_DIR/<name>.result the layer's commit and verdicts, which
# refresh_stack.py --gates reads.
#
# Before each layer: setup_worktree.sh (install, prisma generate, repo hook;
# each only when its input changed). Skip it with --no-setup. Then each commit
# of the layer but its tip gets typecheck, lint and format on its own changed
# files (commits=OK|FAIL, or none for a one-commit layer).
# Steps per layer, each overridable by environment variable (run in --app):
#   TYPECHECK_CMD  default: pnpm typecheck
#   LINT_CMD       default: pnpm lint
#   FORMAT_CMD     default: pnpm exec oxfmt --check   (gets the layer's changed files)
#   TEST_CMD       default: pnpm exec vitest run --testTimeout=20000 --changed
#                  (gets the stack base, or the parent with --tests-each)
# A command is a shell snippet; its arguments arrive as "$@". Set a step to
# "skip" to leave it out.
#
# Usage:
#   layer_gates.sh --manifests DIR [--base REF] [--prefix PREFIX] [--app DIR]
#                  [--log-dir DIR] [--only NAME] [--no-setup] [--tests-each]
set -uo pipefail

usage() { sed -n '2,29p' "$0"; }
base= manifests= prefix= app=. log_dir= only= setup=1 tests_each=0
args=("$@")
while (($#)); do
  case $1 in
    --base) base=$2; shift 2 ;;
    --manifests) manifests=$2; shift 2 ;;
    --prefix) prefix=$2; shift 2 ;;
    --app) app=$2; shift 2 ;;
    --log-dir) log_dir=$2; shift 2 ;;
    --only) only=$2; shift 2 ;;
    --no-setup) setup=0; shift ;;
    --tests-each) tests_each=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n $manifests ]] || { usage >&2; exit 2; }

script_dir=$(cd "$(dirname "$0")" && pwd)
. "$script_dir/lib.sh"
manifests=$(cd "$manifests" && pwd)

base=$(stack_base "$manifests" "$base")
[[ -n $base ]] || { echo "no --base and no '# base:' header in the first manifest" >&2; exit 2; }
typecheck_cmd=${TYPECHECK_CMD:-pnpm typecheck}
lint_cmd=${LINT_CMD:-pnpm lint}
format_cmd=${FORMAT_CMD:-pnpm exec oxfmt --check}
test_cmd=${TEST_CMD:-pnpm exec vitest run --testTimeout=20000 --changed}

mapfile -t branches < <(for n in $(layer_names "$manifests"); do layer_branch "$manifests" "$n" "$prefix"; done)
busy=$(branches_checked_out_elsewhere "${branches[@]}")
if [[ -n $busy ]]; then
  echo "stack branches checked out in other worktrees (detach them first):" >&2
  sed 's/^/  /' <<<"$busy" >&2
  exit 1
fi
if [[ -n $(git status --porcelain --untracked-files=no) ]]; then
  echo "uncommitted changes in $(git rev-parse --show-toplevel); commit or stash them first" >&2
  exit 1
fi

if [[ -z $log_dir ]]; then
  log_dir=$(mktemp -d /tmp/layer-gates-XXXX)
  args+=(--log-dir "$log_dir")
fi
mkdir -p "$log_dir"
log_dir=$(cd "$log_dir" && pwd)
progress=$log_dir/progress

if [[ ${HOST_CHECK_ACTIVE:-} != 1 ]] && command -v host-check >/dev/null; then
  echo "logs: $log_dir (follow $progress)"
  echo "$(date +%T) queued in host-check" >>"$progress"
  HOST_CHECK_CLASS=heavy exec host-check bash "$0" "${args[@]}"
fi

root=$(git rev-parse --show-toplevel)
start=$(git rev-parse --abbrev-ref HEAD)
[[ $start == HEAD ]] && start=$(git rev-parse HEAD)
app_prefix=$(cd "$root/$app" && git rev-parse --show-prefix)
failed=0
parent=$base
top=$(layer_names "$manifests" | tail -1)
echo "logs: $log_dir"
note() { echo "$(date +%T) $*" >>"$progress"; }
note "start base=$(git rev-parse --short "$base")"

tests_step() { # the tests verdict for layer $name
  if ((tests_each)); then
    step tests "$test_cmd" "$parent"
  elif [[ $name == "$top" ]]; then
    step tests "$test_cmd" "$base"
  else
    echo tests=deferred
  fi
}

step() { # label command [args...]; prints label=OK|FAIL|skip
  local label=$1 cmd=$2 started=$SECONDS verdict; shift 2
  if [[ $cmd == skip ]]; then echo "$label=skip"; return; fi
  note "$name $label start"
  echo "### $label: $cmd $*" >>"$log"
  if (cd "$root/$app" && bash -c "$cmd \"\$@\"" "$label" "$@") >>"$log" 2>&1; then verdict=OK; else verdict=FAIL; fi
  note "$name $label $verdict $((SECONDS - started))s"
  echo "$label=$verdict"
}

commits_step() { # typecheck, lint and format on each commit of layer $name but its tip; sets commits_verdict
  local -a shas cfiles; local sha short out
  mapfile -t shas < <(git rev-list --reverse --first-parent "$parent..HEAD" | sed '$d')
  commits_verdict=none
  ((${#shas[@]})) || return 0
  commits_verdict=OK
  for sha in "${shas[@]}"; do
    short=$(git rev-parse --short "$sha")
    note "$name commit $short"
    echo "### commit $short" >>"$log"
    git checkout -q --detach "$sha" || { commits_verdict=FAIL; break; }
    if ((setup)) && ! bash "$script_dir/setup_worktree.sh" "$root" >>"$log" 2>&1; then commits_verdict=FAIL; break; fi
    mapfile -t cfiles < <(git -c core.quotePath=false diff --name-only --diff-filter=d "$sha^" "$sha" -- "$root/$app" | sed "s#^$app_prefix##")
    out=$(step typecheck "$typecheck_cmd"; step lint "$lint_cmd"; ((${#cfiles[@]})) && step format "$format_cmd" "${cfiles[@]}")
    note "$name commit $short ${out//$'\n'/ }"
    if [[ $out == *FAIL* ]]; then commits_verdict=FAIL; break; fi
  done
  git checkout -q "$branch" || { commits_verdict=FAIL; return; }
  if ((setup)) && ! bash "$script_dir/setup_worktree.sh" "$root" >>"$log" 2>&1; then commits_verdict=FAIL; fi
}

for name in $(layer_names "$manifests"); do
  branch=$(layer_branch "$manifests" "$name" "$prefix")
  if [[ -n $only && $name != "$only" ]]; then parent=$branch; continue; fi
  if ! git checkout -q "$branch"; then
    echo "$name: cannot check out $branch"; note "$name checkout FAIL"; failed=1; break
  fi
  log=$log_dir/$name.log
  : >"$log"
  if ((setup)); then
    note "$name setup"
    if ! bash "$script_dir/setup_worktree.sh" "$root" >>"$log" 2>&1; then
      echo "$name setup=FAIL (see $log)"; note "$name setup FAIL"; failed=1; parent=$branch; continue
    fi
  fi
  mapfile -t files < <(git -c core.quotePath=false diff --name-only --diff-filter=d "$parent" HEAD -- "$root/$app" | sed "s#^$app_prefix##")
  commits_step
  results=(
    "$(step typecheck "$typecheck_cmd")"
    "$(step lint "$lint_cmd")"
    "$( ((${#files[@]})) && step format "$format_cmd" "${files[@]}" || echo format=none)"
    "commits=$commits_verdict"
    "$(tests_step)"
  )
  [[ ${results[*]} == *FAIL* ]] && failed=1
  summary=$(grep -E '^ +(Test Files|Tests) ' "$log" | tr -s ' ' | tr '\n' ' ')
  echo "$name ${results[*]}${summary:+ :: $summary}"
  echo "$(git rev-parse HEAD) $branch ${results[*]}${summary:+ :: $summary}" >"$log_dir/$name.result"
  note "$name ${results[*]}"
  parent=$branch
done

git checkout -q "$start" 2>/dev/null
note "done exit=$failed"
echo "logs: $log_dir"
exit $failed
