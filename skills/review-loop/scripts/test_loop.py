"""Behavior tests for loop.py check, outcome, render, and publish, run against a real Git checkout and a fake gh.

Run from this directory: python3 -m unittest test_loop
"""

import os
import textwrap
import unittest

from loop_fixture import LoopCase, finding

FAKE_GH = """\
#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
state = Path(os.environ["FAKE_GH_STATE"])
calls = state / "calls"
calls.open("a").write(json.dumps(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if args[0] != "api":
    sys.exit(f"not REST: {args}")
if args[1] == "repos/acme/app/pulls/7":
    print(json.dumps({"head": {"sha": (state / "head").read_text()}, "base": {"ref": "main"}}))
elif "POST" in args:
    (state / "body.md").write_text(Path(args[args.index("-F") + 1].removeprefix("body=@")).read_text())
    print("https://github.com/acme/app/pull/7#issuecomment-1")
elif args[1] == "repos/acme/app/issues/7/comments":
    print((state / "posted").read_text() if (state / "posted").exists() else "")
else:
    sys.exit(f"unexpected: {args}")
"""


class LoopTests(LoopCase):
    def test_check_passes_a_valid_file_and_lists_its_findings(self):
        self.run_loop("brief", self.loop, 1, "standards", "--model", "m")
        self.write(1, "standards", {"findings": [finding()]})
        code, out = self.run_loop("check", self.loop, 1, "--checkout", self.repo)
        self.assertEqual(code, 0, out)
        self.assertEqual(out, "standards: ok\n1 findings from 1 of 1 reviewers\n"
                              "R1-STD-1  P2 bug  PR 7  app.py:2  Errors are swallowed.\n")

    def test_check_reports_each_problem_in_a_bad_file(self):
        self.run_loop("brief", self.loop, 1, "audit", "--model", "m")
        self.write(1, "audit-7", {"findings": [
            finding(id="STD-1", priority="High", kind="bug", file="gone.py"),
            finding(id="R1-PBP7-2", line=99),
            finding(id="R1-PBP7-3", pr="8", title=""),
        ]})
        code, out = self.run_loop("check", self.loop, 1, "--checkout", self.repo)
        self.assertEqual(code, 1)
        self.assertEqual(out, textwrap.dedent(f"""\
            audit-7: FAIL
              an audit needs a coverage entry for every check
              STD-1: id must start with R1-PBP7-
              STD-1: priority must be one of P1, P2, P3
              STD-1: gone.py does not exist at {self.first[:9]}
              R1-PBP7-2: line 99 is past the end of app.py at {self.first[:9]}
              R1-PBP7-3: missing title
              R1-PBP7-3: pr must be one of 7
            0 findings from 0 of 1 reviewers
            """))

    def test_check_takes_an_empty_coverage_list_from_any_role_but_an_audit(self):
        self.run_loop("brief", self.loop, 1, "standards", "--model", "m")
        self.run_loop("brief", self.loop, 1, "audit", "--model", "m")
        self.write(1, "standards", {"findings": [], "coverage": []})
        self.write(1, "audit-7", {"findings": [], "coverage": []})
        code, out = self.run_loop("check", self.loop, 1)
        self.assertEqual((code, out), (1, "standards: ok\naudit-7: FAIL\n  an audit needs a coverage entry for every "
                                          "check\n0 findings from 1 of 2 reviewers\n"))

    def test_check_marks_a_finding_near_an_earlier_fix(self):
        self.two_rounds()
        code, out = self.run_loop("check", self.loop, 2)
        self.assertEqual(code, 0, out)
        self.assertTrue(out.endswith("R2-DELTA-1  P3 advisory  PR 7  app.py:1  A | in the title.\n"
                                     "  near fixed R1-STD-1\n"), out)
        self.write(2, "delta", {"findings": [finding(id="R2-DELTA-1", line=30), finding(id="R2-DELTA-2", file=None,
                                                                                         line=None)]})
        self.assertNotIn("near fixed", self.run_loop("check", self.loop, 2)[1])

    def test_check_reports_a_reviewer_that_has_not_written(self):
        self.run_loop("brief", self.loop, 1, "spec", "--model", "m")
        code, out = self.run_loop("check", self.loop, 1)
        self.assertEqual((code, out), (1, "spec: FAIL\n  spec.json has not been written\n"
                                          "0 findings from 0 of 1 reviewers\n"))

    def test_outcome_needs_a_known_finding_and_the_status_fields(self):
        self.two_rounds()
        self.assertEqual(self.run_loop("outcome", self.loop, "R9-STD-1", "declined", "--note", "x"),
                         (2, "loop.py: no finding R9-STD-1 in this loop\n"))
        self.assertEqual(self.run_loop("outcome", self.loop, "R2-DELTA-1", "fixed"),
                         (2, "loop.py: a fixed finding needs --commit\n"))
        self.assertEqual(self.run_loop("outcome", self.loop, "R2-DELTA-1", "decision"),
                         (2, "loop.py: a decision finding needs --note\n"))

    def test_render_builds_the_comment_from_rounds_findings_and_outcomes(self):
        self.two_rounds()
        self.run_loop("outcome", self.loop, "R2-DELTA-1", "decision", "--note", "Keep it?")
        code, out = self.run_loop("render", self.loop, "7", "--checkout", self.repo)
        self.assertEqual(code, 0, out)
        s, f = self.second, self.first
        self.assertEqual(out, textwrap.dedent(f"""\
            <!-- review-loop pr-7 r2 {s} -->
            ## Review loop

            > [!NOTE]
            > 2 findings over 2 rounds: 1 fixed, 1 awaiting a decision. Coverage: 2 gaps.

            Reviewed head [`{s[:9]}`](https://github.com/acme/app/commit/{s}) from fork point `{self.base[:9]}` · reviewers: gpt-6.1-sol high

            <details><summary>Rounds and findings: 2 rounds, 2 findings, 1 fixed</summary>

            | Round | Review | Head | Findings | Fixed |
            | --- | --- | --- | ---: | ---: |
            | r1 | whole: standards, audit | `{f[:9]}` | 1 | 1 |
            | r2 | delta: delta | `{s[:9]}` | 1 | 0 |

            - P2 bug: **Errors are swallowed.** Fixed in `{s[:9]}`\\
              `R1-STD-1` · README.md "Errors" · `app.py:2`
            - P3 advisory: **A | in the title.** Awaiting a decision: Keep it?\\
              `R2-DELTA-1` · pedro/no-nested-ternary · [`app.py:1`](https://github.com/acme/app/blob/{s}/app.py#L1)

            #### R1-STD-1: Errors are swallowed.

            README.md "Errors" · `app.py:2` · Fixed in `{s[:9]}`

            **Evidence**

            `except: pass`

            **Failure.** A failed save looks like a success.

            **Recommendation.** Return the error.

            #### R2-DELTA-1: A | in the title.

            pedro/no-nested-ternary · `app.py:1` · Awaiting a decision: Keep it?

            **Evidence**

            `except: pass`

            **Recommendation.** Return the error.

            </details>

            <details><summary>Coverage: 2 checks, 2 gaps</summary>

            | Check | Result | Note |
            | --- | --- | --- |
            | Standards: Core runtime | Incomplete | not vendored |
            | Cognitive complexity (limit 8) | Incomplete | php missing |

            </details>

            """))

    def test_render_reports_a_settled_clean_loop(self):
        self.two_rounds()
        self.write(1, "standards", {"findings": [finding()]})
        self.write(1, "audit-7", {"findings": [], "coverage": [{"check": "Nested conditionals", "status": "clean"}]})
        self.run_loop("outcome", self.loop, "R2-DELTA-1", "ruled", "--note", "Pedro keeps it")
        out = self.run_loop("render", self.loop, "7", "--checkout", self.repo)[1]
        self.assertIn("> [!NOTE]\n> 2 findings over 2 rounds: 1 fixed, 1 settled by a ruling. Coverage: complete.",
                      out)
        self.assertIn("**A | in the title.** Ruled: Pedro keeps it\\\n", out)
        self.assertIn("<details><summary>Coverage: 1 check, 0 gaps</summary>\n\n| Check | Result | Note |\n| --- | --- | --- |\n"
                      "| Nested conditionals | Clean |  |\n", out)

    def publish(self, remote_head, *args, posted=""):
        state = self.root / "gh"
        state.mkdir(exist_ok=True)
        (state / "head").write_text(remote_head)
        (state / "posted").write_text(posted)
        fake = state / "gh"
        fake.write_text(FAKE_GH)
        fake.chmod(0o755)
        env = {**os.environ, "PATH": f"{state}:{os.environ['PATH']}", "FAKE_GH_STATE": str(state)}
        return self.run_loop("publish", self.loop, "--checkout", self.repo, *args, env=env), state

    def settled_rounds(self):
        self.two_rounds()
        self.run_loop("outcome", self.loop, "R2-DELTA-1", "ruled", "--note", "Pedro keeps it")

    def test_publish_posts_the_rendered_comment_when_github_has_the_reviewed_head(self):
        self.settled_rounds()
        (code, out), state = self.publish(self.second)
        self.assertEqual((code, out), (0, "PR 7: posted https://github.com/acme/app/pull/7#issuecomment-1\n"))
        rendered = self.run_loop("render", self.loop, "7", "--checkout", self.repo)[1]
        self.assertEqual((state / "body.md").read_text() + "\n", rendered)

    def test_publish_refuses_while_a_finding_still_needs_pedro(self):
        self.two_rounds()
        self.run_loop("outcome", self.loop, "R1-STD-1", "decision", "--note", "Keep it?")
        (code, out), state = self.publish(self.second)
        self.assertEqual((code, out), (2, "loop.py: not posted: PR 7 has R1-STD-1, R2-DELTA-1 open or awaiting a "
                                          "decision. Put each to the user and record the outcome, then publish "
                                          "again.\n"))
        self.assertFalse((state / "body.md").exists())

    def test_publish_skips_a_pr_whose_github_head_differs(self):
        self.settled_rounds()
        (code, out), state = self.publish(self.first)
        self.assertEqual(out, f"PR 7: GitHub has {self.first[:9]} but the loop reviewed {self.second[:9]}; "
                              "not posted. Run publish again once the reviewed head is pushed.\n")
        self.assertFalse((state / "body.md").exists())

    def final_pass(self):
        """A second ledger on the same PR: one whole round at the first pass's final head."""
        earlier, self.loop = self.loop, self.root / "pr-7-opus"
        self.heads(1, self.second)
        (self.loop / "common.md").write_text("# Pass packet\n")
        (self.loop / "ledger.md").write_text("# Review loop: acme/app #7, Opus pass\n")
        (self.loop / "run.json").write_text("{}\n")
        self.run_loop("brief", self.loop, 1, "standards", "--model", "claude-opus-5-5 medium")
        self.write(1, "standards", {"findings": [finding(priority="P3", kind="violation", line=1, failure="",
                                                         title="A stale comment.")]})
        self.run_loop("outcome", self.loop, "R1-STD-1", "declined", "--note", "The comment is accurate")
        return earlier

    def test_render_with_an_earlier_pass_reports_both_ledgers_in_one_comment(self):
        self.two_rounds()
        earlier = self.final_pass()
        code, out = self.run_loop("render", self.loop, "7", "--checkout", self.repo, "--earlier", earlier)
        self.assertEqual(code, 0, out)
        s, f = self.second, self.first
        self.assertTrue(out.startswith(textwrap.dedent(f"""\
            <!-- review-loop pr-7-opus r1 {s} -->
            ## Review loop

            > [!NOTE]
            > 3 findings over 3 rounds in 2 passes: 1 fixed, 1 declined, 1 open. Coverage: 2 gaps.

            Reviewed head [`{s[:9]}`](https://github.com/acme/app/commit/{s}) from fork point `{self.base[:9]}` · reviewers: claude-opus-5-5 medium, gpt-6.1-sol high

            <details><summary>Pass 1, gpt-6.1-sol high: 2 rounds, 2 findings, 1 fixed</summary>

            | Round | Review | Head | Findings | Fixed |
            | --- | --- | --- | ---: | ---: |
            | r1 | whole: standards, audit | `{f[:9]}` | 1 | 1 |
            | r2 | delta: delta | `{s[:9]}` | 1 | 0 |

            - P2 bug: **Errors are swallowed.** Fixed in `{s[:9]}`\\
              `R1-STD-1` · README.md "Errors" · `app.py:2`
            - P3 advisory: **A | in the title.** Open\\
              `R2-DELTA-1` · pedro/no-nested-ternary · `app.py:1`
            """)), out)
        self.assertTrue(out.endswith(textwrap.dedent(f"""\
            <details><summary>Pass 2, claude-opus-5-5 medium: 1 round, 1 finding, 0 fixed</summary>

            | Round | Review | Head | Findings | Fixed |
            | --- | --- | --- | ---: | ---: |
            | r1 | whole: standards | `{s[:9]}` | 1 | 0 |

            - P3 violation: **A stale comment.** Declined: The comment is accurate\\
              `R1-STD-1` · README.md "Errors" · [`app.py:1`](https://github.com/acme/app/blob/{s}/app.py#L1)

            #### R1-STD-1: A stale comment.

            README.md "Errors" · `app.py:1` · Declined: The comment is accurate

            **Evidence**

            `except: pass`

            **Recommendation.** Return the error.

            </details>

            <details><summary>Coverage: 2 checks, 2 gaps</summary>

            | Check | Result | Note |
            | --- | --- | --- |
            | Standards: Core runtime | Incomplete | not vendored |
            | Cognitive complexity (limit 8) | Incomplete | php missing |

            </details>

            """)), out)

    def test_render_refuses_an_earlier_pass_that_never_pinned_the_pr(self):
        self.two_rounds()
        earlier = self.final_pass()
        (earlier / "r1" / "heads.tsv").write_text(f"8\tother\t{self.base}\t{self.first}\n")
        (earlier / "r2" / "heads.tsv").write_text(f"8\tother\t{self.base}\t{self.second}\n")
        code, out = self.run_loop("render", self.loop, "7", "--checkout", self.repo, "--earlier", earlier)
        self.assertEqual((code, out), (2, "loop.py: PR 7 is in no round's heads.tsv\n"))

    def test_publish_with_an_earlier_pass_posts_the_unified_comment(self):
        self.settled_rounds()
        earlier = self.final_pass()
        (code, out), state = self.publish(self.second, "--earlier", earlier)
        self.assertEqual((code, out), (0, "PR 7: posted https://github.com/acme/app/pull/7#issuecomment-1\n"))
        rendered = self.run_loop("render", self.loop, "7", "--checkout", self.repo, "--earlier", earlier)[1]
        self.assertEqual((state / "body.md").read_text() + "\n", rendered)

    def test_publish_posts_a_round_once(self):
        self.settled_rounds()
        url = "https://github.com/acme/app/pull/7#issuecomment-9"
        (code, out), state = self.publish(self.second, posted=url)
        self.assertEqual(out, f"PR 7: already posted, {url}\n")
        self.assertFalse((state / "body.md").exists())


if __name__ == "__main__":
    unittest.main()
