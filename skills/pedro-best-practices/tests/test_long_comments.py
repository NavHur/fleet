"""Behavior tests for long_comments.py.

Run from this directory: python3 -m unittest test_long_comments
`fixtures/comments.ts` holds the edge cases `dca/no-long-comment` was checked
against: both flag the comments starting on lines 1, 7, and 34 and no others.
"""

from __future__ import annotations

import os
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


class Script(unittest.TestCase):
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
        env = {**os.environ, "HOST_CHECK_ACTIVE": "1"}
        result = subprocess.run([sys.executable, str(SCRIPTS / "long_comments.py"), "HEAD", *args,
                                 "--repo", str(self.repo)], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_reports_changed_comments_with_the_repository_rule(self):
        (self.repo / ".oxlintrc.json").write_text('{"rules": {"team/no-long-comment": "error"}}\n')
        (self.repo / "old.ts").write_text("// one\n// two\n// three\nexport const a = 2;\n")
        (self.repo / "new.py").write_text("# one\n# two\n# three\nvalue = 1\n")
        output = self.scan()
        self.assertIn("new.py:1-3: 3 prose lines (file header) [not lint-checked]", output)
        self.assertNotIn("old.ts:1-3", output)
        self.assertIn("Result: 1 comment over the cap in 2 changed source files", output)
        self.assertIn("old.ts:1-3: 3 prose lines (file header) [lint: team/no-long-comment]", self.scan("--all"))


if __name__ == "__main__":
    unittest.main()

    def test_godot_guard_rule_and_baseline_tag_gdscript(self):
        (self.repo / ".godot-guard.yml").write_text("rules:\n  long-comment: error\n")
        (self.repo / ".godot-guard-baseline.json").write_text('{"long-comment": {"old.gd": 1}}\n')
        body = "extends Node\nvar a := 1\n# one\n# two\n# three\nvar b := 2\n"
        (self.repo / "old.gd").write_text(body)
        (self.repo / "new.gd").write_text(body)
        output = self.scan()
        self.assertIn("old.gd:3-5: 3 prose lines [lint: godot-guard/long-comment, baselined]", output)
        self.assertIn("new.gd:3-5: 3 prose lines [lint: godot-guard/long-comment]", output)
        (self.repo / ".godot-guard.yml").write_text("rules:\n  long-comment: off\n")
        self.assertIn("new.gd:3-5: 3 prose lines [not lint-checked]", self.scan())
