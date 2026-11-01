"""Behavior tests for loop.py brief: the reviewer's task and the round's shared context file.

Run from this directory: python3 -m unittest test_loop_brief
"""

import unittest

from loop_fixture import SKILL_DIR, LoopCase, finding

RULES = SKILL_DIR.parent / "pedro-best-practices" / "references"


class BriefTests(LoopCase):
    def test_brief_names_the_contract_the_output_and_the_id_prefix(self):
        code, out = self.run_loop("brief", self.loop, 1, "audit", "--model", "gpt-6.1-sol high",
                                  "--checkout", self.repo)
        self.assertEqual(code, 0, out)
        self.assertIn(f"Read {self.loop.resolve()}/r1/context.md in full before anything else.", out)
        self.assertIn(f"- PR 7 (branch): the whole change, `git diff {self.base} {self.first}`.", out)
        self.assertIn(f"Write your findings to {self.loop.resolve()}/r1/audit-7.json, numbering their IDs R1-PBP7-1",
                      out)
        self.assertIn(f"check {self.loop.resolve()} 1 --only audit-7 --checkout {self.repo}", out)
        self.assertEqual((self.loop / "r1" / "reviewers.tsv").read_text(),
                         "audit-7\taudit\twhole\t7\tgpt-6.1-sol high\n")

    def test_brief_writes_one_context_file_for_the_round(self):
        self.two_rounds()
        self.run_loop("brief", self.loop, 2, "audit", "--delta", "--model", "gpt-6.1-sol high")
        context = (self.loop / "r2" / "context.md").read_text()
        reviewer_md = (SKILL_DIR / "reviewer.md").read_text().strip()
        self.assertIn(f'<file path="{SKILL_DIR}/reviewer.md">\n{reviewer_md}\n</file>', context)
        self.assertIn(f'<file path="{self.loop.resolve()}/common.md">\n# Pass packet', context)
        self.assertIn(f"## Round 2\n\n- PR 7 (branch): fork `{self.base}`, head `{self.second}`\n", context)
        self.assertIn("- Ruling: keep the retry.\n</file>", context)
        self.assertIn("## Reviewers this round\n\n- delta: delta, delta, PR 7\n- audit-7: audit, delta, PR 7\n",
                      context)
        self.assertIn(f"## Settled findings\n\n"
                      "The last outcome of every other finding from earlier rounds; a round's `<reviewer>.json` holds the "
                      "full record.\nA finding fixed in the previous round carries the recommendation its fix "
                      f"answers.\n\n- R1-STD-1 (P2 bug, PR 7, app.py:2) fixed in {self.second[:9]}. "
                      "Errors are swallowed.\n  Recommendation: Return the error.\n", context)
        self.assertTrue(context.endswith("Recommendation: Return the error.\n"),
                        "round 2's own findings are not settled")

    def test_brief_refuses_a_round_without_its_packet(self):
        (self.loop / "common.md").unlink()
        code, out = self.run_loop("brief", self.loop, 1, "spec", "--model", "m")
        self.assertEqual((code, out), (2, f"loop.py: write {self.loop.resolve()}/common.md before the briefs\n"))
        self.assertFalse((self.loop / "r1" / "reviewers.tsv").exists())

    def test_brief_refuses_a_delta_with_no_diff(self):
        self.heads(2, self.second)
        code, out = self.run_loop("brief", self.loop, 2, "delta", "--model", "m")
        self.assertEqual((code, out), (2, "loop.py: PR 7 has no delta in r2; review it whole or skip it\n"))

    def test_a_branch_in_the_pr_column_gets_an_encoded_reviewer_name_and_delta_file(self):
        for n, head in ((1, self.first), (2, self.second)):
            self.heads(n, head)
            (self.loop / f"r{n}" / "heads.tsv").write_text(f"pedro/feature\tbranch\t{self.base}\t{head}\n")
        (self.loop / "r2" / "delta-pedro%2Ffeature.diff").write_text("diff\n")
        code, out = self.run_loop("brief", self.loop, 2, "audit", "--delta", "--model", "m")
        self.assertEqual(code, 0, out)
        self.assertIn(f"{self.loop.resolve()}/r2/audit-pedro%2Ffeature.json", out)
        self.assertIn(f"in `{self.loop.resolve()}/r2/delta-pedro%2Ffeature.diff`", out)

    def test_branches_that_differ_only_in_a_slash_get_their_own_audits(self):
        rows = "".join(f"{b}\tbranch\t{self.base}\t{self.first}\n" for b in ("pedro/a", "pedro-a"))
        (self.loop / "r1" / "heads.tsv").write_text(rows)
        for branch in ("pedro/a", "pedro-a"):
            self.run_loop("brief", self.loop, 1, "audit", "--pr", branch, "--model", "m")
        names = [line.split("\t")[0] for line in (self.loop / "r1" / "reviewers.tsv").read_text().splitlines()]
        self.assertEqual(names, ["audit-pedro%2Fa", "audit-pedro-a"])

    def test_an_audit_brief_lists_the_rules_and_the_references_for_its_files(self):
        code, out = self.run_loop("brief", self.loop, 1, "audit", "--model", "m", "--checkout", self.repo)
        self.assertEqual(code, 0, out)
        self.assertIn(f"Your role's files are {RULES}/rules.md, {RULES}/complexity.md, {RULES}/construction-rules.md, "
                      f"and the\nlanguage references for your scope's files: {RULES}/python.md.\n", out)
        self.assertIn(f"Checkout: `{self.repo}`", (self.loop / "r1" / "context.md").read_text())

    def test_a_delta_audit_takes_its_references_from_the_delta(self):
        self.heads(2, self.second)
        (self.loop / "r2" / "delta-7.diff").write_text("diff --git a/ui/view.tsx b/ui/view.tsx\n+x\n"
                                                       "diff --git a/ui/old.py b/ui/new.php\n")
        out = self.run_loop("brief", self.loop, 2, "audit", "--delta", "--model", "m")[1]
        self.assertIn(f"language references for your scope's files: {RULES}/php.md, {RULES}/react.md.\n", out)

    def test_a_whole_audit_with_no_checkout_points_at_the_languages_table(self):
        out = self.run_loop("brief", self.loop, 1, "audit", "--model", "m")[1]
        self.assertIn('your scope\'s files: each one rules.md "Languages" names for your files.\n', out)

    def test_other_roles_get_no_audit_reading(self):
        out = self.run_loop("brief", self.loop, 1, "standards", "--model", "m", "--checkout", self.repo)[1]
        self.assertNotIn("rules.md", out)

    def test_rulings_reach_every_round_and_the_next_pass(self):
        self.loop = self.root / "pr-7-p1"
        self.setUpLoop()
        self.two_rounds()
        self.run_loop("outcome", self.loop, "R2-DELTA-1", "ruled", "--note", "Pedro keeps the ternary.")
        self.heads(3, self.second)
        (self.loop / "r3" / "delta-7.diff").write_text("diff\n")
        self.run_loop("brief", self.loop, 3, "delta", "--model", "m")
        ruling = "(PR 7, app.py:1): A | in the title.\n  Ruling: Pedro keeps the ternary.\n"
        context = (self.loop / "r3" / "context.md").read_text()
        self.assertIn(f"\n- R2-DELTA-1 {ruling}", context)
        self.assertNotIn("R2-DELTA-1 (P3", context, "a ruling is not repeated under settled findings")
        self.loop = self.root / "pr-7-p2"
        self.setUpLoop()
        self.run_loop("brief", self.loop, 1, "standards", "--model", "m")
        context = (self.loop / "r1" / "context.md").read_text()
        self.assertIn(f"\n- R2-DELTA-1 from pr-7-p1 {ruling}", context)
        self.assertIn("## Settled findings\n\nThe last outcome", context)
        self.assertTrue(context.endswith("\n\nNone yet.\n"), "pass 1's other verdicts stay out of pass 2")


    def test_two_panels_of_one_role_keep_separate_files_and_ids(self):
        for panel, model in (("terra", "gpt-6.1-terra medium"), ("muse", "muse-spark-1.3 medium")):
            code, out = self.run_loop("brief", self.loop, 1, "audit", "--model", model, "--panel", panel)
            self.assertEqual(code, 0, out)
        self.assertIn(f"{self.loop.resolve()}/r1/audit-7-muse.json, numbering their IDs R1-MUSE-PBP7-1", out)
        self.assertEqual((self.loop / "r1" / "reviewers.tsv").read_text(),
                         "audit-7-terra\taudit\twhole\t7\tgpt-6.1-terra medium\tterra\n"
                         "audit-7-muse\taudit\twhole\t7\tmuse-spark-1.3 medium\tmuse\n")
        coverage = [{"check": "Cognitive complexity (limit 8)", "status": "clean"}]
        self.write(1, "audit-7-terra", {"findings": [finding(id="R1-TERRA-PBP7-1")], "coverage": coverage})
        self.write(1, "audit-7-muse", {"findings": [finding(id="R1-MUSE-PBP7-1")], "coverage": coverage})
        code, out = self.run_loop("check", self.loop, 1, "--checkout", self.repo)
        self.assertEqual(code, 0, out)
        self.assertIn("2 findings from 2 of 2 reviewers", out)

    def test_a_panel_name_is_a_short_lowercase_word(self):
        code, out = self.run_loop("brief", self.loop, 1, "standards", "--model", "m", "--panel", "Muse Spark")
        self.assertEqual(code, 2)
        self.assertIn("a panel is a short lowercase name", out)

if __name__ == "__main__":
    unittest.main()
