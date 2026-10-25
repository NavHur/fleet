import contextlib
import io
import json
import pathlib
import shutil
import tempfile
import textwrap
import unittest

import ci_covers

SELF_HOSTED_JOB = """
jobs:
  lint:
    runs-on: [self-hosted, lightsail]
    steps:
      - run: pnpm test
"""
TEST_STEP = "  steps: [{run: pnpm test}]\n"
LINT_STEP = "  steps: [{run: pnpm lint}]\n"
TEST_COMMANDS = [
    "pnpm test",
    "pnpm turbo run test --filter=@nj-homes/web -- --shard=1",
    "pnpm --filter @dca/chatdca test",
    "python -m pytest -q -n 4",
    ".venv/bin/pytest -q",
    "pnpm review:coverage --base x",
    "npx vitest run",
]
OTHER_COMMANDS = [
    "pnpm test:lint",
    "pnpm lint",
    "pnpm typecheck",
    "uvx ruff check src tests",
    "echo latest",
]

ACCEPTED_GUARDS = [
    "!github.event.pull_request.draft",
    "${{ !github.event.pull_request.draft }}",
    "github.event.pull_request.draft == false",
    "github.event_name != 'pull_request' || !github.event.pull_request.draft",
    'github.event_name != "pull_request" || github.event.pull_request.draft == false',
]
REJECTED_GUARDS = [
    "github.event_name == 'push'",
    "github.event.pull_request.draft",
    "github.event.pull_request.draft == false && github.actor != 'bot'",
    "true",
]


def pull_request(filters=""):
    """A workflow with a self-hosted job and these pull_request filters."""
    return "on:\n  pull_request:\n" + textwrap.indent(filters, "    ") + SELF_HOSTED_JOB


ON_PR = "on: pull_request\n"
ON_READY = "on:\n  pull_request:\n    types: [opened, synchronize, ready_for_review]\n"


def with_jobs(on, body):
    return on + "jobs:\n" + textwrap.indent(textwrap.dedent(body), "  ")


def job_with_if(condition, on=ON_READY):
    return (
        f"{on}jobs:\n  build:\n"
        f"    if: {json.dumps(condition)}\n    runs-on: [self-hosted]\n"
        + "  "
        + TEST_STEP
    )


class RepoTestCase(unittest.TestCase):
    def repo(self, *workflows):
        root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        (root / ".github" / "workflows").mkdir(parents=True)
        for i, text in enumerate(workflows):
            path = root / ".github" / "workflows" / f"w{i}.yml"
            path.write_text(textwrap.dedent(text))
        return root

    def covering(self, workflow, base):
        return ci_covers.covering(self.repo(workflow), base)


