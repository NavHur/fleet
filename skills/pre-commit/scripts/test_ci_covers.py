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
"""

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


def job_with_if(condition):
    return (
        "on: pull_request\njobs:\n  build:\n"
        f"    if: {json.dumps(condition)}\n    runs-on: [self-hosted]\n"
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

    def test_types_with_synchronize_cover(self):
        workflow = pull_request("types: [opened, synchronize]\n")
        self.assertEqual(self.covering(workflow, "main"), [("w0.yml", False)])

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

    def test_draft_gated_jobs_are_reported(self):
        workflow = job_with_if(ACCEPTED_GUARDS[3])
        self.assertEqual(self.covering(workflow, "main"), [("w0.yml", True)])

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

    def test_unguarded_job_beside_guarded_job_reports_drafts(self):
        workflow = (
            job_with_if("!github.event.pull_request.draft")
            + "  lint:\n    runs-on: self-hosted\n"
        )
        self.assertEqual(self.covering(workflow, "main"), [("w0.yml", True)])


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

    def test_non_mapping_jobs_is_an_error(self):
        self.assertEqual(self.run_main(self.repo("on: push\njobs: [a]\n"))[0], 2)


if __name__ == "__main__":
    unittest.main()
