"""Behavior tests for long_comments.py.

Run from this directory: python3 -m unittest test_long_comments
`fixtures/comments.ts` holds the edge cases `dca/no-long-comment` was checked
against: both flag the comments starting on lines 1, 7, and 34 and no others.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import guard_oracle  # noqa: E402
import long_comments  # noqa: E402


def found(path: str, source: str) -> list[tuple[int, int, bool]]:
    return [(c.line, c.prose, c.header) for c in long_comments.long_comments(path, textwrap.dedent(source))]


class Scanner(unittest.TestCase):
    def test_js_matches_the_lint_rule(self):
        source = (HERE / "fixtures" / "comments.ts").read_text()
        self.assertEqual([c.line for c in long_comments.long_comments("comments.ts", source)], [1, 7, 34])

    def test_python_reads_comments_from_tokens(self):
        self.assertEqual(found("tool.py", '''\
            #!/usr/bin/env python3
            # -*- coding: utf-8 -*-
            """Docstrings are documentation,
            however long
            they run."""
            TEMPLATE = """
            # a string, not a comment
            # still a string
            # and again
            """
            # noqa: E501
            # one
            # two
            # three
            value = 1  # trailing
            '''), [(11, 3, False)])

    def test_gdscript_skips_doc_comments_and_marks_headers(self):
        self.assertEqual(found("unit.gd", """\
            extends Node
            # Header one
            # Header two
            # Header three

            ## Doc one
            ## Doc two
            ## Doc three
            var speed := 1.0
            # gdlint: disable=max-line-length
            # one
            # two
            """), [(2, 3, True)])

    def test_php_comment_forms(self):
        self.assertEqual(found("Invoice.php", """\
            <?php
            #[Attribute]
            /**
             * Doc one
             * Doc two
             * Doc three
             */
            final class Invoice
            {
                # one
                // two
                # three
            }
            """), [(10, 3, False)])
        self.assertEqual(found("card.blade.php", """\
            {{-- one
                 two
                 three --}}
            <div></div>
            """), [(1, 3, True)])

    def test_svelte_markup_comments(self):
        self.assertEqual(found("Card.svelte", """\
            <script>
              let open = false;
            </script>
            <!--
              one
              https://example.com/reference
              two
              three
            -->
            <div></div>
            """), [(4, 3, False)])


class ScriptCase(unittest.TestCase):
    """long_comments.py against a throwaway git repository."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="pbp-comments-"))
        self.addCleanup(shutil.rmtree, self.repo)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        (self.repo / "old.ts").write_text("// one\n// two\n// three\nexport const a = 1;\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)

    def scan(self, *args: str) -> str:
        env = {**os.environ, "HOST_CHECK_ACTIVE": "1", "PBP_GODOT_GUARD": guard_oracle.GODOT_GUARD or ""}
        result = subprocess.run([sys.executable, str(SCRIPTS / "long_comments.py"), "HEAD", *args,
                                 "--repo", str(self.repo)], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout


class Script(ScriptCase):
    def test_reports_changed_comments_with_the_repository_rule(self):
        (self.repo / ".oxlintrc.json").write_text('{"rules": {"team/no-long-comment": "error"}}\n')
        (self.repo / "old.ts").write_text("// one\n// two\n// three\nexport const a = 2;\n")
        (self.repo / "new.py").write_text("# one\n# two\n# three\nvalue = 1\n")
        output = self.scan()
        self.assertIn("new.py:1-3: 3 prose lines (file header) [not lint-checked]", output)
        self.assertNotIn("old.ts:1-3", output)
        self.assertIn("Result: 1 comment over the cap in 2 changed source files", output)
        self.assertIn("old.ts:1-3: 3 prose lines (file header) [lint: team/no-long-comment]", self.scan("--all"))

    @unittest.skipUnless(guard_oracle.GODOT_GUARD, guard_oracle.MISSING)
    def test_godot_guard_rule_and_baseline_tag_gdscript(self):
        (self.repo / ".godot-guard.yml").write_text("rules:\n  long-comment: error\n")
        (self.repo / ".godot-guard-baseline.json").write_text('{"long-comment": {"old.gd": 1}}\n')
        body = "extends Node\nvar a := 1\n# one\n# two\n# three\nvar b := 2\n"
        (self.repo / "old.gd").write_text(body)
        (self.repo / "new.gd").write_text(body)
        output = self.scan()
        self.assertIn("old.gd:3-5: 3 prose lines [lint passes: godot-guard/long-comment]", output)
        self.assertIn("new.gd:3-5: 3 prose lines [lint: godot-guard/long-comment]", output)
        self.assertIn("1 under a repository lint rule, 1 that lint passes, 0 not lint-checked.", output)
        (self.repo / ".godot-guard.yml").write_text("rules:\n  long-comment: off\n")
        self.assertIn("new.gd:3-5: 3 prose lines [not lint-checked]", self.scan())


TAGS = {"error": "[lint: godot-guard/long-comment]", "warning": "[lint: godot-guard/long-comment, warning]",
        "passes": "[lint passes: godot-guard/long-comment]", "unchecked": "[not lint-checked]"}
LISTED = re.compile(r"^(\S+):(\d+)-\d+: \d+ prose lines(?: \(file header\))? (\[.+\])$", re.M)
COMMENT = "extends Node\nvar a := 1\n# one\n# two\n# three\nvar b := 2\n"
HEADER = "# header one\n# header two\n# header three\n"


@unittest.skipUnless(guard_oracle.GODOT_GUARD, guard_oracle.MISSING)
class GodotGuardVerdicts(ScriptCase):
    """Each GDScript comment's tag equals what `godot-guard check` decides, where a re-implementation got it wrong."""

    def write(self, name: str, text: str) -> None:
        (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / name).write_text(text)

    def assert_tags(self, expected: dict[tuple[str, int], str]) -> None:
        listed = {(path, int(line)): tag for path, line, tag in LISTED.findall(self.scan())}
        self.assertEqual(listed, expected)
        decided = {(path, line): TAGS[guard_oracle.verdict(self.repo, path, line, ("long-comment",))]
                   for path, line in expected}
        self.assertEqual(decided, expected)

    def test_a_loose_baseline_entry_fails(self):
        self.write(".godot-guard.yml", "")
        self.write(".godot-guard-baseline.json", json.dumps({"version": 1, "long-comment": {"unit.gd": 2}}))
        self.write("unit.gd", COMMENT)
        self.assert_tags({("unit.gd", 3): "[lint: godot-guard/long-comment]"})

    def test_file_headers_and_the_comment_lines_cap_follow_godot_guard(self):
        self.write(".godot-guard.yml", "limits: {comment-lines: 3}\n")
        self.write("header.gd", HEADER + "extends Node\nvar a := 1\n")
        self.write("unit.gd", COMMENT)
        self.assert_tags({("header.gd", 1): "[lint passes: godot-guard/long-comment]",
                          ("unit.gd", 3): "[lint passes: godot-guard/long-comment]"})

    def test_a_header_does_not_count_against_the_baseline(self):
        self.write(".godot-guard.yml", "")
        self.write(".godot-guard-baseline.json", json.dumps({"version": 1, "long-comment": {"unit.gd": 1}}))
        self.write("unit.gd", HEADER + COMMENT)
        self.assert_tags({("unit.gd", 1): "[lint passes: godot-guard/long-comment]",
                          ("unit.gd", 6): "[lint passes: godot-guard/long-comment]"})

    def test_excluded_and_hidden_scripts_are_not_lint_checked(self):
        self.write(".godot-guard.yml", "exclude: [vendor/**]\nrules: {long-comment: warn}\n")
        for name in ("unit.gd", "vendor/unit.gd", ".hidden/unit.gd"):
            self.write(name, COMMENT)
        self.assert_tags({("unit.gd", 3): "[lint: godot-guard/long-comment, warning]",
                          ("vendor/unit.gd", 3): "[not lint-checked]", (".hidden/unit.gd", 3): "[not lint-checked]"})


if __name__ == "__main__":
    unittest.main()
