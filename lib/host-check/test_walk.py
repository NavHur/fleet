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


if __name__ == "__main__":
    unittest.main()
