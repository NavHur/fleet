#!/usr/bin/env bash
# Build (or rebuild) one branch per layer from the source tip.
#
# Run inside the temporary worktree, never the user's checkout. Layers come
# from MANIFEST_DIR in sorted order (format in lib.sh); each becomes its branch
# (header or PREFIX<name>), committed on the previous layer. Plain paths are
# taken whole from the source and files deleted there are removed. A layer
# with ~paths (in-between versions of a file whose final version is in a later
# layer) needs an executable MANIFEST_DIR/hooks/<name> that writes them; the
# hook may also edit the layer's whole files. A change outside the manifest is
# an error. A layer is one commit, message MSG_DIR/<name> when present, unless
# its manifest has "# commit: SUBJECT" sections: then each section is one
# commit, message MSG_DIR/<name>.<k> (k counts sections from 1) or SUBJECT.
# Commits skip hooks: run the layer gates afterwards (layer_gates.sh).
#
# Usage:
#   build_layers.sh --base REF --source REF --manifests DIR [--prefix PREFIX] [--msgs DIR]
set -euo pipefail

base= source= manifests= prefix= msgs=
while (($#)); do
  case $1 in
    --base) base=$2; shift 2 ;;
    --source) source=$2; shift 2 ;;
    --manifests) manifests=$2; shift 2 ;;
    --prefix) prefix=$2; shift 2 ;;
    --msgs) msgs=$2; shift 2 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n $base && -n $source && -n $manifests ]] || { sed -n '2,17p' "$0" >&2; exit 2; }

commit_with() { # MESSAGE_FILE FALLBACK_SUBJECT
  if [[ -n $msgs && -f $1 ]]; then
    git -c core.hooksPath=/dev/null commit -q -F "$1"
  else
    git -c core.hooksPath=/dev/null commit -q -m "$2"
  fi
}

commit_sections() { # NAME; the layer's changes are staged
  local manifest=$manifests/$1 subject k=0 paths want
  want=$(git write-tree)
  git reset -q
  while IFS= read -r subject; do
    k=$((k + 1))
    paths=$(section_paths "$manifest" "$k")
    [[ -z $paths ]] || GIT_LITERAL_PATHSPECS=1 git add -A --force --pathspec-from-file=- <<<"$paths"
    if git diff --cached --quiet; then
      echo "$1: commit $k ($subject) changes nothing" >&2
      exit 1
    fi
    commit_with "$msgs/$1.$k" "$subject"
  done < <(commit_subjects "$manifest")
  if [[ $(git rev-parse 'HEAD^{tree}') != "$want" ]]; then
    echo "$1: changes outside every commit section:" >&2
    git diff --stat HEAD "$want" >&2
    exit 1
  fi
}

script_dir=$(cd "$(dirname "$0")" && pwd)
. "$script_dir/lib.sh"
manifests=$(cd "$manifests" && pwd)
python3 "$script_dir/check_manifests.py" "$base" "$source" "$manifests" --require-hooks

if [[ -n $(git status --porcelain) ]]; then
  echo "uncommitted or untracked files in $(git rev-parse --show-toplevel); clean the worktree first" >&2
  exit 1
fi
base_sha=$(git rev-parse "$base^{commit}")
source_sha=$(git rev-parse "$source^{commit}")
parent=$base_sha
git checkout -q --detach "$parent"

read_layers "$manifests" "$prefix"
for i in "${!names[@]}"; do
  name=${names[i]} branch=${branches[i]}
  git checkout -q -B "$branch" "$parent"
  apply_whole "$source_sha" "$manifests/$name"
  run_hook "$manifests" "$name" "$source_sha" "$base_sha" "$parent"
  git add -A
  stray=$(comm -23 <(git -c core.quotePath=false diff --cached --name-only --no-renames "$parent" | sort) \
    <({ whole_paths "$manifests/$name"; staged_paths "$manifests/$name"; } | sort -u))
  if [[ -n $stray ]]; then
    echo "$name: changes outside its manifest (hook or stray file):" >&2
    sed 's/^/  /' <<<"$stray" >&2
    exit 1
  fi
  if git diff --cached --quiet "$parent"; then
    echo "$name: the layer changes nothing" >&2
    exit 1
  fi
  if [[ -n $(commit_subjects "$manifests/$name") ]]; then
    commit_sections "$name"
  else
    commit_with "$msgs/$name" "wip: $name"
  fi
  parent=$(git rev-parse HEAD)
  printf '%s %s\n' "$(git rev-parse --short HEAD)" "$branch"
done

if git diff --quiet "$source_sha" HEAD; then
  echo "top tree equals source"
else
  echo "TOP TREE DIFFERS from source:" >&2
  git diff --stat "$source_sha" HEAD | tail -5 >&2
  exit 1
fi
