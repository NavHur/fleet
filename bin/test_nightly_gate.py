import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

loader = importlib.machinery.SourceFileLoader("nightly_gate", str(Path(__file__).parent / "nightly-gate"))
nightly_gate = importlib.util.module_from_spec(importlib.util.spec_from_loader("nightly_gate", loader))
loader.exec_module(nightly_gate)

# Stands in for host-check: drops the `timeout --kill-after=30s Nm` prefix and runs the rest.
HOST_CHECK = '#!/bin/sh\nshift 3\nexec "$@"\n'
# Stands in for gh: logs each call, and fails while $GH_DOWN exists.
GH = '#!/bin/sh\necho "$@" >> "$GH_CALLS"\nif [ -e "$GH_DOWN" ]; then echo "gh is down" >&2; exit 1; fi\n'


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


class Pure(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(nightly_gate.classify([0]), "pass")
        self.assertEqual(nightly_gate.classify([1, 0]), "flaky")
        self.assertEqual(nightly_gate.classify([1, 1]), "fail")
        self.assertEqual(nightly_gate.classify([1, 124]), "timeout")

    def test_needs_fix(self):
        self.assertFalse(nightly_gate.needs_fix({"status": "pass", "ack": None}))
        self.assertTrue(nightly_gate.needs_fix({"status": "fail", "ack": None}))
        self.assertTrue(nightly_gate.needs_fix({"status": "error", "ack": None}))
        self.assertFalse(nightly_gate.needs_fix({"status": "fail", "ack": {"thread": "t"}}))
        self.assertTrue(nightly_gate.needs_fix({"status": "error", "ack": {"thread": "t"}}))
        self.assertFalse(nightly_gate.needs_fix({"status": "flaky", "flakyStreak": 2, "ack": None}))
        self.assertTrue(nightly_gate.needs_fix({"status": "flaky", "flakyStreak": 3, "ack": None}))

    def test_flaky_streak(self):
        self.assertEqual(nightly_gate.flaky_streak(None, "flaky"), 1)
        self.assertEqual(nightly_gate.flaky_streak({"status": "flaky", "flakyStreak": 2}, "flaky"), 3)
        self.assertEqual(nightly_gate.flaky_streak({"status": "fail", "flakyStreak": 0}, "flaky"), 1)
        self.assertEqual(nightly_gate.flaky_streak({"status": "flaky", "flakyStreak": 2}, "pass"), 0)


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        origin = self.tmp / "origin"
        origin.mkdir()
        git(origin, "init", "-q", "-b", "main")
        (origin / "README").write_text("one\n")
        git(origin, "add", ".")
        git(origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one")
        self.origin = origin
        git(self.tmp, "clone", "-q", str(origin), "clone")
        stub = self.tmp / "host-check"
        stub.write_text(HOST_CHECK)
        stub.chmod(0o755)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text(GH)
        (bin_dir / "gh").chmod(0o755)
        self.gh_calls = self.tmp / "gh-calls"
        self.gh_down = self.tmp / "gh-down"
        self.config = self.tmp / "nightly.json"
        self.patches = [mock.patch.object(nightly_gate, "ROOT", self.tmp / "state"),
                        mock.patch.object(nightly_gate, "CONFIG", self.config),
                        mock.patch.object(nightly_gate, "HOST_CHECK", str(stub)),
                        mock.patch.object(nightly_gate, "wake", return_value=0),
                        mock.patch.dict(os.environ, {"PATH": f"{bin_dir}:{os.environ['PATH']}",
                                                     "GH_CALLS": str(self.gh_calls), "GH_DOWN": str(self.gh_down)})]
        for patch in self.patches:
            patch.start()
        self.wake = nightly_gate.wake

    def tearDown(self):
        for patch in self.patches:
            patch.stop()

    def configure(self, suite, clone=None):
        repo = {"clone": str(clone or self.tmp / "clone"), "suite": suite, "github": "o/demo"}
        self.config.write_text(json.dumps({"repos": {"demo": repo}}))

    def commit(self, text):
        (self.origin / "README").write_text(text)
        git(self.origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", text)

    def run_gate(self, *args):
        with mock.patch("sys.stdout"):
            return nightly_gate.main(["run", *args])

    def test_pass_then_skip_until_main_moves(self):
        marker = self.tmp / "runs"
        self.configure(f"test -f README && test ! -e .untracked && echo x >> {marker}")
        self.assertEqual(self.run_gate(), 0)
        result = nightly_gate.latest("demo")
        self.assertEqual(result["status"], "pass")
        self.assertFalse((self.tmp / "state" / "demo" / "checkout").exists())

        self.run_gate()
        self.assertEqual(marker.read_text().count("x"), 1)
        self.run_gate("--force")
        self.assertEqual(marker.read_text().count("x"), 2)

        self.commit("two\n")
        self.run_gate()
        self.assertEqual(marker.read_text().count("x"), 3)
        self.assertNotEqual(nightly_gate.latest("demo")["sha"], result["sha"])
        self.wake.assert_not_called()

    def test_checkout_has_no_untracked_files_from_the_clone(self):
        (self.tmp / "clone" / "cache.tmp").write_text("local only")
        self.configure("test ! -e cache.tmp")
        self.run_gate()
        self.assertEqual(nightly_gate.latest("demo")["status"], "pass")

    def test_failure_wakes_the_fix_task_until_acked(self):
        self.configure("echo broken; exit 3")
        self.run_gate()
        result = nightly_gate.latest("demo")
        self.assertEqual((result["status"], result["exits"]), ("fail", [3, 3]))
        self.assertIn("broken", result["tail"])
        self.wake.assert_called_once_with("demo")

        self.assertEqual(nightly_gate.main(["ack", "demo", result["sha"], "thread-1"]), 0)
        self.assertFalse(nightly_gate.needs_fix(nightly_gate.latest("demo")))
        self.assertEqual(nightly_gate.main(["ack", "demo", "0" * 40, "thread-1"]), 1)

    def test_second_attempt_passing_is_flaky(self):
        marker = self.tmp / "failed-once"
        self.configure(f"if [ -e {marker} ]; then exit 0; fi; touch {marker}; exit 1")
        self.run_gate()
        result = nightly_gate.latest("demo")
        self.assertEqual((result["status"], result["flakyStreak"]), ("flaky", 1))
        self.wake.assert_not_called()

    def test_unreachable_origin_is_an_error(self):
        git(self.tmp / "clone", "remote", "set-url", "origin", str(self.tmp / "missing"))
        self.configure("true")
        self.run_gate()
        result = nightly_gate.latest("demo")
        self.assertEqual(result["status"], "error")
        self.assertIn("fetch failed", result["error"])
        self.wake.assert_called_once_with("demo")

    def test_failed_wake_fails_the_run(self):
        self.configure("exit 3")
        self.wake.return_value = 1
        self.assertEqual(self.run_gate(), 1)

    def test_unposted_status_is_posted_again_without_rerunning(self):
        marker = self.tmp / "runs"
        self.configure(f"echo x >> {marker}")
        self.gh_down.touch()
        with mock.patch("sys.stderr"):
            self.run_gate()
        self.assertFalse(nightly_gate.latest("demo")["posted"])

        self.gh_down.unlink()
        self.run_gate()
        self.assertTrue(nightly_gate.latest("demo")["posted"])
        self.run_gate()
        self.assertEqual(marker.read_text().count("x"), 1)
        self.assertEqual(len(self.gh_calls.read_text().splitlines()), 2)

    def test_unposted_status_is_posted_after_main_moves(self):
        marker = self.tmp / "runs"
        self.configure(f"echo x >> {marker}")
        self.gh_down.touch()
        with mock.patch("sys.stderr"):
            self.run_gate()
            first = nightly_gate.latest("demo")["sha"]
            self.commit("two\n")
            self.run_gate()
        second = nightly_gate.latest("demo")["sha"]

        self.gh_down.unlink()
        self.run_gate()
        self.assertTrue(nightly_gate.completed("demo", first)["posted"])
        self.assertEqual(nightly_gate.latest("demo")["sha"], second)
        self.assertTrue(nightly_gate.latest("demo")["posted"])
        self.assertEqual(marker.read_text().count("x"), 2)

    def test_main_back_at_an_acked_failure_after_a_pass_wakes_again(self):
        self.configure("grep -q two README")
        self.run_gate()
        first = nightly_gate.latest("demo")["sha"]
        nightly_gate.main(["ack", "demo", first, "thread-1"])
        self.commit("two\n")
        self.run_gate()
        self.assertEqual(nightly_gate.latest("demo")["status"], "pass")

        git(self.origin, "reset", "-q", "--hard", first)
        self.run_gate()
        result = nightly_gate.latest("demo")
        self.assertEqual((result["sha"], result["ack"]), (first, None))
        self.assertEqual(self.wake.call_count, 2)

    def test_ack_survives_a_crash_before_the_sha_result_is_written(self):
        self.configure("exit 3")
        self.run_gate()
        sha = nightly_gate.latest("demo")["sha"]
        write = nightly_gate.write

        def crash_after_latest(path, data):
            if path.name != "latest.json":
                raise OSError("crash")
            write(path, data)

        with mock.patch.object(nightly_gate, "write", side_effect=crash_after_latest), self.assertRaises(OSError):
            nightly_gate.main(["ack", "demo", sha, "thread-1"])
        self.run_gate()
        self.assertEqual(nightly_gate.latest("demo")["ack"]["thread"], "thread-1")
        self.wake.assert_called_once_with("demo")

    def crash_before_the_sha_result(self, marker):
        self.configure(f"echo x >> {marker}")
        write = nightly_gate.write

        def crash_after_latest(path, data):
            if path.name != "latest.json":
                raise OSError("crash")
            write(path, data)

        with mock.patch.object(nightly_gate, "write", side_effect=crash_after_latest), self.assertRaises(OSError):
            self.run_gate()
        return nightly_gate.latest("demo")["sha"]

    def test_result_survives_a_crash_before_the_sha_result_is_written(self):
        marker = self.tmp / "runs"
        sha = self.crash_before_the_sha_result(marker)
        self.run_gate()
        self.assertTrue(nightly_gate.completed("demo", sha)["posted"])
        self.assertEqual(marker.read_text().count("x"), 1)

    def test_result_survives_a_crash_before_the_sha_result_after_main_moves(self):
        marker = self.tmp / "runs"
        first = self.crash_before_the_sha_result(marker)
        self.commit("two\n")
        self.run_gate()
        self.assertTrue(nightly_gate.completed("demo", first)["posted"])
        self.assertIn(f"statuses/{first}", self.gh_calls.read_text())
        self.assertNotEqual(nightly_gate.latest("demo")["sha"], first)
        self.assertEqual(marker.read_text().count("x"), 2)

    def test_ack_covers_new_failures_until_a_pass(self):
        self.configure("exit 3")
        self.run_gate()
        first = nightly_gate.latest("demo")["sha"]
        nightly_gate.main(["ack", "demo", first, "thread-1"])

        self.commit("two\n")
        self.run_gate()
        result = nightly_gate.latest("demo")
        self.assertNotEqual(result["sha"], first)
        self.assertEqual((result["ack"]["thread"], result["ack"]["sha"]), ("thread-1", first))
        self.wake.assert_called_once_with("demo")

        self.configure("true")
        self.commit("three\n")
        self.run_gate()
        self.assertIsNone(nightly_gate.latest("demo")["ack"])
        self.configure("exit 3")
        self.commit("four\n")
        self.run_gate()
        self.assertIsNone(nightly_gate.latest("demo")["ack"])
        self.assertEqual(self.wake.call_count, 2)

    def test_each_repo_wakes_the_fix_task_before_the_next_runs(self):
        marker = self.tmp / "b-ran"
        clone = str(self.tmp / "clone")
        repos = {"a": {"clone": clone, "suite": "exit 1"}, "b": {"clone": clone, "suite": f"touch {marker}"},
                 "c": {"clone": clone, "suite": "exit 1"}}
        self.config.write_text(json.dumps({"repos": repos}))
        woken = []
        self.wake.side_effect = lambda name: woken.append((name, marker.exists())) or 0
        self.run_gate()
        self.assertEqual(woken, [("a", False), ("c", True)])

    def test_fetch_error_keeps_the_result_at_main(self):
        marker = self.tmp / "runs"
        self.configure(f"echo x >> {marker}")
        self.run_gate()
        sha = nightly_gate.latest("demo")["sha"]
        git(self.tmp / "clone", "remote", "set-url", "origin", str(self.tmp / "missing"))
        self.run_gate()
        self.assertEqual(nightly_gate.latest("demo")["status"], "error")

        git(self.tmp / "clone", "remote", "set-url", "origin", str(self.origin))
        self.run_gate()
        self.assertEqual((nightly_gate.latest("demo")["status"], nightly_gate.latest("demo")["sha"]), ("pass", sha))
        self.assertEqual(marker.read_text().count("x"), 1)

    def test_checkout_error_runs_again(self):
        marker = self.tmp / "runs"
        self.configure(f"echo x >> {marker}")
        with mock.patch.object(nightly_gate, "fresh_checkout", side_effect=OSError("disk full")):
            self.run_gate()
        self.assertEqual(nightly_gate.latest("demo")["status"], "error")
        self.run_gate()
        self.assertEqual(nightly_gate.latest("demo")["status"], "pass")
        self.assertEqual(marker.read_text().count("x"), 1)

    def test_unknown_repo_is_refused(self):
        self.configure("true")
        with mock.patch("sys.stderr"):
            self.assertEqual(self.run_gate("other"), 2)


if __name__ == "__main__":
    unittest.main()
