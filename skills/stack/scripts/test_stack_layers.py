"""The stack's layers, read from manifests or a branch list, over a temporary repository."""

import os
from pathlib import Path
import stat
import subprocess
import sys
import unittest

from stack_fixture import StackRepo
from stack_layers import GitHub, PullRequest, Stack, StackError, read_manifest


class FakeGitHub:
    """Open PRs by branch; `pr` answers only for numbers it knows."""

    def __init__(self, open_prs, pulls=None):
        self.open_prs, self.pulls, self.slug = open_prs, pulls or {}, "o/r"

    def open_pr(self, branch):
        return self.open_prs.get(branch)

    def pr(self, number):
        return self.pulls[number]


class ManifestListingTests(unittest.TestCase):
    def setUp(self):
        self.repo = StackRepo(self)

    def test_layers_come_in_manifest_order_with_prefixed_branches(self):
        self.repo.manifest("02-domain", "b.ts\n")
        self.repo.manifest("01-contract", "# base: main\na.ts\n")
        self.repo.manifest(".hidden", "x\n")
        stack = Stack.from_manifests(self.repo.manifests, "s-", git_refs=False)
        self.assertEqual(stack.base, "main")
        self.assertEqual([(l.name, l.branch, l.parent) for l in stack.layers],
                         [("01-contract", "s-01-contract", "main"), ("02-domain", "s-02-domain", "s-01-contract")])

    def test_branch_header_wins_over_the_prefix(self):
        self.repo.manifest("01-contract", "# branch: feat/contract\n# base: main\na.ts\n")
        stack = Stack.from_manifests(self.repo.manifests, "s-", git_refs=False)
        self.assertEqual(stack.layers[0].branch, "feat/contract")

    def test_explicit_base_wins_over_the_header(self):
        self.repo.manifest("01-contract", "# base: main\na.ts\n")
        stack = Stack.from_manifests(self.repo.manifests, "s-", base="nightly", git_refs=False)
        self.assertEqual(stack.base, "nightly")
        self.assertEqual(stack.layers[0].parent, "nightly")

    def test_paths_are_whole_and_staged_paths_without_the_tilde(self):
        self.repo.manifest("01-contract", "# base: main\n# commit: first\na.ts  \n~b.ts\n\n# note\nc.ts\n")
        manifest = read_manifest(self.repo.manifests / "01-contract")
        self.assertEqual(manifest.paths, ("a.ts", "b.ts", "c.ts"))
        self.assertEqual((manifest.whole, manifest.staged), (("a.ts", "c.ts"), {"b.ts"}))

    def test_a_layer_without_branch_header_or_prefix_is_refused(self):
        self.repo.manifest("01-contract", "# base: main\na.ts\n")
        with self.assertRaisesRegex(StackError, "01-contract: no '# branch:' header and no --prefix"):
            Stack.from_manifests(self.repo.manifests, "", git_refs=False)

    def test_no_base_is_refused(self):
        self.repo.manifest("01-contract", "a.ts\n")
        with self.assertRaisesRegex(StackError, "no --base"):
            Stack.from_manifests(self.repo.manifests, "s-", git_refs=False)

    def test_an_empty_or_missing_manifest_directory_is_refused(self):
        with self.assertRaisesRegex(StackError, "no manifests"):
            Stack.from_manifests(self.repo.manifests, "s-", git_refs=False)
        with self.assertRaisesRegex(StackError, "no manifests"):
            Stack.from_manifests(self.repo.manifests / "missing", "s-", git_refs=False)


