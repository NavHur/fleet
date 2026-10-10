"""Behavior tests for the complexity analyzers and measure_complexity.py.

Run from this directory: python3 -m unittest test_complexity
Languages whose toolchain is missing (gdtoolkit, php, the skill's oxlint) are
skipped with a reason, never silently passed.

The probe fixtures hold the same functions in each language, so their scores
cross-check: `pick` is cognitive 14 and cyclomatic 10 in every language.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SCRIPTS = SKILL / "scripts"
FIXTURES = HERE / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import godot_guard  # noqa: E402
import measure_complexity  # noqa: E402

OXLINT = SKILL / "node_modules" / ".bin" / "oxlint"


def scores(command: list[str], fixture: str) -> dict[tuple[str, int], tuple[int | None, int]]:
    result = subprocess.run([*command, str(FIXTURES / fixture)], capture_output=True, text=True, check=True)
    [functions] = json.loads(result.stdout).values()
    return {(f["name"], f["line"]): (f["cognitive"], f["cyclomatic"]) for f in functions}


class PythonAnalyzer(unittest.TestCase):
    def setUp(self):
        self.command = [measure_complexity.pick_python(SKILL), str(SCRIPTS / "complexity_python.py")]

    def test_probe_scores(self):
        self.assertEqual(scores(self.command, "probe.py"), {
            ("pick", 1): (14, 10),
            ("a1", 14): (2, 4),
            ("a2", 18): (3, 3),
            ("a5", 25): (7, 5),
            ("a8", 31): (3, 4),
            ("a9", 33): (2, 1),
            ("<lambda>", 34): (None, 2),
            ("a13", 36): (2, 2),
            ("a14", 38): (1, 2),
            ("K.m", 43): (2, 2),
        })

    def test_methods_recurse_only_through_self(self):
        self.assertEqual(scores(self.command, "class_recursion.py"), {
            ("walk", 1): (2, 2),
            ("Tree.walk", 6): (0, 1),
            ("Tree.depth", 9): (2, 2),
        })


class GDScriptAnalyzer(unittest.TestCase):
    def setUp(self):
        python = measure_complexity.pick_gdtoolkit_python(SKILL)
        if python is None:
            self.skipTest("no Python with gdtoolkit")
        self.command = [python, str(SCRIPTS / "complexity_gdscript.py")]

    def test_probe_scores(self):
        self.assertEqual(scores(self.command, "probe.gd"), {
            ("pick", 7): (18, 11),
            ("<lambda>", 22): (None, 2),
            ("helper", 25): (0, 1),
            ("Inner.m", 29): (2, 2),
        })


class PHPAnalyzer(unittest.TestCase):
    def setUp(self):
        if shutil.which("php") is None:
            self.skipTest("no php on PATH")
        self.command = [sys.executable, str(SCRIPTS / "complexity_php.py")]

    def test_probe_scores(self):
        self.assertEqual(scores(self.command, "probe.php"), {
            ("pick", 2): (14, 10),
            ("a8", 14): (3, 4),
            ("a9", 15): (4, 1),
            ("<arrow>", 15): (None, 2),
            ("<closure>", 15): (None, 2),
            ("a10", 16): (1, 3),
            ("a12", 17): (0, 3),
            ("a13", 18): (2, 2),
            ("a15", 19): (3, 5),
            ("a16", 20): (10, 6),
            ("K::m", 23): (2, 2),
            ("K::s", 24): (2, 2),
        })


@unittest.skipUnless(OXLINT.exists(), "run `pnpm install` in the skill directory for its oxlint")
class OxlintPlugin(unittest.TestCase):
    def lint(self, fixture: str) -> dict[int, dict[str, int]]:
        config = {
            "categories": {c: "off" for c in measure_complexity.CATEGORIES},
            "jsPlugins": [str(measure_complexity.PLUGIN)],
            "rules": {"pbp/cognitive-complexity": ["warn", {"max": 0}], "complexity": ["warn", {"max": 0}]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "config.json")
            path.write_text(json.dumps(config))
            result = subprocess.run([str(OXLINT), "-c", str(path), "--format", "json", str(FIXTURES / fixture)],
                                    capture_output=True, text=True)
        rows: dict[int, dict[str, int]] = {}
        for diagnostic in json.loads(result.stdout)["diagnostics"]:
            line = diagnostic["labels"][0]["span"]["line"]
            metric = "cognitive" if "cognitive" in diagnostic["code"] else "cyclomatic"
            score = int(measure_complexity.SCORE.search(diagnostic["message"]).group(1))
            rows.setdefault(line, {}).setdefault(metric, score)
        return rows

    def test_probe_scores_match_the_other_languages(self):
        rows = self.lint("probe.ts")
        self.assertEqual(rows[1], {"cognitive": 14, "cyclomatic": 10})
        self.assertEqual({line: row.get("cognitive", 0) for line, row in rows.items()}, {
            1: 14, 13: 2, 14: 3, 15: 3, 16: 3, 17: 7, 18: 4, 19: 4, 20: 3, 21: 2, 22: 1, 23: 11, 24: 0, 25: 2, 26: 2,
        })

    def test_svelte_script_blocks(self):
        self.assertEqual(self.lint("probe.svelte"), {4: {"cognitive": 5, "cyclomatic": 5}})


class GodotInterface(unittest.TestCase):
    def test_counts_exports_signals_and_setup_parameters(self):
        import godot_interface

        surface = godot_interface.parse("unit.gd", textwrap.dedent("""\
            extends Node2D
            signal died(at: Vector2)
            signal healed
            @export_category("Tuning")
            @export var speed: float = 1.0
            @export_range(0, 10, 1)
            var armor: int = 2
            @onready var sprite := $Sprite2D
            var hidden := 0

            func _init(
            \tlabel: String,
            \torigin: Vector2 = Vector2(1, 2),
            ) -> void:
            \tpass

            func configure(team: int) -> void:
            \tpass

            class Inner:
            \tsignal not_counted
            \t@export var nor_this: int
            """))
        self.assertEqual(surface.signals, ["died", "healed"])
        self.assertEqual(surface.exports, ["speed", "armor"])
        self.assertEqual(surface.parameters, {"_init": ["label", "origin"], "configure": ["team"]})
        self.assertEqual(surface.total, 7)

    def test_resource_scripts_are_excluded_through_class_name_chains(self):
        import godot_interface

        base = godot_interface.parse("base.gd", "class_name Definition\nextends Resource\n")
        child = godot_interface.parse("enemy.gd", "extends Definition\n@export var hp: int\n")
        node = godot_interface.parse("node.gd", "extends Node\n")
        by_class = {"Definition": base}
        surfaces = {"base.gd": base, "enemy.gd": child, "node.gd": node}
        self.assertTrue(godot_interface.is_resource(child, by_class, surfaces))
        self.assertFalse(godot_interface.is_resource(node, by_class, surfaces))


class GodotGuardConfig(unittest.TestCase):
    CONFIG = """\
        paths: [scripts]
        limits:
          cognitive: 6   # stricter than Pedro's
          cyclomatic: 12
        rules: {nested-ternary: warn, long-comment: off}
        """

    def load(self, files: dict[str, str]):
        return godot_guard.load(files.get)

    def test_reads_limits_rules_and_baseline_without_pyyaml(self):
        sections = godot_guard.read_sections(textwrap.dedent(self.CONFIG))
        self.assertEqual(sections["limits"], {"cognitive": 6, "cyclomatic": 12})
        self.assertEqual(sections["rules"], {"nested-ternary": "warn", "long-comment": "off"})

    def test_load(self):
        guard = self.load({godot_guard.CONFIG: textwrap.dedent(self.CONFIG),
                           godot_guard.BASELINE: '{"version": 1, "cognitive-complexity": {"a.gd::f": 9}}'})
        self.assertEqual((guard.limits["cognitive"], guard.limits["cyclomatic"]), (6, 12))
        self.assertIsNone(guard.severity("long-comment"))
        self.assertEqual(guard.severity("cognitive-complexity"), "error")
        self.assertEqual(guard.allowance("cognitive-complexity", "a.gd::f"), 9)
        self.assertIsNone(self.load({}))


class MeasureScript(unittest.TestCase):
    """measure_complexity.py against a throwaway git repository."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="pbp-test-"))
        self.addCleanup(shutil.rmtree, self.repo)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        (self.repo / "keep.py").write_text("def ok():\n    return 1\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)

    def measure(self, *args: str) -> str:
        env = {**os.environ, "HOST_CHECK_ACTIVE": "1"}
        result = subprocess.run([sys.executable, str(SCRIPTS / "measure_complexity.py"), "HEAD", *args,
                                 "--repo", str(self.repo)], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def write(self, name: str, text: str) -> None:
        (self.repo / name).write_text(textwrap.dedent(text))

    def test_reports_a_python_excess_in_the_working_tree(self):
        self.write("deep.py", """\
            def deep(a, b, c):
                if a:
                    for x in b:
                        if x:
                            while c:
                                c -= 1
                return 0
            """)
        output = self.measure()
        self.assertIn("deep: cognitive 10, cyclomatic 5  OVER: cognitive 10 > 8 [not lint-checked]", output)
        self.assertIn("Result: 1 function over threshold among 1 changed functions in 1 changed source files "
                      "(1 python): 0 fail the repository's lint, 0 pass it, 1 not lint-checked.", output)

    def test_a_stricter_flag_wins_and_a_looser_one_is_ignored(self):
        self.write("mid.py", """\
            def mid(a, b):
                if a and b:
                    return 1
                return 0
            """)
        output = self.measure("--cognitive-limit", "1", "--cyclomatic-limit", "40")
        self.assertIn("OVER: cognitive 2 > 1 [not lint-checked]", output)
        self.assertIn("--cyclomatic-limit 40 is looser than Pedro's 16; ignored", output)

    def test_a_repository_ruff_limit_tightens_python(self):
        self.write("pyproject.toml", "[tool.ruff.lint.mccabe]\nmax-complexity = 2\n")
        self.write("mid.py", """\
            def mid(a, b):
                if a and b:
                    return 1
                return 0
            """)
        output = self.measure()
        self.assertIn("pyproject.toml: repository cyclomatic max 2", output)
        self.assertIn("OVER: cyclomatic 3 > 2 [not lint-checked]", output)

    @unittest.skipUnless(OXLINT.exists(), "skill oxlint not installed")
    def test_a_stricter_oxlint_max_fails_lint(self):
        self.write(".oxlintrc.json", '{"rules": {"complexity": ["error", {"max": 2}]}}')
        self.write("pick.ts", """\
            export function pick(a: number, b: boolean): number {
              if (a > 1 && b) return 1
              return 0
            }
            """)
        output = self.measure()
        self.assertIn("pick: cognitive 2, cyclomatic 3  OVER: cyclomatic 3 > 2 [lint: error]", output)
        self.assertIn("measured with fleet's pbp plugin", output)

    @unittest.skipUnless(OXLINT.exists(), "skill oxlint not installed")
    def test_svelte_without_any_config_uses_the_skill_oxlint(self):
        shutil.copy(FIXTURES / "probe.svelte", self.repo / "Label.svelte")
        output = self.measure()
        self.assertIn("Config: (no .oxlintrc.json) -> 1 JS-family file(s)", output)
        self.assertIn("L4-11 label: cognitive 5, cyclomatic 5", output)


if __name__ == "__main__":
    unittest.main()

    def test_godot_guard_limits_and_baseline_tag_gdscript(self):
        if measure_complexity.pick_gdtoolkit_python(self.repo) is None:
            self.skipTest("no Python with gdtoolkit")
        self.write(".godot-guard.yml", "limits:\n  cognitive: 2\n")
        self.write(".godot-guard-baseline.json", '{"cognitive-complexity": {"old.gd::pick": 3}}')
        body = """\
            extends Node


            func pick(a: bool, b: bool) -> int:
            \tif a:
            \t\tif b:
            \t\t\treturn 1
            \treturn 0
            """
        self.write("old.gd", body)
        self.write("new.gd", body)
        output = self.measure()
        self.assertIn(".godot-guard.yml: repository cognitive max 2, cyclomatic max 16", output)
        self.assertIn("old.gd:5 pick: cognitive 3 > 2 [lint passes]", output)
        self.assertIn("new.gd:5 pick: cognitive 3 > 2 [lint: error]", output)
