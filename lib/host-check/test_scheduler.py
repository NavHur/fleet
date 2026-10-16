"""Exercise bin/host-check with isolated lock files, a test config, and real processes."""
import fcntl
import json
import os
from pathlib import Path
import platform
import select
import signal
import subprocess
import tempfile
import unittest


WRAPPER = Path(__file__).resolve().parent.parent.parent / "bin" / "host-check"
SLOTS = 6
LINUX_SLICE = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True).returncode == 0 \
    if platform.system() == "Linux" else False
HOLD = "import sys; print('READY', flush=True); sys.stdin.readline()"


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="host-check-test-")
        self.root = Path(self.temp.name)
        self.queue = self.root / "queue"
        self.queue.mkdir()
        self.wrapper = WRAPPER
        config = self.root / "host.json"
        config.write_text(json.dumps({
            "slots": SLOTS, "heavy_slots": 3, "build_slots": 2, "vitest_max_workers": 5, "nice": 0,
            "slice": "builds.slice" if LINUX_SLICE else None,
            "qos_clamp": "utility" if platform.system() == "Darwin" else None,
        }))
        self.env = dict(os.environ, HOST_CHECK_QUEUE_DIR=str(self.queue), HOST_CHECK_CONFIG=str(config))
        self.env.pop("HOST_CHECK_ACTIVE", None)
        self.env.pop("VITEST_MAX_WORKERS", None)
        self.processes = []
        # One directory per global slot plus one that must wait.
        self.dirs = [self.root / f"w{index}" for index in range(SLOTS + 1)]
        for directory in self.dirs:
            directory.mkdir()
        self.a, self.b = self.dirs[:2]

    def tearDown(self):
        for process in self.processes:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        self.temp.cleanup()

    def launch(self, cwd, *command):
        process = subprocess.Popen(
            [str(self.wrapper), *(command or ("python3", "-c", HOLD))],
            cwd=cwd, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.processes.append(process)
        return process

    def ready(self, process):
        self.assertTrue(select.select([process.stdout], [], [], 5)[0], "job never started")
        self.assertEqual(process.stdout.readline().strip(), "READY")

    def waiting(self, process):
        self.assertFalse(select.select([process.stdout], [], [], 0.3)[0], "job started too soon")
        self.assertIsNone(process.poll())

    def finish(self, process):
        process.stdin.write("done\n")
        process.stdin.flush()
        self.assertEqual(process.wait(timeout=5), 0)

    def test_all_slots_and_any_slot_release(self):
        running = [self.launch(cwd) for cwd in self.dirs[:SLOTS]]
        for process in running:
            self.ready(process)
        extra = self.launch(self.dirs[SLOTS])
        self.waiting(extra)
        self.finish(running[1])
        self.ready(extra)
        self.assertIsNone(running[0].poll())
        for process in (running[0], *running[2:], extra):
            self.finish(process)

    @unittest.skipUnless(LINUX_SLICE, "needs a Linux user systemd bus")
    def test_job_runs_in_builds_slice(self):
        process = self.launch(self.a, "cat", "/proc/self/cgroup")
        stdout, _ = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0)
        self.assertIn("/builds.slice/", stdout)

    @unittest.skipUnless(platform.system() == "Darwin", "macOS only")
    def test_job_and_children_run_under_utility_clamp(self):
        # Base priority 31 is the default band; the utility clamp lowers it to 20.
        process = self.launch(self.a, "sh", "-c", "sh -c 'ps -o pri= -p $$'")
        stdout, _ = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0)
        self.assertLessEqual(int(stdout.strip()), 20)

    def test_same_worktree_subdirectory_and_symlink_share_lock(self):
        subprocess.run(["git", "init", "-q", str(self.a)], check=True)
        subdirectory = self.a / "sub"
        subdirectory.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(subdirectory, target_is_directory=True)
        first = self.launch(self.a)
        self.ready(first)
        same = self.launch(alias)
        self.waiting(same)
        other = self.launch(self.b)
        self.ready(other)
        self.finish(first)
        self.ready(same)
        self.finish(same)
        self.finish(other)

    def test_git_worktrees_have_independent_locks(self):
        subprocess.run(["git", "init", "-q", str(self.a)], check=True)
        # An unborn worktree needs no commits or repository fixtures.
        subprocess.run(["git", "-C", str(self.a), "worktree", "add", "--orphan",
                        "-b", "test-linked", str(self.root / "linked")],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        first = self.launch(self.a)
        second = self.launch(self.root / "linked")
        self.ready(first)
        self.ready(second)
        self.finish(first)
        self.finish(second)

    def test_legacy_exclusive_lock_blocks_new_jobs(self):
        with (self.queue / "lock").open("w") as legacy:
            fcntl.flock(legacy, fcntl.LOCK_EX)
            first = self.launch(self.a)
            self.waiting(first)
            fcntl.flock(legacy, fcntl.LOCK_UN)
            self.ready(first)
            self.finish(first)

    def test_arguments_environment_priority_and_exit_status(self):
        args = ["space here", "$(touch not-executed)", "*", "", "a;b"]
        code = "import os,sys,json; print(json.dumps([sys.argv[1:], os.getenv('VITEST_MAX_WORKERS'), os.getpriority(os.PRIO_PROCESS,0)])); sys.exit(23)"
        process = self.launch(self.a, "python3", "-c", code, *args)
        stdout, _ = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 23)
        values = json.loads(stdout)
        self.assertEqual(values[:2], [args, "5"])
        # Jobs run unniced in builds.slice or under the macOS clamp; Linux
        # without a user bus falls back to nice 10.
        unniced = LINUX_SLICE or platform.system() == "Darwin"
        self.assertGreaterEqual(values[2], 0 if unniced else 10)
        self.assertFalse((self.a / "not-executed").exists())
        self.env["VITEST_MAX_WORKERS"] = "1"
        process = self.launch(self.a, "printenv", "VITEST_MAX_WORKERS")
        self.assertEqual(process.communicate(timeout=5)[0].strip(), "1")

    def test_finished_jobs_are_logged(self):
        self.env["HOST_CHECK_LABEL"] = "pre-push"
        process = self.launch(self.a, "python3", "-c", "import sys; sys.exit(3)")
        process.communicate(timeout=5)
        self.assertEqual(process.returncode, 3)
        killed = self.launch(self.b, "bash", "-c", "kill -TERM $$")
        killed.communicate(timeout=5)
        self.assertEqual(killed.returncode, -signal.SIGTERM)
        records = [json.loads(line) for line in (self.queue / "jobs.jsonl").read_text().splitlines()]
        self.assertEqual([(r["label"], r["exit"]) for r in records], [("pre-push", 3), ("pre-push", -15)])
        first = records[0]
        self.assertEqual((first["class"], first["worktree"]), ("light", os.path.realpath(self.a)))
        self.assertIn("sys.exit(3)", first["command"])
        self.assertGreaterEqual(first["wait_s"], 0)
        self.assertGreaterEqual(first["run_s"], 0)

    def test_job_killed_by_sigkill_is_logged_and_wrapper_dies_by_it(self):
        process = self.launch(self.a, "bash", "-c", "kill -KILL $$")
        process.communicate(timeout=5)
        self.assertEqual(process.returncode, -signal.SIGKILL)
        records = [json.loads(line) for line in (self.queue / "jobs.jsonl").read_text().splitlines()]
        self.assertEqual([r["exit"] for r in records], [-signal.SIGKILL])

    def test_nested_wrapper_is_rejected(self):
        process = self.launch(self.a, str(self.wrapper), "true")
        _, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 64)
        self.assertIn("nested invocation refused", stderr)

    def test_termination_releases_slot(self):
        process = self.launch(self.a)
        self.ready(process)
        process.terminate()
        self.assertEqual(process.wait(timeout=5), -signal.SIGTERM)
        replacement = self.launch(self.a)
        self.ready(replacement)
        self.finish(replacement)

    def test_surviving_child_keeps_worktree_locked(self):
        survivor = self.launch(self.a, "bash", "-c", "sleep 2 & echo READY; wait")
        self.ready(survivor)
        survivor.terminate()
        survivor.wait(timeout=5)
        replacement = self.launch(self.a)
        self.waiting(replacement)
        self.ready(replacement)
        self.finish(replacement)


if __name__ == "__main__":
    unittest.main()