class GitRefTests(unittest.TestCase):
    def setUp(self):
        self.repo = StackRepo(self)
        self.main = self.repo.git("rev-parse", "main")
        self.lower = self.repo.branch("s-01-contract", "main", {"a.ts": "a\n"})
        self.upper = self.repo.branch("s-02-domain", "s-01-contract", {"b.ts": "b\n"})
        self.repo.manifest("01-contract", "# base: main\na.ts\n")
        self.repo.manifest("02-domain", "b.ts\n")

    def test_each_layer_forks_from_its_parent(self):
        stack = Stack.from_manifests(self.repo.manifests, "s-")
        self.assertEqual([(l.fork, l.head) for l in stack.layers],
                         [(self.main, self.lower), (self.lower, self.upper)])

    def test_a_fix_on_the_lower_layer_leaves_the_upper_fork_at_the_old_tip(self):
        self.repo.git("checkout", "-q", "s-01-contract")
        fixed = self.repo.commit({"a.ts": "a fixed\n"}, "fix")
        self.repo.git("checkout", "-q", "main")
        lower, upper = Stack.from_manifests(self.repo.manifests, "s-").layers
        self.assertEqual(lower.head, fixed)
        self.assertEqual(upper.fork, self.lower)

    def test_a_branch_list_is_a_stack_named_by_its_branches(self):
        stack = Stack.from_branches("main", ["s-01-contract", "s-02-domain"])
        self.assertEqual([(l.name, l.parent, l.fork, l.head) for l in stack.layers],
                         [("s-01-contract", "main", self.main, self.lower),
                          ("s-02-domain", "s-01-contract", self.lower, self.upper)])

    def test_a_remote_reads_heads_from_its_tracking_refs(self):
        self.repo.git("update-ref", "refs/remotes/origin/s-01-contract", self.main)
        self.repo.git("update-ref", "refs/remotes/origin/s-02-domain", self.lower)
        stack = Stack.from_branches("main", ["s-01-contract", "s-02-domain"], remote="origin")
        self.assertEqual([(l.branch, l.head) for l in stack.layers],
                         [("s-01-contract", self.main), ("s-02-domain", self.lower)])

    def test_a_branch_that_does_not_resolve_is_refused(self):
        with self.assertRaisesRegex(StackError, r"rev-parse --verify s-03-missing\^{commit}: fatal: "):
            Stack.from_branches("main", ["s-01-contract", "s-03-missing"])


class PullRequestTests(unittest.TestCase):
    def setUp(self):
        self.repo = StackRepo(self)
        self.repo.manifest("01-contract", "# base: main\n# pr: 7\na.ts\n")
        self.repo.manifest("02-domain", "b.ts\n")
        self.repo.manifest("03-ui", "c.ts\n")

    def test_the_header_wins_and_the_open_pr_fills_the_rest(self):
        github = FakeGitHub({"s-01-contract": 99, "s-02-domain": 8})
        stack = Stack.from_manifests(self.repo.manifests, "s-", git_refs=False, github=github)
        self.assertEqual([l.pr for l in stack.layers], [7, 8, None])

    def test_without_github_only_headers_give_numbers(self):
        stack = Stack.from_manifests(self.repo.manifests, "s-", git_refs=False)
        self.assertEqual([l.pr for l in stack.layers], [7, None, None])


FAKE_GH = """#!/bin/sh
printf '%s\\n' "$*" >>"$GH_LOG"
case "$*" in
  *"pulls?head=o:"*"feat/boom"*) echo "HTTP 500" >&2; exit 1 ;;
  *"pulls?head=o:"*"feat/x"*) echo 12 ;;
  *"pulls?head="*) ;;
  *pulls/12*) echo '{"head": {"sha": "abc"}, "base": {"ref": "nightly"}}' ;;
  *) echo "unexpected: $*" >&2; exit 1 ;;
esac
"""


def fake_gh(test, repo):
    """Put FAKE_GH first on PATH for the test; returns the file it logs its arguments to."""
    bin_dir = Path(repo.root).parent / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    log = bin_dir / "gh.log"
    for key, value in {"PATH": f"{bin_dir}:{os.environ['PATH']}", "GH_LOG": str(log)}.items():
        test.addCleanup(os.environ.__setitem__, key, os.environ.get(key, ""))
        os.environ[key] = value
    return log


class RestAdapterTests(unittest.TestCase):
    def setUp(self):
        self.repo = StackRepo(self)
        self.log = fake_gh(self, self.repo)

    def test_lookups_go_over_rest(self):
        github = GitHub("o/r")
        self.assertEqual(github.open_pr("feat/x"), 12)
        self.assertIsNone(github.open_pr("feat/none"))
        self.assertEqual(github.pr(12), PullRequest(head="abc", base_ref="nightly"))
        calls = self.log.read_text().splitlines()
        self.assertTrue(all(call.startswith("api repos/o/r/pulls") for call in calls), calls)

    def test_a_failed_call_is_an_error_not_a_missing_pr(self):
        with self.assertRaisesRegex(StackError, "unexpected"):
            GitHub("o/r").pr(13)

    def test_the_slug_comes_from_a_github_origin(self):
        self.repo.git("remote", "add", "origin", "https://github.com/o/r")
        for url in ("git@github.com:o/r.git", "https://github.com/o/r", "ssh://git@github.com/o/r.git"):
            self.repo.git("remote", "set-url", "origin", url)
            self.assertEqual(GitHub.from_origin().slug, "o/r")

    def test_the_slug_comes_from_another_checkouts_origin(self):
        self.repo.git("remote", "add", "origin", "git@github.com:o/r.git")
        os.chdir(self.repo.root.parent)
        self.assertEqual(GitHub.from_origin(root=self.repo.root).slug, "o/r")

    def test_a_non_github_origin_is_refused(self):
        self.repo.git("remote", "add", "origin", "https://gitlab.com/o/r.git")
        with self.assertRaisesRegex(StackError, "not a GitHub repository"):
            GitHub.from_origin()


