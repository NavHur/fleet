# PR and stack size (Pedro's personal rule)

Size is measured in bytes: the bytes of every added and deleted line, about
four bytes per token, the unit of the 20,000-byte file cap. A line count
misjudges review work, because lines run from about 20 to 90 bytes and one
minified or prose line can hold thousands. 1 KB here is 1,000 bytes.

Every pull request Pedro authors, stacked or not, stays within two ceilings
against its direct base branch:

- **Weighted size** is non-test added bytes plus one quarter of non-test
  deleted bytes, at most **48 KB** (about 12k tokens). Test files are excluded
  from this ceiling only.
- **Raw churn** is added plus deleted bytes, including test files, at most
  **96 KB**. Report test churn separately.

A pull request is made of commits, and a stack of layers:

- A **commit** is one step a reviewer can follow alone: a move or rename, an
  extracted helper, a new type, a behavior change with its tests, the wiring.
  Refactors and behavior changes go in separate commits, and each commit
  typechecks. Against its parent, a commit stays within **12 KB** weighted and
  **24 KB** raw, measured like a pull request, so a pull request holds four
  full commits. A commit that cannot be split, such as one cohesive new
  module or a mechanical edit across many files, carries a
  `Size-Exception: <reason>` trailer.
- A **layer** is one purpose a reviewer approves in one sitting, built from
  several commits, and a pull request of its own under the same ceilings. A
  layer under **12 KB** weighted, one full commit, needs a reason (a
  migration that ships first, rollout order, a retirement, a risky change
  that should revert alone); otherwise merge it into its neighbour.

Test files are unit, component, integration, E2E, and accessibility tests:
JS/TS `*.test.*` and `*.spec.*`, Python `test_*.py` and `*_test.py`, Go
`*_test.go`; pass other verified test files with `--test GLOB`. Handwritten
fixtures, test helpers, setup, and test infrastructure count toward both
ceilings, so never exempt a whole test directory. Keep tests in the layer whose
behavior they verify. Lockfiles and verified generated or vendored data
(committed data JSON, Prisma migrations, captured `.geojson`) are exempt from
both; confirm the evidence before adding another exclusion. Measure from the
repository root before pushing:

```sh
python3 ~/.agents/skills/split-stacked-prs/scripts/diff_budget.py \
  <base> HEAD \
  --generated 'data/*.json' --generated '*/data/*.json' \
  --generated 'prisma/municipalities.json' --generated '*/prisma/municipalities.json' \
  --generated 'prisma/migrations/*' --generated '*/prisma/migrations/*' \
  --generated '*.geojson'
```

Add `--per-commit` to the same command to measure each commit in the range
against its parent under the commit ceilings.

- A layer or commit that only deletes files, or only renames them without
  content changes, is exempt from its ceilings. Group those retirements so
  each layer still typechecks, importer before import.
- A stack holds 2 to 4 layers, at most **5**. Work within the pull request
  ceilings ships as one pull request of small commits. Larger work becomes
  several independent stacks, each branched from the integration branch and
  merged in waves: one stack merges, the rest rebase onto the new tip.
- Split on whole files, never inside one, so every layer typechecks on its own.
  The seam that usually works: domain module and its tests, then the component
  with its tests and accessibility suite, then the wiring and any retirement.
- This rule is personal. Apply it only to Pedro's pull requests, and keep it out
  of repositories: no CI job, repo docs, `.gitattributes` entries, or package
  scripts.

