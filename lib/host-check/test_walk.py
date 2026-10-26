import json
import os
from pathlib import Path
import shlex
import tempfile
import unittest

from walk import leaves


def words(command, cwd="/work"):
    return [leaf.words for leaf in leaves(command, cwd)]


def only(command, cwd="/work"):
    found = list(leaves(command, cwd))
    assert len(found) == 1, found
    return found[0]


class SequenceTests(unittest.TestCase):
    def test_each_simple_command_is_a_leaf(self):
        self.assertEqual(words("make lint && make test | tee log; git status"),
                         [["make", "lint"], ["make", "test"], ["tee", "log"], ["git", "status"]])

    def test_a_cd_moves_the_commands_after_it(self):
        found = list(leaves("cd apps/web && make test; cd .. && git status", "/repo"))
        self.assertEqual([(leaf.words[0], leaf.cwd) for leaf in found],
                         [("cd", "/repo"), ("make", "/repo/apps/web"), ("cd", "/repo/apps/web"), ("git", "/repo/apps")])

    def test_commands_inside_a_substitution_run_in_a_subshell(self):
        found = list(leaves('git commit -m "$(git log -1 --format=%s)"', "/work"))
        self.assertEqual([(leaf.words[:2], leaf.subshell) for leaf in found],
                         [(["git", "log"], True), (["git", "commit"], False)])

    def test_a_cd_inside_a_substitution_moves_nothing(self):
        self.assertEqual(list(leaves("x=$(cd /tmp && pwd); git status", "/repo"))[-1].cwd, "/repo")

    def test_keywords_and_prefix_assignments_are_not_the_command(self):
        leaf = only("if CI=1 FOO=bar vitest run")
        self.assertEqual(leaf.words, ["vitest", "run"])
        self.assertEqual(leaf.env, {"CI": "1", "FOO": "bar"})

    def test_a_leaf_sees_assignments_made_before_it(self):
        found = list(leaves("export A11Y_BASE_URL=http://localhost:3000; tsx scripts/a11y-pages.ts", "/work"))
        self.assertEqual(found[-1].env, {"A11Y_BASE_URL": "http://localhost:3000"})

    def test_a_command_word_stored_in_a_variable_is_expanded(self):
        self.assertEqual(words('G="git -C /tmp"; $G log')[-1], ["git", "-C", "/tmp", "log"])

    def test_redirections_are_dropped(self):
        self.assertEqual(words("vitest run > out.log 2>/dev/null"), [["vitest", "run"]])

    def test_comments_and_heredocs_are_not_commands(self):
        self.assertEqual(words("cat <<'EOF' > brief.md\nit's make test\nEOF\n# pnpm build\nmake lint"),
                         [["cat"], ["make", "lint"]])


class BackgroundTests(unittest.TestCase):
    def test_a_lone_ampersand_sends_a_command_to_the_background(self):
        found = list(leaves("claude -p hi & wait", "/work"))
        self.assertEqual([(leaf.words[0], leaf.background) for leaf in found], [("claude", True), ("wait", False)])

    def test_and_lists_pipes_and_descriptor_copies_stay_in_the_foreground(self):
        found = list(leaves("a && b |& c 2>&1 | d >&2; e &>log", "/work"))
        self.assertEqual([(leaf.words, leaf.background) for leaf in found],
                         [(["a"], False), (["b"], False), (["c"], False), (["d"], False), (["e"], False)])


