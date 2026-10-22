"""Behavior tests for the complexity analyzers and measure_complexity.py.

Run from this directory: python3 -m unittest test_complexity
Languages whose analyzer is missing (pbp-complexity, a godot-guard with
`complexity --json`, the skill's oxlint) are skipped with a reason, never
silently passed. `cargo build --release` in fleet provides pbp-complexity.

The probe fixtures hold the same functions in each language, so their scores
cross-check: `pick` is cognitive 14 and cyclomatic 10 in every language.
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
SKILL = HERE.parent
SCRIPTS = SKILL / "scripts"
FIXTURES = HERE / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import godot_guard  # noqa: E402
import guard_oracle  # noqa: E402
import measure_complexity  # noqa: E402
import measure_js  # noqa: E402

OXLINT = SKILL / "node_modules" / ".bin" / "oxlint"
PICK = """\
    extends Node


    func pick(a: bool, b: bool) -> int:
    \tif a:
    \t\tif b:
    \t\t\treturn 1
    \treturn 0
    """


def scores(command: list[str], fixture: str) -> dict[tuple[str, int], tuple[int | None, int]]:
    result = subprocess.run([*command, str(FIXTURES / fixture)], capture_output=True, text=True, check=True)
    [functions] = json.loads(result.stdout).values()
    return {(f["name"], f["line"]): (f["cognitive"], f["cyclomatic"]) for f in functions}


PBP_COMPLEXITY = measure_complexity.pbp_complexity()
NO_PBP_COMPLEXITY = "no pbp-complexity; run `cargo build --release` in fleet or set PBP_COMPLEXITY"
GDSCRIPT_SCORER = godot_guard.scorer(SKILL)
NO_GDSCRIPT_SCORER = "no godot-guard with `complexity --json`; set PBP_GODOT_GUARD to one (0.6+)"


@unittest.skipUnless(PBP_COMPLEXITY, NO_PBP_COMPLEXITY)
class PythonAnalyzer(unittest.TestCase):
    def setUp(self):
        self.command = [PBP_COMPLEXITY, "python"]

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


@unittest.skipUnless(GDSCRIPT_SCORER, NO_GDSCRIPT_SCORER)
class GDScriptAnalyzer(unittest.TestCase):
    def setUp(self):
        self.command = [GDSCRIPT_SCORER, "complexity", "--json"]

    def test_probe_scores(self):
        self.assertEqual(scores(self.command, "probe.gd"), {
            ("pick", 7): (18, 11),
            ("pick.<lambda#1>", 22): (None, 2),
            ("helper", 25): (0, 1),
            ("Inner.m", 29): (2, 2),
        })


@unittest.skipUnless(PBP_COMPLEXITY, NO_PBP_COMPLEXITY)
class PHPAnalyzer(unittest.TestCase):
    def setUp(self):
        self.command = [PBP_COMPLEXITY, "php"]

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
            "categories": {c: "off" for c in measure_js.CATEGORIES},
            "jsPlugins": [str(measure_js.PLUGIN)],
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
            score = int(measure_js.SCORE.search(diagnostic["message"]).group(1))
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


class ScriptCase(unittest.TestCase):
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

    def measure(self, *args: str, base: str = "HEAD", env: dict | None = None) -> str:
        env = {**os.environ, "HOST_CHECK_ACTIVE": "1", **(env or {})}
        result = subprocess.run([sys.executable, str(SCRIPTS / "measure_complexity.py"), base, *args,
                                 "--repo", str(self.repo)], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def write(self, name: str, text: str) -> None:
        (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / name).write_text(textwrap.dedent(text))


class MeasureScript(ScriptCase):

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

    @unittest.skipUnless(guard_oracle.GODOT_GUARD, guard_oracle.MISSING)
    @unittest.skipUnless(GDSCRIPT_SCORER, NO_GDSCRIPT_SCORER)
    def test_godot_guard_limits_and_baseline_tag_gdscript(self):
        self.write(".godot-guard.yml", "limits:\n  cognitive: 2\n")
        self.write(".godot-guard-baseline.json", '{"version": 1, "cognitive-complexity": {"old.gd::pick": 3}}')
        self.write("old.gd", PICK)
        self.write("new.gd", PICK)
        output = self.measure(env={"PBP_GODOT_GUARD": guard_oracle.GODOT_GUARD})
        self.assertIn(".godot-guard.yml: repository cognitive max 2, cyclomatic max 16", output)
        self.assertIn("old.gd:4 pick: cognitive 3 > 2 [lint passes]", output)
        self.assertIn("new.gd:4 pick: cognitive 3 > 2 [lint: error]", output)


TAGS = {"error": "[lint: error]", "warning": "[lint: warning]", "passes": "[lint passes]",
        "unchecked": "[not lint-checked]"}
SUMMARY = re.compile(r"^  (\S+):(\d+) \S+: .* (\[[^\]]+\])$", re.M)
LAMBDA = """\
    extends Node

    func outer() -> void:
    \tvar callable = func{name}(a: bool, b: bool):
    \t\tif a:
    \t\t\tif b:
    \t\t\t\treturn 1
    \t\treturn 0
    \tcallable.call(true, true)
    """
ACCESSOR = """\
    extends Node
    var health: int:
    \tset(value):
    \t\tif value > 0:
    \t\t\tif value > 1:
    \t\t\t\thealth = value
    \tget:
    \t\treturn health
    """
INNER = """\
    extends Node

    class Inner:
    \tfunc pick(a: bool, b: bool) -> int:
    \t\tif a:
    \t\t\tif b:
    \t\t\t\treturn 1
    \t\treturn 0
    """


def baseline(**rules: dict) -> str:
    return json.dumps({"version": 1, **{rule.replace("_", "-"): entries for rule, entries in rules.items()}})


@unittest.skipUnless(guard_oracle.GODOT_GUARD, guard_oracle.MISSING)
@unittest.skipUnless(GDSCRIPT_SCORER, NO_GDSCRIPT_SCORER)
class GodotGuardVerdicts(ScriptCase):
    """Each GDScript tag equals what `godot-guard check` decides, in the cases a re-implementation got wrong."""

    def tags(self, *args: str, base: str = "HEAD") -> dict[tuple[str, int], str]:
        output = self.measure(*args, base=base, env={"PBP_GODOT_GUARD": guard_oracle.GODOT_GUARD})
        return {(path, int(line)): tag for path, line, tag in SUMMARY.findall(output)}

    def decided(self, keys) -> dict[tuple[str, int], str]:
        rules = ("cognitive-complexity", "cyclomatic-complexity")
        return {(path, line): TAGS[guard_oracle.verdict(self.repo, path, line, rules)] for path, line in keys}

    def assert_tags(self, expected: dict[tuple[str, int], str]) -> None:
        self.assertEqual(self.tags(), expected)
        self.assertEqual(self.decided(expected), expected)

    def test_a_loose_baseline_entry_fails(self):
        self.write(".godot-guard.yml", "limits: {cognitive: 2}\n")
        self.write(".godot-guard-baseline.json", baseline(cognitive_complexity={"unit.gd::pick": 4}))
        self.write("unit.gd", PICK)
        self.assert_tags({("unit.gd", 4): "[lint: error]"})

    def test_an_exact_baseline_entry_passes(self):
        self.write(".godot-guard.yml", "limits: {cognitive: 2}\n")
        self.write(".godot-guard-baseline.json", baseline(cognitive_complexity={"unit.gd::pick": 3}))
        self.write("unit.gd", PICK)
        self.assert_tags({("unit.gd", 4): "[lint passes]"})

    def test_excluded_hidden_and_unscanned_scripts_are_not_lint_checked(self):
        self.write(".godot-guard.yml", "paths: [game, vendor, .hidden]\nexclude: [vendor/**]\nlimits: {cognitive: 2}\n")
        for name in ("game/unit.gd", "vendor/unit.gd", ".hidden/unit.gd", "tools/unit.gd"):
            self.write(name, PICK)
        self.assert_tags({("game/unit.gd", 4): "[lint: error]", ("vendor/unit.gd", 4): "[not lint-checked]",
                          (".hidden/unit.gd", 4): "[not lint-checked]", ("tools/unit.gd", 4): "[not lint-checked]"})

    def test_rule_levels_come_from_godot_guard(self):
        self.write("unit.gd", PICK)
        levels = {
            "rules: {cognitive-complexity: null}\n": "[lint: error]",
            'rules:\n  "cognitive-complexity": off\n': "[lint passes]",
            "rules: {cognitive-complexity: warn}\n": "[lint: warning]",
            "rules: {cognitive-complexity: off}\n": "[lint passes]",
        }
        for rules, tag in levels.items():
            with self.subTest(rules=rules):
                self.write(".godot-guard.yml", "limits: {cognitive: 2}\n" + rules)
                self.assert_tags({("unit.gd", 4): tag})

    def test_lambdas_accessors_and_repeated_names_are_matched_by_line(self):
        self.write(".godot-guard.yml", "limits: {cognitive: 2, cyclomatic: 2}\n")
        self.write(".godot-guard-baseline.json", baseline(
            cognitive_complexity={"named.gd::outer": 5, "inner.gd::Inner.pick": 3},
            cyclomatic_complexity={"named.gd::outer.named": 3, "inner.gd::Inner.pick": 3}))
        self.write("named.gd", LAMBDA.format(name=" named"))
        self.write("anonymous.gd", LAMBDA.format(name=""))
        self.write("accessor.gd", ACCESSOR)
        pick = textwrap.dedent(PICK)
        self.write("repeated.gd", pick + "\n\n" + pick.split("\n\n\n", 1)[1])
        self.write("inner.gd", INNER)
        self.assert_tags({
            ("accessor.gd", 3): "[lint: error]",
            ("anonymous.gd", 3): "[lint: error]",
            ("anonymous.gd", 4): "[lint: error]",
            ("inner.gd", 4): "[lint passes]",
            ("named.gd", 3): "[lint passes]",
            ("named.gd", 4): "[lint passes]",
            ("repeated.gd", 4): "[lint: error]",
            ("repeated.gd", 11): "[lint: error]",
        })

    def test_a_revision_is_judged_by_its_own_config_and_baseline_in_a_temporary_tree(self):
        self.write(".godot-guard.yml", "limits: {cognitive: 2}\n")
        self.write(".godot-guard-baseline.json", baseline(cognitive_complexity={"unit.gd::pick": 3}))
        self.write("unit.gd", PICK)
        self.git("add", ".")
        self.git("commit", "-qm", "guarded")
        (self.repo / ".godot-guard-baseline.json").unlink()
        self.write(".godot-guard.yml", "limits: {cognitive: 1}\n")
        self.assertEqual(self.tags("HEAD", base="HEAD~1"), {("unit.gd", 4): "[lint passes]"})
        status = subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain"], capture_output=True, text=True)
        self.assertEqual(status.stdout, " D .godot-guard-baseline.json\n M .godot-guard.yml\n")
        self.git("checkout", "--", ".")
        self.assertEqual(self.decided([("unit.gd", 4)]), {("unit.gd", 4): "[lint passes]"})

    def old_guard(self) -> Path:
        bin_dir = Path(tempfile.mkdtemp(prefix="pbp-old-guard-"))
        self.addCleanup(shutil.rmtree, bin_dir)
        old = bin_dir / "godot-guard"
        old.write_text("#!/bin/sh\necho 'godot-guard 0.1.0'\nexit 2\n")
        old.chmod(0o755)
        self.write(".godot-guard.yml", "limits: {cognitive: 2}\n")
        self.write("unit.gd", PICK)
        return old

    def test_an_old_godot_guard_leaves_gdscript_unchecked_but_scored(self):
        old = self.old_guard()
        scorer_dir = Path(tempfile.mkdtemp(prefix="pbp-scorer-"))
        self.addCleanup(shutil.rmtree, scorer_dir)
        (scorer_dir / "godot-guard").symlink_to(GDSCRIPT_SCORER)
        output = self.measure("--cognitive-limit", "2",
                              env={"PBP_GODOT_GUARD": str(old), "PATH": f"{scorer_dir}:/usr/bin:/bin"})
        self.assertIn(f".godot-guard.yml: found godot-guard 0.1 at {old}", output)
        self.assertIn("tagging needs godot-guard 0.2+ (`check --json`)", output)
        self.assertIn("unit.gd:4 pick: cognitive 3 > 2 [not lint-checked]", output)

    def test_without_a_scoring_godot_guard_gdscript_is_not_measured(self):
        old = self.old_guard()
        for guard in (str(old), ""):
            with self.subTest(guard=guard):
                output = self.measure("--cognitive-limit", "2", env={"PBP_GODOT_GUARD": guard, "PATH": "/usr/bin:/bin"})
                self.assertIn("GDScript: no godot-guard with `complexity --json`", output)
                self.assertIn("1 file(s) not measured; run fleet's `bin/sync --apply`", output)
                self.assertNotIn("unit.gd:4 pick", output)

if __name__ == "__main__":
    unittest.main()
