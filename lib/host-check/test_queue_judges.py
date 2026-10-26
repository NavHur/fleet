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
    ("command -v vitest", False, "light"),
    ("echo pnpm test", False, "light"),
]


class QueueJudgesAgreeTests(unittest.TestCase):
    """The guard and the job classes judge the same leaves, so every wrapper spelling reaches both."""

    def test_both_judges_see_the_same_command(self):
        with tempfile.TemporaryDirectory(prefix="queue-judges-") as cwd:
            for command, queued, job in AGREEMENT:
                with self.subTest(command=command):
                    self.assertEqual((needs_queue(command, cwd), job_class(command, cwd)), (queued, job))


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
