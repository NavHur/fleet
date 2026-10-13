# PR and stack size (Pedro's personal rule)

Every pull request Pedro authors, stacked or not, stays within two ceilings
against its direct base branch:

- **Weighted size** is non-test additions plus one quarter of non-test
  deletions, at most **1000**. Test files are excluded from this ceiling only.
- **Raw churn** is additions plus deletions, including test files, at most
  **2000**. Report test churn separately.

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

- A layer that only deletes files, or only renames them without content
  changes, is exempt from both ceilings. Group those retirements so each layer
  still typechecks, importer before import.
- A stack holds at most **5 layers**. Larger work becomes several independent
  stacks, each branched from the integration branch and merged in waves: one
  stack merges, the rest rebase onto the new tip.
- Split on whole files, never inside one, so every layer typechecks on its own.
  The seam that usually works: domain module and its tests, then the component
  with its tests and accessibility suite, then the wiring and any retirement.
- This rule is personal. Apply it only to Pedro's pull requests, and keep it out
  of repositories: no CI job, repo docs, `.gitattributes` entries, or package
  scripts.