def cli(*args):
    return subprocess.run([sys.executable, str(Path(__file__).with_name("stack_layers.py")), *args],
                          capture_output=True, text=True)


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.repo = StackRepo(self)
        self.main = self.repo.git("rev-parse", "main")
        self.lower = self.repo.branch("s-01-contract", "main", {"a.ts": "a\n"})
        self.upper = self.repo.branch("s-02-domain", "s-01-contract", {"b.ts": "b\n"})
        self.repo.manifest("01-contract", "# base: main\n# pr: 7\na.ts\n")
        self.repo.manifest("02-domain", "b.ts\n")
        self.manifests = str(self.repo.manifests)

    def test_layers_lists_names_and_branches(self):
        result = cli("layers", "--manifests", self.manifests, "--prefix", "s-")
        self.assertEqual(result.stdout, "01-contract\ts-01-contract\n02-domain\ts-02-domain\n")

    def test_layers_needs_no_base(self):
        self.repo.manifest("01-contract", "a.ts\n")
        result = cli("layers", "--manifests", self.manifests, "--prefix", "s-")
        self.assertEqual(result.stdout.splitlines()[0], "01-contract\ts-01-contract")

    def test_base_prefers_the_argument(self):
        self.assertEqual(cli("base", "--manifests", self.manifests).stdout, "main\n")
        self.assertEqual(cli("base", "--manifests", self.manifests, "--base", "dev").stdout, "dev\n")

    def test_base_prints_nothing_and_exits_0_without_one(self):
        self.repo.manifest("01-contract", "a.ts\n")
        result = cli("base", "--manifests", self.manifests)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_base_on_a_missing_manifest_directory_exits_1(self):
        result = cli("base", "--manifests", self.manifests + "/missing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no manifests in", result.stderr)

    def test_heads_writes_one_line_per_layer_with_its_fork_point(self):
        result = cli("heads", "--manifests", self.manifests, "--prefix", "s-")
        self.assertEqual(result.stdout, f"7\t01-contract\t{self.main}\t{self.lower}\n"
                                        f"s-02-domain\t02-domain\t{self.lower}\t{self.upper}\n")
        self.assertIn("no GitHub origin", result.stderr)

    def test_heads_takes_a_branch_list(self):
        result = cli("heads", "--base", "main", "s-01-contract")
        self.assertEqual(result.stdout, f"s-01-contract\ts-01-contract\t{self.main}\t{self.lower}\n")

    def test_pr_base_prints_the_open_prs_base_or_nothing(self):
        fake_gh(self, self.repo)
        self.assertEqual(cli("pr-base", "--branch", "feat/x", "--repo", "o/r").stdout, "nightly\n")
        none = cli("pr-base", "--branch", "feat/none", "--repo", "o/r")
        self.assertEqual((none.returncode, none.stdout, none.stderr), (0, "", ""))

    def test_pr_base_exits_1_with_the_reason_when_gh_fails(self):
        fake_gh(self, self.repo)
        result = cli("pr-base", "--branch", "feat/boom", "--repo", "o/r")
        self.assertEqual((result.returncode, result.stdout), (1, ""))
        self.assertIn("HTTP 500", result.stderr)

    def test_a_pr_header_that_is_not_a_number_exits_1_without_a_traceback(self):
        self.repo.manifest("01-contract", "# base: main\n# pr: #52\na.ts\n")
        result = cli("heads", "--manifests", self.manifests, "--prefix", "s-", "--repo", "o/r")
        self.assertEqual(result.returncode, 1)
        self.assertIn("01-contract: '# pr:' is not a PR number: #52", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_a_bad_stack_exits_1_with_the_reason(self):
        result = cli("layers", "--manifests", self.manifests)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no '# branch:' header and no --prefix", result.stderr)


if __name__ == "__main__":
    unittest.main()
