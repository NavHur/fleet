"""Behavior tests for complexity_parity.py: it must report every difference and accept only agreement.

Run from this directory: python3 -m unittest test_complexity_parity
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def function(name: str, line: int, cognitive: int | None = 0, cyclomatic: int = 1, end_line: int = 0) -> dict:
    return {"name": name, "line": line, "end_line": end_line or line, "cyclomatic": cyclomatic,
            "cognitive": cognitive}


class Parity(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.source = self.dir / "a.src"
        self.source.write_text("")

    def analyzer(self, name: str, value: object) -> str:
        """A fake analyzer printing `value` for every file it is given."""
        output = self.dir / f"{name}.json"
        output.write_text(json.dumps(value))
        script = self.dir / f"{name}.py"
        script.write_text("import json, sys\n"
                          f"value = json.load(open({str(output)!r}))\n"
                          "print(json.dumps({path: value for path in sys.argv[1:]}))\n")
        return f"{sys.executable} {script}"

    def compare(self, reference: object, candidate: object, *flags: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(HERE / "complexity_parity.py"),
                               "--reference", self.analyzer("reference", reference),
                               "--candidate", self.analyzer("candidate", candidate), *flags, str(self.source)],
                              capture_output=True, text=True)

    def test_identical_outputs_pass(self):
        functions = [function("pick", 1, 14, 10), function("<lambda>", 1, None)]
        result = self.compare(functions, functions)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("2 function(s), 0 rejected file(s): 0 difference(s)", result.stdout)

    def test_each_field_difference_is_reported(self):
        result = self.compare([function("pick", 1, 14, 10, 9)], [function("pick", 1, 13, 11, 8)])
        self.assertEqual(result.returncode, 1)
        for field in ("cognitive 14 != 13", "cyclomatic 10 != 11", "end_line 9 != 8"):
            self.assertIn(field, result.stdout)

    def test_a_missing_or_renamed_function_is_reported(self):
        result = self.compare([function("a", 1), function("b", 5)], [function("c", 1)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("name 'a' != 'c'", result.stdout)
        self.assertIn(":5: only in reference", result.stdout)

    def test_a_file_only_one_side_rejects_is_reported(self):
        result = self.compare({"error": "SyntaxError: x"}, [])
        self.assertEqual(result.returncode, 1)
        self.assertIn("reference error (SyntaxError: x), candidate 0 function(s)", result.stdout)
        self.assertEqual(self.compare({"error": "a"}, {"error": "b"}).returncode, 0)

    def test_gdscript_names_accept_only_godot_guards_qualified_forms(self):
        reference = [function("<lambda>", 3, None), function("set", 7), function("named", 9, None)]
        candidate = [function("outer.<lambda#1>", 3, None), function("hp.set", 7), function("outer.named", 9, None)]
        self.assertEqual(self.compare(reference, candidate).returncode, 1)
        self.assertEqual(self.compare(reference, candidate, "--gdscript-names").returncode, 0)
        result = self.compare([function("pick", 1)], [function("pick2", 1)], "--gdscript-names")
        self.assertEqual(result.returncode, 1)

    def test_gdscript_names_accept_accessors_qualified_by_inner_class_and_property(self):
        self.assertEqual(self.compare([function("Inner.get", 8)], [function("Inner.p.get", 8)],
                                      "--gdscript-names").returncode, 0)
        for wrong in ("Other.p.get", "Inner.p.q.get", "p.get"):
            with self.subTest(candidate=wrong):
                result = self.compare([function("Inner.get", 8)], [function(wrong, 8)], "--gdscript-names")
                self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
