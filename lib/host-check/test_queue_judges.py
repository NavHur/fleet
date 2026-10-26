import tempfile
import unittest

from guard import needs_queue, starts_dev
from jobclass import job_class

# (command, needs the queue, job class), judged in a directory with no package.json.
AGREEMENT = [
    ("vitest", True, "heavy"),
    ("env -u FOO pnpm test", True, "heavy"),
    ("timeout -s KILL 60 vitest", True, "heavy"),
    ("timeout 60 vitest", True, "heavy"),
    ("setsid vitest", True, "heavy"),
    ("stdbuf -oL pnpm build", True, "build"),
    ("env -C sub nice -n 5 vitest run src/a.test.ts", True, "light"),
    ("bash -lc 'setsid pnpm test'", True, "heavy"),
    ("bg-job start t -- timeout -k 5 60 vitest", True, "heavy"),
    ("uv run --with x pnpm lint", True, "light"),
    ("yarn node --test", True, "heavy"),
    ("pnpm run node --test", True, "heavy"),
    ("pnpm node --test x.test.js", True, "light"),
    ("command -v vitest", False, "none"),
    ("echo pnpm test", False, "none"),
    # The catalogue's rows, which the guard and the queue once kept apart.
    ("godot-guard gate", True, "heavy"),
    ("godot-guard gate --fast --staged", True, "light"),
    ("godot-guard check", True, "light"),
    ("godot-guard format", False, "none"),
    ("tsrs", True, "light"),
    ("svelte-check --tsconfig tsconfig.json", True, "light"),
    ("oxfmt --check .", True, "light"),
    ("tsx scripts/a11y-pages.ts", True, "light"),
    ("playwright screenshot https://x", True, "light"),
    ("next lint", True, "light"),
    ("pnpm fmt", True, "light"),
    ("make bench", True, "light"),
    ("pnpm exec eslint .", True, "light"),
    ("tsup", True, "build"),
    ("tsup src/index.ts --format esm", True, "build"),
    ("tsup --watch", False, "none"),
    ("pnpm add -D tsup", False, "none"),
    ("hyperfine 'node a.js'", True, "heavy"),
    # Background commands run side by side, so the job is a fan-out; `wait` itself runs nothing.
    ("wait", False, "none"),
    ("pnpm lint & pnpm typecheck & wait", True, "heavy"),
    ("sleep 1 & wait", False, "heavy"),
    ("vitest --help", False, "none"),
    ("ls", False, "none"),
]
# Leaves the walk cannot see: heavy for the queue, but the guard never asks for the queue on a guess.
OPAQUE = [("eval \"$CMD\"", "heavy"), ("bash -s", "heavy"), ("$RUN", "heavy")]


class QueueJudgesAgreeTests(unittest.TestCase):
    """The guard and the job classes judge the same leaves, so every wrapper spelling reaches both."""

    def test_both_judges_see_the_same_command(self):
        with tempfile.TemporaryDirectory(prefix="queue-judges-") as cwd:
            for command, queued, job in AGREEMENT:
                with self.subTest(command=command):
                    self.assertEqual((needs_queue(command, cwd), job_class(command, cwd)), (queued, job))

    def test_the_guard_queues_what_the_catalogue_classes(self):
        with tempfile.TemporaryDirectory(prefix="queue-judges-") as cwd:
            for command, _, _ in AGREEMENT:
                if "&" in command:
                    continue  # the fan-out is the job's, not a leaf's
                with self.subTest(command=command):
                    self.assertEqual(needs_queue(command, cwd), job_class(command, cwd) != "none")

    def test_opaque_leaves_are_heavy_but_never_queued(self):
        for command, job in OPAQUE:
            with self.subTest(command=command):
                self.assertEqual((needs_queue(command, "/"), job_class(command, "/")), (False, job))

    def test_a_gate_that_queues_itself_is_left_to_queue(self):
        self.assertEqual((needs_queue("njhomes-page-gates a.tsx", "/"), job_class("njhomes-page-gates a.tsx", "/")),
                         (False, "build"))


class DevServerTests(unittest.TestCase):
    def test_a11y_base_url_counts_only_where_the_gate_sees_it(self):
        for command, dev in [
            ("A11Y_BASE_URL=http://localhost:3000 tsx scripts/a11y-pages.ts", False),
            ("export A11Y_BASE_URL=http://localhost:3000; tsx scripts/a11y-pages.ts", False),
            ("A11Y_BASE_URL=http://localhost:3000 bash -c 'tsx scripts/a11y-pages.ts'", False),
            ("echo A11Y_BASE_URL=x; tsx scripts/a11y-pages.ts", True),
            ("setsid env -u X tsx scripts/a11y-pages.ts", True),
        ]:
            with self.subTest(command=command):
                self.assertEqual(starts_dev(command, "/"), dev)


if __name__ == "__main__":
    unittest.main()
