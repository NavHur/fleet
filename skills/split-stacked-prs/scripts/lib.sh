# Shared by build_layers.sh, fix_layers.sh and layer_gates.sh; source it.
#
# A manifest directory holds one file per layer; sorting the names gives the
# stack order (01-contract, 02-domain, ...). Hidden files and the hooks/
# directory are not layers. A manifest has, one per line:
#   # branch: NAME   optional header; without it the branch is PREFIX<file name>
#   # base: REF      optional, first manifest only: the stack's base
#   # pr: N          optional, the layer's pull request number
#   path             whole file: the layer takes the source version (or deletes it)
#   ~path            staged: an in-between version; the final version is in a
#                    later layer. hooks/<name> writes it (build and fix); without
#                    a hook fix_layers.sh 3-way merges the fix into it.
# Other lines starting with # and blank lines are ignored.
#
# An executable MANIFEST_DIR/hooks/<name> runs in the worktree root after the
# whole files are copied, with LAYER, SOURCE (source commit), BASE, PARENT,
# MANIFESTS and STAGED (newline-separated ~paths) in the environment. It must
# write each staged path's full content from $SOURCE (git show "$SOURCE:path"
# plus edits), not patch the current file, so reruns give the same result.

layer_names() { # DIR; a glob skips dotfiles, and BSD find has no -printf
  local path
  for path in "$1"/*; do
    if [[ -f $path ]]; then printf '%s\n' "${path##*/}"; fi
  done | LC_ALL=C sort
}

manifest_header() { # DIR NAME KEY
  sed -n "s/^#[[:space:]]*$3:[[:space:]]*//p" "$1/$2" | head -1
}

layer_branch() { # DIR NAME PREFIX
  local branch
  branch=$(manifest_header "$1" "$2" branch)
  printf '%s\n' "${branch:-$3$2}"
}

stack_base() { # DIR [EXPLICIT]; the --base argument wins over the header
  local first
  if [[ -n ${2:-} ]]; then printf '%s\n' "$2"; return; fi
  first=$(layer_names "$1" | head -1)
  manifest_header "$1" "$first" base
}

whole_paths() { # MANIFEST_FILE
  sed -e 's/[[:space:]]*$//' "$1" | grep -v -e '^[[:space:]]*#' -e '^[[:space:]]*$' -e '^~' || true
}

staged_paths() { # MANIFEST_FILE
  sed -n -e 's/[[:space:]]*$//' -e 's/^~//p' "$1"
}

apply_whole() { # SOURCE_SHA MANIFEST_FILE: copy whole files from the source, delete removed ones
  local path
  while IFS= read -r path; do
    if git cat-file -e "$1:$path" 2>/dev/null; then
      git checkout -q "$1" -- "$path"
    else
      git rm -q --ignore-unmatch -- "$path"
    fi
  done < <(whole_paths "$2")
}

run_hook() { # DIR NAME SOURCE BASE PARENT; no-op without an executable hook
  local hook=$1/hooks/$2
  [[ -x $hook ]] || return 0
  LAYER=$2 SOURCE=$3 BASE=$4 PARENT=$5 MANIFESTS=$1 STAGED=$(staged_paths "$1/$2") "$hook"
}

branches_checked_out_elsewhere() { # BRANCH...; prints "branch worktree" for each
  local here wt line want
  here=$(git rev-parse --show-toplevel)
  declare -A want_set=()
  for want in "$@"; do want_set[refs/heads/$want]=1; done
  while IFS= read -r line; do
    case $line in
      "worktree "*) wt=${line#worktree } ;;
      "branch "*)
        if [[ -n ${want_set[${line#branch }]:-} && $wt != "$here" ]]; then
          printf '%s %s\n' "${line#branch refs/heads/}" "$wt"
        fi ;;
    esac
  done < <(git worktree list --porcelain)
}