class CoveringTest(RepoTestCase):
    def test_unfiltered_pull_request_covers_any_base(self):
        self.assertEqual(
            self.covering(pull_request(), "feature/layer-1"), [("w0.yml", False)]
        )

    def test_branch_filter_excludes_stack_layers(self):
        workflow = pull_request("branches: [main, nightly]\n")
        self.assertEqual(self.covering(workflow, "nightly"), [("w0.yml", False)])
        self.assertEqual(self.covering(workflow, "feature/layer-1"), [])

    def test_branches_ignore(self):
        workflow = pull_request("branches-ignore: ['release/**']\n")
        self.assertEqual(self.covering(workflow, "release/2026-10"), [])
        self.assertEqual(self.covering(workflow, "main"), [("w0.yml", False)])

    def test_single_star_does_not_cross_slashes(self):
        workflow = pull_request("branches: ['*']\n")
        self.assertEqual(self.covering(workflow, "main"), [("w0.yml", False)])
        self.assertEqual(self.covering(workflow, "pedro/layer-1"), [])

    def test_double_star_crosses_slashes(self):
        workflow = pull_request("branches: ['**']\n")
        self.assertEqual(self.covering(workflow, "pedro/layer-1"), [("w0.yml", False)])

    def test_negated_pattern_excludes_later(self):
        workflow = pull_request("branches: ['**', '!release/**']\n")
        self.assertEqual(self.covering(workflow, "release/1"), [])
        self.assertEqual(self.covering(workflow, "main"), [("w0.yml", False)])

    def test_later_positive_pattern_readmits(self):
        workflow = pull_request("branches: ['!release/**', 'release/**']\n")
        self.assertEqual(self.covering(workflow, "release/1"), [("w0.yml", False)])
        self.assertEqual(self.covering(workflow, "main"), [])

    def test_branches_ignore_single_star_admits_nested(self):
        workflow = pull_request("branches-ignore: ['release/*']\n")
        self.assertEqual(self.covering(workflow, "release/a"), [])
        self.assertEqual(self.covering(workflow, "release/a/b"), [("w0.yml", False)])

    def test_question_mark_and_plus_quantify_previous_char(self):
        workflow = pull_request("branches: ['v1?', 'rc+']\n")
        for base in ["v", "v1", "rc", "rcc"]:
            with self.subTest(base=base):
                self.assertEqual(self.covering(workflow, base), [("w0.yml", False)])
        self.assertEqual(self.covering(workflow, "v11"), [])

    def test_character_class(self):
        workflow = pull_request("branches: ['v[0-9]']\n")
        self.assertEqual(self.covering(workflow, "v3"), [("w0.yml", False)])
        self.assertEqual(self.covering(workflow, "vx"), [])

    def test_path_filters_do_not_cover(self):
        for filters in ["paths: ['src/**']\n", "paths-ignore: ['docs/**']\n"]:
            with self.subTest(filters=filters):
                self.assertEqual(self.covering(pull_request(filters), "main"), [])

    def test_types_without_synchronize_do_not_cover(self):
        workflow = pull_request("types: [opened, reopened]\n")
        self.assertEqual(self.covering(workflow, "main"), [])

    def test_types_with_opened_and_synchronize_cover(self):
        workflow = pull_request("types: [opened, synchronize]\n")
        self.assertEqual(self.covering(workflow, "main"), [("w0.yml", False)])

    def test_types_without_opened_do_not_cover(self):
        workflow = pull_request("types: [synchronize]\n")
        self.assertEqual(self.covering(workflow, "main"), [])

    def test_github_hosted_jobs_do_not_count(self):
        workflow = (
            "on: [push, pull_request]\njobs:\n  lint:\n    runs-on: ubuntu-latest\n"
        )
        self.assertEqual(self.covering(workflow, "main"), [])

    def test_expression_runs_on_does_not_count(self):
        workflow = (
            "on: pull_request\njobs:\n  lint:\n    runs-on: ${{ matrix.runner }}\n"
        )
        self.assertEqual(self.covering(workflow, "main"), [])

    def test_push_only_workflow_does_not_count(self):
        self.assertEqual(self.covering("on:\n  push:\n" + SELF_HOSTED_JOB, "main"), [])

    def test_runner_group_needs_a_self_hosted_label(self):
        cases = {
            "{group: runners, labels: [self-hosted, lightsail]}": [("w0.yml", False)],
            "{group: runners}": [],
        }
        for runs_on, expected in cases.items():
            with self.subTest(runs_on=runs_on):
                body = f"lint:\n  runs-on: {runs_on}\n" + TEST_STEP
                workflow = with_jobs(ON_PR, body)
                self.assertEqual(self.covering(workflow, "main"), expected)

    def test_needs_must_all_count(self):
        gate = "gate:\n  runs-on: self-hosted\n"
        push_gate = "gate:\n  if: github.event_name == 'push'\n  runs-on: self-hosted\n"
        dependent = "t:\n  needs: gate\n  runs-on: self-hosted\n" + TEST_STEP
        cases = {
            "counted": (gate + dependent, True),
            "list": (gate + dependent.replace("gate", "[gate]"), True),
            "push-only": (push_gate + dependent, False),
            "unknown": (dependent.replace("gate", "nope"), False),
            "hosted": (
                "gate:\n  runs-on: ubuntu-latest\n" + dependent,
                False,
            ),
            "cycle": (
                "a:\n  needs: b\n  runs-on: self-hosted\n"
                + "b:\n  needs: a\n  runs-on: self-hosted\n",
                False,
            ),
        }
        for name, (body, counts) in cases.items():
            with self.subTest(name=name):
                workflow = with_jobs(ON_PR, body)
                expected = [("w0.yml", False)] if counts else []
                self.assertEqual(self.covering(workflow, "main"), expected)

    def test_job_inherits_draft_guard_from_needs(self):
        guard = "gate:\n  if: '!github.event.pull_request.draft'\n"
        body = (
            guard
            + "  runs-on: self-hosted\nt:\n  needs: gate\n  runs-on: self-hosted\n"
            + TEST_STEP
        )
        self.assertEqual(
            self.covering(with_jobs(ON_READY, body), "main"), [("w0.yml", True)]
        )
        self.assertEqual(self.covering(with_jobs(ON_PR, body), "main"), [])

    def test_guarded_jobs_need_ready_for_review(self):
        guard = ACCEPTED_GUARDS[0]
        unguarded = "  lint:\n    runs-on: self-hosted\n  " + TEST_STEP
        self.assertEqual(self.covering(job_with_if(guard, ON_PR), "main"), [])
        self.assertEqual(
            self.covering(job_with_if(guard, ON_PR) + unguarded, "main"),
            [("w0.yml", False)],
        )
        self.assertEqual(self.covering(job_with_if(guard), "main"), [("w0.yml", True)])

    def test_accepted_guards_count_and_report_drafts(self):
        for guard in ACCEPTED_GUARDS:
            with self.subTest(guard=guard):
                self.assertEqual(
                    self.covering(job_with_if(guard), "main"), [("w0.yml", True)]
                )

    def test_other_conditions_do_not_count(self):
        for guard in REJECTED_GUARDS:
            with self.subTest(guard=guard):
                self.assertEqual(self.covering(job_with_if(guard), "main"), [])

    def test_unguarded_lint_beside_guarded_tests_reports_drafts(self):
        workflow = (
            job_with_if("!github.event.pull_request.draft")
            + "  lint:\n    runs-on: self-hosted\n  "
            + LINT_STEP
        )
        self.assertEqual(self.covering(workflow, "main"), [("w0.yml", True)])

    def test_test_command_patterns(self):
        for command in TEST_COMMANDS + OTHER_COMMANDS:
            with self.subTest(command=command):
                step = f"  steps:\n    - run: {json.dumps(command)}\n"
                workflow = with_jobs(ON_PR, "t:\n  runs-on: self-hosted\n" + step)
                expected = [("w0.yml", False)] if command in TEST_COMMANDS else []
                self.assertEqual(self.covering(workflow, "main"), expected)

    def test_lint_only_workflow_does_not_cover(self):
        body = "lint:\n  runs-on: self-hosted\n" + LINT_STEP
        self.assertEqual(self.covering(with_jobs(ON_PR, body), "main"), [])

    def test_tests_on_hosted_runner_beside_self_hosted_lint_do_not_cover(self):
        body = (
            "lint:\n  runs-on: self-hosted\n"
            + LINT_STEP
            + "test:\n  runs-on: ubuntu-latest\n"
            + TEST_STEP
        )
        self.assertEqual(self.covering(with_jobs(ON_PR, body), "main"), [])

    def test_jobs_without_run_steps_do_not_cover(self):
        steps = ["", "  steps: [{uses: actions/checkout@v4}]\n", "  steps: [5]\n"]
        for step in steps:
            with self.subTest(step=step):
                body = "t:\n  runs-on: self-hosted\n" + step
                self.assertEqual(self.covering(with_jobs(ON_PR, body), "main"), [])