class WrapperTests(unittest.TestCase):
    def test_wrappers_run_the_command_after_their_options(self):
        for command in ("env -u FOO make test", "timeout -s KILL 60 make test", "setsid make test",
                        "timeout 60 make test", "timeout --kill-after=10s 10m make test", "nice -n 5 make test",
                        "nohup make test", "stdbuf -o L make test", "time -p make test", "exec -a x make test",
                        "command make test", "env -i PATH=/bin CI=1 make test", "env -- make test",
                        "nice timeout 60 env FOO=1 make test"):
            with self.subTest(command):
                self.assertEqual(words(command), [["make", "test"]])

    def test_the_walk_records_each_wrapper_it_passes(self):
        leaf = only("host-check timeout 60 vitest")
        self.assertEqual(leaf.via, (("wrapper", "host-check"), ("wrapper", "timeout")))

    def test_env_assignments_and_directory_reach_the_leaf(self):
        leaf = only("env -C sub FOO=1 vitest", "/repo")
        self.assertEqual((leaf.cwd, leaf.env), ("/repo/sub", {"FOO": "1"}))

    def test_a_wrapper_given_by_path_still_wraps(self):
        self.assertEqual(words("/Users/me/.local/bin/host-check make lint"), [["make", "lint"]])

    def test_command_v_looks_a_command_up_without_running_it(self):
        self.assertEqual(words("command -v vitest"), [["command", "-v", "vitest"]])

    def test_bg_job_start_runs_its_command(self):
        leaf = only("bg-job start gates -- host-check make check")
        self.assertEqual((leaf.words, leaf.via), (["make", "check"], (("wrapper", "bg-job"), ("wrapper", "host-check"))))
        self.assertEqual(words("bg-job status gates"), [])

    def test_exec_runners_run_the_command_after_their_verb(self):
        for command, runner in (("uv run --with pytest-cov pytest -q", "uv run"), ("uvx pytest", "uvx"),
                                ("poetry run pytest", "poetry run"), ("pipenv run pytest", "pipenv run")):
            with self.subTest(command):
                leaf = only(command)
                self.assertEqual((leaf.words[0], leaf.via), ("pytest", (("runner", runner),)))

    def test_a_runner_verb_that_runs_nothing_is_the_leaf(self):
        self.assertEqual(words("uv pip install x"), [["uv", "pip", "install", "x"]])

    def test_uv_run_directory_moves_the_leaf(self):
        self.assertEqual(only("uv run --directory api pytest", "/repo").cwd, "/repo/api")


class ShellTests(unittest.TestCase):
    def test_a_shell_string_runs_its_commands_where_the_shell_runs(self):
        leaf = list(leaves("bash -lc 'cd sub && make test'", "/repo"))[-1]
        self.assertEqual((leaf.words, leaf.cwd, leaf.via), (["make", "test"], "/repo/sub", (("shell", "bash"),)))

    def test_a_shell_string_it_cannot_parse_is_an_error(self):
        with self.assertRaises(ValueError):
            list(leaves("bash -lc \"echo $'it\\'s'; gh pr merge 1 --squash\"", "/work"))

    def test_a_shell_reading_stdin_hides_its_commands(self):
        self.assertEqual(list(leaves("curl -s x | bash", "/work"))[-1].opaque, "stdin")

    def test_a_shell_that_only_parses_or_answers_help_runs_nothing(self):
        for command in ("bash -n gates.sh", "bash --version"):
            with self.subTest(command):
                leaf = only(command)
                self.assertEqual((leaf.words[0], leaf.opaque, leaf.expanded), ("bash", None, False))

    def test_eval_and_an_unknown_variable_hide_their_command(self):
        self.assertEqual([leaf.opaque for leaf in leaves('eval "$CMD"; $RUN test', "/work")], ["eval", "variable"])

    def test_shell_strings_stop_at_the_depth_limit(self):
        command = "make lint"
        for _ in range(7):
            command = "bash -c " + shlex.quote(command)
        self.assertEqual(only(command).opaque, "too-deep")


