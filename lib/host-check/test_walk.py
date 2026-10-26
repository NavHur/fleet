import os
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
        self.assertEqual(words("pnpm lint && pnpm test | tee log; git status"),
                         [["pnpm", "lint"], ["pnpm", "test"], ["tee", "log"], ["git", "status"]])

    def test_a_cd_moves_the_commands_after_it(self):
        found = list(leaves("cd apps/web && pnpm test; cd .. && git status", "/repo"))
        self.assertEqual([(leaf.words[0], leaf.cwd) for leaf in found],
                         [("cd", "/repo"), ("pnpm", "/repo/apps/web"), ("cd", "/repo/apps/web"), ("git", "/repo/apps")])

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
        self.assertEqual(words("cat <<'EOF' > brief.md\nit's pnpm test\nEOF\n# pnpm build\npnpm lint"),
                         [["cat"], ["pnpm", "lint"]])


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
        for command in ("env -u FOO pnpm test", "timeout -s KILL 60 pnpm test", "setsid pnpm test",
                        "timeout 60 pnpm test", "timeout --kill-after=10s 10m pnpm test", "nice -n 5 pnpm test",
                        "nohup pnpm test", "stdbuf -o L pnpm test", "time -p pnpm test", "exec -a x pnpm test",
                        "command pnpm test", "env -i PATH=/bin CI=1 pnpm test", "env -- pnpm test",
                        "nice timeout 60 env FOO=1 pnpm test"):
            with self.subTest(command):
                self.assertEqual(words(command), [["pnpm", "test"]])

    def test_the_walk_records_each_wrapper_it_passes(self):
        leaf = only("host-check timeout 60 vitest")
        self.assertEqual(leaf.via, (("wrapper", "host-check"), ("wrapper", "timeout")))

    def test_env_assignments_and_directory_reach_the_leaf(self):
        leaf = only("env -C sub FOO=1 vitest", "/repo")
        self.assertEqual((leaf.cwd, leaf.env), ("/repo/sub", {"FOO": "1"}))

    def test_a_wrapper_given_by_path_still_wraps(self):
        self.assertEqual(words("/Users/me/.local/bin/host-check pnpm lint"), [["pnpm", "lint"]])

    def test_command_v_looks_a_command_up_without_running_it(self):
        self.assertEqual(words("command -v vitest"), [["command", "-v", "vitest"]])

    def test_bg_job_start_runs_its_command(self):
        leaf = only("bg-job start gates -- host-check pnpm check")
        self.assertEqual((leaf.words, leaf.via), (["pnpm", "check"], (("wrapper", "bg-job"), ("wrapper", "host-check"))))
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


if __name__ == "__main__":
    unittest.main()