class MainTest(RepoTestCase):
    def run_main(self, root):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = ci_covers.main(["--base", "x", "--root", str(root)])
        return code, stderr.getvalue()

    def test_exit_codes_covered_and_not(self):
        self.assertEqual(self.run_main(self.repo(pull_request()))[0], 0)
        self.assertEqual(self.run_main(self.repo())[0], 1)

    def test_malformed_yaml_is_an_error(self):
        code, stderr = self.run_main(self.repo("on: [pull_request\njobs: {"))
        self.assertEqual(code, 2)
        self.assertIn("w0.yml", stderr)

    def test_null_job_is_an_error(self):
        code, stderr = self.run_main(self.repo("on: pull_request\njobs:\n  t: null\n"))
        self.assertEqual(code, 2)
        self.assertIn("job t must be a mapping", stderr)

    def test_non_mapping_workflow_is_an_error(self):
        self.assertEqual(self.run_main(self.repo("- a\n- b\n"))[0], 2)

    def test_malformed_trigger_values_are_errors(self):
        workflows = [
            pull_request("branches: 5\n"),
            pull_request("types: 5\n"),
            "on:\n  pull_request: [x]\n" + SELF_HOSTED_JOB,
        ]
        for workflow in workflows:
            with self.subTest(workflow=workflow):
                self.assertEqual(self.run_main(self.repo(workflow))[0], 2)

    def test_non_list_steps_is_an_error(self):
        body = "t:\n  runs-on: self-hosted\n  steps: 5\n"
        code, stderr = self.run_main(self.repo(with_jobs(ON_PR, body)))
        self.assertEqual(code, 2)
        self.assertIn("job t steps must be a list", stderr)

    def test_non_mapping_jobs_is_an_error(self):
        self.assertEqual(self.run_main(self.repo("on: push\njobs: [a]\n"))[0], 2)


if __name__ == "__main__":
    unittest.main()