class FileTests(unittest.TestCase):
    """Script files and package scripts on disk."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="walk-test-")
        cls.root = Path(os.path.realpath(cls.temp.name))
        write(cls.root / "gates.sh", "#!/usr/bin/env bash\ncd web\noxlint .\n", 0o755)
        write(cls.root / "stored.sh", 'test_cmd=${TEST_CMD:-pnpm exec vitest run}\nmsg="hello there"\n$test_cmd\n')
        write(cls.root / "broken.sh", "echo 'unclosed\n")
        write(cls.root / "twice.sh", "./gates.sh\n./gates.sh\n")
        write(cls.root / "package.json", json.dumps({"scripts": {
            "test": "vitest run", "loop": "pnpm loop", "broken": "echo 'unclosed"}}))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def found(self, command):
        return list(leaves(command, str(self.root)))

    def test_a_script_run_by_path_is_followed_into(self):
        script, lint = [leaf for leaf in self.found("./gates.sh") if leaf.words[0] != "cd"]
        self.assertEqual((script.words, script.expanded), (["./gates.sh"], True))
        self.assertEqual((lint.words, lint.cwd, lint.via),
                         (["oxlint", "."], str(self.root / "web"), (("script", str(self.root / "gates.sh")),)))

    def test_a_script_given_to_a_shell_or_source_is_followed_into(self):
        for command in ("bash gates.sh", "source gates.sh", ". ./gates.sh"):
            with self.subTest(command):
                self.assertEqual(self.found(command)[-1].words, ["oxlint", "."])

    def test_a_script_asked_for_help_is_not_followed(self):
        self.assertEqual([leaf.expanded for leaf in self.found("./gates.sh --help")], [False])

    def test_a_script_runs_the_commands_it_stores(self):
        stored = [leaf.words for leaf in self.found("bash stored.sh")]
        self.assertIn(["pnpm", "exec", "vitest", "run"], stored)
        self.assertNotIn(["hello", "there"], stored)

    def test_a_script_that_cannot_be_read_or_parsed_is_opaque(self):
        for command, reason in (("bash missing.sh", "unreadable"), ("bash broken.sh", "unparseable")):
            with self.subTest(command):
                leaf = self.found(command)[-1]
                self.assertEqual((leaf.words, leaf.opaque), (command.split(), reason))

    def test_a_script_run_twice_runs_its_commands_twice(self):
        self.assertEqual([leaf.words for leaf in self.found("bash twice.sh")].count(["oxlint", "."]), 2)

    def test_a_package_script_runs_its_body_in_its_package(self):
        runner, body = self.found("pnpm test")
        self.assertEqual((runner.words, runner.expanded), (["pnpm", "test"], True))
        self.assertEqual((body.words, body.cwd, body.via), (["vitest", "run"], str(self.root), (("package", str(self.root)),)))

    def test_package_executables_are_followed_into(self):
        for command in ("npx vitest run", "pnpm exec vitest run", "pnpm vitest run"):
            with self.subTest(command):
                self.assertEqual(self.found(command)[-1].words, ["vitest", "run"])

    def test_a_bin_a_package_manager_runs_by_name_is_followed_into(self):
        for command, bin_words in (("yarn node --test", ["node", "--test"]),
                                   ("pnpm run node --test", ["node", "--test"]),
                                   ("pnpm node --test x.test.js", ["node", "--test", "x.test.js"])):
            with self.subTest(command):
                runner, bin_leaf = self.found(command)
                self.assertEqual((runner.words, runner.expanded), (command.split(), True))
                self.assertEqual((bin_leaf.words, bin_leaf.via), (bin_words, (("package", str(self.root)),)))

    def test_a_package_script_that_runs_itself_stops_at_the_depth_limit(self):
        found = self.found("pnpm loop")
        self.assertEqual(len(found), 7)
        self.assertFalse(found[-1].expanded)

    def test_a_package_script_it_cannot_parse_is_opaque(self):
        self.assertEqual([(leaf.words, leaf.opaque) for leaf in self.found("pnpm broken")][-1],
                         (["pnpm", "broken"], "unparseable"))


def write(path, text, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mode:
        path.chmod(mode)


if __name__ == "__main__":
    unittest.main()
