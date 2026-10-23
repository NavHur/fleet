import pathlib
import tempfile
import textwrap
import unittest

import ci_covers


def repo(*workflows):
    root = pathlib.Path(tempfile.mkdtemp())
    (root / ".github" / "workflows").mkdir(parents=True)
    for i, text in enumerate(workflows):
        (root / ".github" / "workflows" / f"w{i}.yml").write_text(textwrap.dedent(text))
    return root


SELF_HOSTED_JOB = """
jobs:
  lint:
    runs-on: [self-hosted, lightsail]
"""


class CoveringTest(unittest.TestCase):
    def test_unfiltered_pull_request_covers_any_base(self):
        root = repo("on:\n  pull_request:\n" + SELF_HOSTED_JOB)
        self.assertEqual(
            ci_covers.covering(root, "feature/layer-1"), [("w0.yml", False)]
        )

    def test_branch_filter_excludes_stack_layers(self):
        root = repo(
            "on:\n  pull_request:\n    branches: [main, nightly]\n" + SELF_HOSTED_JOB
        )
        self.assertEqual(ci_covers.covering(root, "nightly"), [("w0.yml", False)])
        self.assertEqual(ci_covers.covering(root, "feature/layer-1"), [])

    def test_branches_ignore(self):
        root = repo(
            "on:\n  pull_request:\n    branches-ignore: ['release/**']\n"
            + SELF_HOSTED_JOB
        )
        self.assertEqual(ci_covers.covering(root, "release/2026-10"), [])
        self.assertEqual(ci_covers.covering(root, "main"), [("w0.yml", False)])

    def test_github_hosted_jobs_do_not_count(self):
        root = repo(
            "on: [push, pull_request]\njobs:\n  lint:\n    runs-on: ubuntu-latest\n"
        )
        self.assertEqual(ci_covers.covering(root, "main"), [])

    def test_push_only_workflow_does_not_count(self):
        root = repo("on:\n  push:\n" + SELF_HOSTED_JOB)
        self.assertEqual(ci_covers.covering(root, "main"), [])

    def test_draft_gated_jobs_are_reported(self):
        root = repo(
            """
            on: pull_request
            jobs:
              build:
                if: github.event_name != 'pull_request' || !github.event.pull_request.draft
                runs-on:
                  labels: [self-hosted]
            """
        )
        self.assertEqual(ci_covers.covering(root, "main"), [("w0.yml", True)])

    def test_main_exit_codes(self):
        root = repo("on:\n  pull_request:\n" + SELF_HOSTED_JOB)
        self.assertEqual(ci_covers.main(["--base", "x", "--root", str(root)]), 0)
        self.assertEqual(ci_covers.main(["--base", "x", "--root", str(repo())]), 1)


if __name__ == "__main__":
    unittest.main()
