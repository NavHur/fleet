#!/usr/bin/env bash
# Carry fixes from a fixed source into an existing stack: one fix commit per
# layer that changes, with the layers above rebased along by
# `git rebase --update-refs`.
#
# The fixed source is the old top (or the old source) plus fix commits.
# Works with manifests from build_layers.sh or derive_manifests.py (format in
# lib.sh). Per layer, plain paths are taken whole from the fixed source;
# ~paths are rewritten by hooks/<name>, or without a hook get the fix by a
# 3-way merge (old top -> fixed source) when it applies cleanly to the layer's
# version; otherwise that fix lands in the path's final layer. A rebase
# conflict on a path the replayed layer regenerates anyway (plain, or staged
# with a hook) is resolved automatically. Any other conflict stops with the
# rebase in progress: resolve it, `git rebase --continue`, then rerun with
# --from <next layer>.
#
# Run in a worktree where no stack branch is checked out elsewhere.
# Commit message: FIX_MSG_DIR/<name>, else FIX_MSG_DIR/default.
#
# Usage:
#   fix_layers.sh --source REF --manifests DIR --fix-msgs DIR [--prefix PREFIX] [--base REF] [--from NAME]
set -euo pipefail

source= manifests= prefix= fix_msgs= base= from=
while (($#)); do
  case $1 in
    --source) source=$2; shift 2 ;;
    --manifests) manifests=$2; shift 2 ;;
    --prefix) prefix=$2; shift 2 ;;
    --fix-msgs) fix_msgs=$2; shift 2 ;;
    --base) base=$2; shift 2 ;;
    --from) from=$2; shift 2 ;;
    -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n $source && -n $manifests && -n $fix_msgs ]] || { sed -n '2,21p' "$0" >&2; exit 2; }

script_dir=$(cd "$(dirname "$0")" && pwd)
. "$script_dir/lib.sh"
manifests=$(cd "$manifests" && pwd)
source_sha=$(git rev-parse "$source^{commit}")
base=$(stack_base "$manifests" "$base")
base_sha=$([[ -n $base ]] && git rev-parse "$base^{commit}" || true)
read_layers "$manifests" "$prefix"
declare -A branch_of=()
for i in "${!names[@]}"; do branch_of[${names[i]}]=${branches[i]}; done
top=${branch_of[${names[-1]}]}

busy=$(branches_checked_out_elsewhere "${branch_of[@]}")
if [[ -n $busy ]]; then
  echo "stack branches checked out in other worktrees (detach them first):" >&2
  sed 's/^/  /' <<<"$busy" >&2
  exit 1
fi

if [[ -n $(git status --porcelain) ]]; then
  echo "uncommitted or untracked files in $(git rev-parse --show-toplevel); clean the worktree first" >&2
  exit 1
fi
heads_file=$(dirname "$manifests")/pre-fix-heads.txt
if [[ -z $from ]]; then
  for name in "${names[@]}"; do echo "$name $(git rev-parse "${branch_of[$name]}")"; done >"$heads_file"
  echo "previous heads saved to $heads_file"
elif [[ ! -f $heads_file ]]; then
  echo "--from needs $heads_file from the first run" >&2; exit 1
fi
old_top=$(awk -v n="${names[-1]}" '$1 == n { print $2 }' "$heads_file")

regenerated() { # NAME PATH: does this layer's fix step rewrite PATH whole?
  whole_paths "$manifests/$1" | grep -qxF -- "$2" && return 0
  [[ -x $manifests/hooks/$1 ]] && staged_paths "$manifests/$1" | grep -qxF -- "$2"
}

merge_staged() { # NAME PATH: 3-way merge the fix into this layer's in-between version
  local path=$2 tmp
  [[ -f $path ]] && git cat-file -e "$old_top:$path" 2>/dev/null && git cat-file -e "$source_sha:$path" 2>/dev/null || return 0
  tmp=$(mktemp -d)
  git show "$old_top:$path" >"$tmp/base"
  git show "$source_sha:$path" >"$tmp/theirs"
  if git merge-file -q -p "$path" "$tmp/base" "$tmp/theirs" >"$tmp/out"; then
    cat "$tmp/out" >"$path"
  else
    echo "$1: the fix to ~$path overlaps a later layer's lines; it lands in a later layer"
  fi
  rm -rf "$tmp"
}

