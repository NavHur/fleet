#!/usr/bin/env bash
# Write each layer's delta between two review rounds.
#
#   delta.sh --prev PREV_HEADS.tsv --heads HEADS.tsv --out DIR [--manifests DIR] [--repo DIR]
#
# A heads file has one line per PR, bottom to top: PR<TAB>LAYER<TAB>BASE_SHA<TAB>HEAD_SHA.
# With --manifests (split-stacked-prs layout) a layer's delta is restricted to the
# files its manifest owns, so fixes carried up from lower layers stay out of it;
# without, the delta is the whole PREV_HEAD..HEAD diff. A rebase shows up as the
# base's changes merged into those files, which is what a hand-resolved conflict
# looks like. Writes DIR/delta-<PR>.diff for every non-empty delta and prints
# PR, layer, changed size (bytes of added and deleted lines, as diff_budget.py
# counts them) and whether files pedro-best-practices audits changed
# (JS/TS, Svelte, Vue, Astro, GDScript, Python, PHP).
set -euo pipefail
prev= heads= out= manifests= repo=.
while (($#)); do
  case $1 in
    --prev) prev=$2; shift 2 ;;
    --heads) heads=$2; shift 2 ;;
    --out) out=$2; shift 2 ;;
    --manifests) manifests=$2; shift 2 ;;
    --repo) repo=$2; shift 2 ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n $prev && -n $heads && -n $out ]] || { sed -n '4p' "$0" >&2; exit 2; }
mkdir -p "$out"
cd "$repo"
while IFS=$'\t' read -r pr layer _base head; do
  [[ -z $pr || $pr == \#* ]] && continue
  old=$(awk -F'\t' -v pr="$pr" '$1 == pr { print $4 }' "$prev")
  if [[ -z $old ]]; then
    echo "$pr $layer: new in this round, review it whole"
    continue
  fi
  paths=()
  if [[ -n $manifests ]]; then
    [[ -f $manifests/$layer ]] || { echo "$pr $layer: no manifest $manifests/$layer" >&2; exit 2; }
    mapfile -t paths < <(sed -e 's/^~//' -e '/^#/d' -e '/^[[:space:]]*$/d' "$manifests/$layer")
  fi
  file=$out/delta-$pr.diff
  git diff "$old" "$head" -- "${paths[@]}" >"$file"
  if [[ ! -s $file ]]; then
    rm -f "$file"
    echo "$pr $layer: no delta"
    continue
  fi
  size=$(git diff -U0 --find-renames --find-copies --no-ext-diff --no-textconv --no-color "$old" "$head" -- "${paths[@]}" | LC_ALL=C awk '
    /^diff --git / { hunk = 0; next }
    /^@@ / { hunk = 1; next }
    hunk && /^[-+]/ { n += length($0) }
    END { printf "%.1f KB", n / 1000 }')
  audit=no
  git diff --name-only "$old" "$head" -- "${paths[@]}" |
    grep -qE '\.([cm]?[jt]sx?|svelte|vue|astro|gd|py|php)$' && audit=yes
  echo "$pr $layer: $size, audit=$audit -> $file"
done <"$heads"