rebase_up() { # BRANCH OLD_HEAD LAYER_INDEX
  local -A replayed_in=() # pre-rebase head -> layer name, for layers above
  local -a order=() unresolved=()
  local i commit layer path
  for ((i = $3 + 1; i < ${#names[@]}; i++)); do
    order+=("$(git rev-parse "${branch_of[${names[i]}]}")")
    replayed_in[${order[-1]}]=${names[i]}
  done
  local seen=
  git -c core.hooksPath=/dev/null rebase -q --update-refs --onto "$1" "$2" "$top" >/dev/null 2>&1 || true
  while [[ -d $(git rev-parse --git-path rebase-merge) ]]; do
    commit=$(git rev-parse REBASE_HEAD)
    if [[ $commit == "$seen" ]]; then
      echo "rebase stuck at $commit; see git status" >&2; exit 1
    fi
    seen=$commit
    layer=
    for head in "${order[@]}"; do
      if git merge-base --is-ancestor "$commit" "$head"; then layer=${replayed_in[$head]}; break; fi
    done
    unresolved=()
    while IFS= read -r path; do
      [[ -z $path ]] && continue
      if [[ -n $layer ]] && regenerated "$layer" "$path"; then
        if git cat-file -e "REBASE_HEAD:$path" 2>/dev/null; then git checkout -q --theirs -- "$path"; else git rm -q -- "$path"; fi
        git add -- "$path"
        echo "  auto-resolved $path (layer $layer rewrites it)"
      else
        unresolved+=("$path")
      fi
    done < <(git -c core.quotePath=false diff --name-only --diff-filter=U)
    if ((${#unresolved[@]})); then
      echo "rebase conflict in layer ${layer:-?} while carrying ${names[$3]} up the stack:" >&2
      printf '  %s\n' "${unresolved[@]}" >&2
      echo "resolve, 'git rebase --continue', then rerun with --from <the layer after ${names[$3]}>" >&2
      exit 1
    fi
    if git diff --cached --quiet HEAD; then
      git -c core.hooksPath=/dev/null rebase --skip -q 2>/dev/null || true
    else
      GIT_EDITOR=true git -c core.hooksPath=/dev/null rebase --continue >/dev/null 2>&1 || true
    fi
  done
  if ! git merge-base --is-ancestor "$1" "$top"; then
    echo "rebase of the layers above ${names[$3]} did not complete" >&2; exit 1
  fi
}

started=$([[ -z $from ]] && echo 1 || echo 0)
parent=$base_sha
for i in "${!names[@]}"; do
  name=${names[i]}
  branch=${branch_of[$name]}
  [[ $name == "$from" ]] && started=1
  if ((!started)); then parent=$(git rev-parse "$branch"); continue; fi
  git checkout -q "$branch"
  old=$(git rev-parse HEAD)
  apply_whole "$source_sha" "$manifests/$name"
  if [[ -x $manifests/hooks/$name ]]; then
    run_hook "$manifests" "$name" "$source_sha" "$base_sha" "$parent"
  else
    while IFS= read -r path; do merge_staged "$name" "$path"; done < <(staged_paths "$manifests/$name")
  fi
  git add -A
  if git diff --cached --quiet; then
    echo "$name: no fix"
  else
    msg=$fix_msgs/$name
    [[ -f $msg ]] || msg=$fix_msgs/default
    [[ -f $msg ]] || { echo "missing message $fix_msgs/$name (or $fix_msgs/default)" >&2; exit 1; }
    git -c core.hooksPath=/dev/null commit -q -F "$msg"
    echo "$name: fix $(git rev-parse --short HEAD)"
    [[ $branch != "$top" ]] && rebase_up "$branch" "$old" "$i"
  fi
  parent=$(git rev-parse "$branch")
done
((started)) || { echo "--from $from matches no layer" >&2; exit 2; }

git checkout -q "$top"
if [[ $(git rev-parse "$top^{tree}") == "$(git rev-parse "$source_sha^{tree}")" ]]; then
  echo "top tree equals fixed source"
else
  echo "TOP TREE DIFFERS from fixed source:" >&2
  git diff --stat "$source_sha" "$top" | tail -5 >&2
  exit 1
fi
