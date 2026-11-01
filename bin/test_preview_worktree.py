import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from unittest import mock

loader = importlib.machinery.SourceFileLoader("preview_worktree", str(Path(__file__).parent / "preview-worktree"))
pw = importlib.util.module_from_spec(importlib.util.spec_from_loader("preview_worktree", loader))
loader.exec_module(pw)

RECIPE = {
    "copy": [".dev.vars"],
    "setup": [["migrate", "--local"]],
    "serve": ["server", "--port", "{port}", "--var", "AUTH_ORIGIN:{origin}"],
}


def git(*args):
    subprocess.run(["git", *args], check=True, capture_output=True)


class Temp(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="preview-worktree-test-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        patcher = mock.patch.object(pw, "STATE", self.root / "state")
        patcher.start()
        self.addCleanup(patcher.stop)

    def checkout(self):
        """A main checkout named shop with one linked worktree, feature."""
        main = self.root / "shop"
        git("init", "-q", "-b", "main", str(main))
        git("-C", str(main), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base")
        git("-C", str(main), "worktree", "add", "-q", "--detach", str(self.root / "feature"))
        return main, self.root / "feature"

    def record(self, name, port, worktree=None):
        worktree = worktree or self.root
        record = {"name": name, "project": "shop", "worktree": str(worktree), "dir": str(worktree),
                  "port": port, "recipe": RECIPE}
        pw.write_state(record)
        return record


class Identify(Temp):
    def test_a_linked_worktree_belongs_to_its_main_checkouts_project(self):
        main, feature = self.checkout()
        project, worktree, found_main = pw.identify(feature / ".")
        self.assertEqual((project, worktree, found_main), ("shop", feature.resolve(), main.resolve()))
        self.assertRegex(pw.preview_name(project, worktree), r"^shop-feature-[0-9a-f]{6}$")

    def test_worktrees_sharing_a_directory_name_get_distinct_previews(self):
        names = {pw.preview_name("shop", self.root / run / "base") for run in ("one", "two")}
        self.assertEqual(len(names), 2)

    def test_the_main_checkout_is_refused(self):
        main, _ = self.checkout()
        with self.assertRaisesRegex(pw.Refusal, "main checkout"):
            pw.identify(main)

    def test_a_directory_outside_git_is_refused(self):
        with self.assertRaisesRegex(pw.Refusal, "not inside a Git worktree"):
            pw.identify(self.root)


class Ports(Temp):
    CONFIG = {"ports": [4400, 4402]}

    def test_a_preview_keeps_its_port(self):
        records = [self.record("a", 4401)]
        self.assertEqual(pw.allocate_port(self.CONFIG, "a", records), 4401)

    def test_a_new_preview_skips_ports_other_previews_hold(self):
        records = [self.record("a", 4400)]
        self.assertEqual(pw.allocate_port(self.CONFIG, "b", records), 4401)

    def test_a_new_preview_skips_a_port_something_else_listens_on(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            config = {"ports": [port, port + 1]}
            self.assertNotEqual(pw.allocate_port(config, "b", []), port)

    def test_an_exhausted_range_is_refused(self):
        records = [self.record(name, port) for name, port in [("a", 4400), ("b", 4401), ("c", 4402)]]
        with self.assertRaisesRegex(pw.Refusal, "no free port"):
            pw.allocate_port(self.CONFIG, "d", records)


class Lifecycle(Temp):
    def test_prune_forgets_previews_whose_worktree_or_unit_is_gone(self):
        self.record("removed", 4400, worktree=self.root / "deleted")
        self.record("stopped", 4401)
        self.record("running", 4402)
        self.record("starting", 4403, worktree=self.root / "deleted")
        with mock.patch.object(pw, "active", lambda name: name != "stopped"), \
                mock.patch.object(pw, "stop_unit") as stop_unit:
            removed = pw.prune(keep="starting")
        self.assertEqual(sorted(removed), ["removed", "stopped"])
        self.assertEqual(sorted(r["name"] for r in pw.read_states()), ["running", "starting"])
        self.assertEqual(sorted(c.args[0] for c in stop_unit.call_args_list), ["removed", "stopped"])

    def test_the_limit_counts_other_previews_only(self):
        records = [self.record("a", 4400), self.record("b", 4401)]
        pw.check_limit({"limit": 2}, "a", records)
        with self.assertRaisesRegex(pw.Refusal, "2 previews already run"):
            pw.check_limit({"limit": 2}, "c", records)

    def test_local_files_are_copied_once_and_never_overwritten(self):
        main, worktree = self.root / "main", self.root / "wt"
        main.mkdir()
        worktree.mkdir()
        (main / ".dev.vars").write_text("SECRET=main\n")
        pw.copy_from_main(RECIPE, worktree, main)
        self.assertEqual((worktree / ".dev.vars").read_text(), "SECRET=main\n")
        self.assertEqual((worktree / ".dev.vars").stat().st_mode & 0o777, 0o600)
        (worktree / ".dev.vars").write_text("SECRET=branch\n")
        pw.copy_from_main(RECIPE, worktree, main)
        self.assertEqual((worktree / ".dev.vars").read_text(), "SECRET=branch\n")

    def test_the_unit_runs_setup_then_serves_on_its_port_and_origin(self):
        self.record("shop-feature", 4405)
        with mock.patch.object(pw, "run_step") as run_step, mock.patch.object(pw.os, "execvp") as execvp:
            pw.serve(["shop-feature"])
        run_step.assert_called_once_with(["migrate", "--local"], str(self.root))
        execvp.assert_called_once_with(
            "server", ["server", "--port", "4405", "--var", "AUTH_ORIGIN:http://localhost:4405"])

    def test_the_build_queues_unless_it_already_runs_in_the_queue(self):
        recipe = {"build": ["npm", "run", "build"]}
        for queued, expected in [(False, ["host-check", "npm", "run", "build"]), (True, ["npm", "run", "build"])]:
            env = {key: value for key, value in pw.os.environ.items() if key != "HOST_CHECK_ACTIVE"}
            if queued:
                env["HOST_CHECK_ACTIVE"] = "1"
            with self.subTest(queued=queued), mock.patch.dict(pw.os.environ, env, clear=True), \
                    mock.patch.object(pw, "run_step") as run_step:
                pw.build(recipe, self.root)
                run_step.assert_called_once_with(expected, self.root)


class Main(Temp):
    def test_a_project_without_a_recipe_names_the_known_ones(self):
        _, feature = self.checkout()
        config = self.root / "previews.json"
        config.write_text(json.dumps({"projects": {"leetwiz": RECIPE}}))
        stderr = io.StringIO()
        with mock.patch.object(pw, "CONFIG", config), contextlib.redirect_stderr(stderr):
            code = pw.main(["start", str(feature), "--no-build"])
        self.assertEqual(code, 2)
        self.assertIn("no preview recipe for shop (known: leetwiz)", stderr.getvalue())


def completed(code, stderr=""):
    return subprocess.CompletedProcess([], code, "", stderr)


class Robustness(Temp):
    NAME = "shop-feature-abc123"

    def test_a_retained_port_something_else_took_is_replaced(self):
        records = [self.record("a", 4400)]
        with mock.patch.object(pw, "port_free", lambda port: port != 4400):
            self.assertEqual(pw.allocate_port({"ports": [4400, 4402]}, "a", records), 4401)

    def test_an_answer_from_another_service_is_not_readiness_of_an_inactive_unit(self):
        record = self.record("a", 4400)
        with mock.patch.object(pw, "active", lambda name: False), mock.patch.object(pw, "responds", lambda url: True), \
                mock.patch.object(pw, "report") as report, mock.patch.object(pw.subprocess, "run"):
            with self.assertRaisesRegex(pw.Refusal, "did not answer"):
                pw.wait_ready(record, 5)
        report.assert_not_called()

    @contextlib.contextmanager
    def answering(self, listener):
        """An active unit whose port answers; yields the record and the report mock."""
        with mock.patch.object(pw, "active", lambda name: True), mock.patch.object(pw, "responds", lambda url: True), \
                mock.patch.object(pw, "listens_in_unit", listener), mock.patch.object(pw.time, "sleep"), \
                mock.patch.object(pw.time, "monotonic", side_effect=[0, 1, 2, 100]), \
                mock.patch.object(pw, "report") as report, mock.patch.object(pw.subprocess, "run"):
            yield self.record("a", 4400), report

    def test_an_answer_from_a_process_outside_the_unit_is_not_readiness(self):
        with self.answering(lambda port, name: False) as (record, report):
            with self.assertRaisesRegex(pw.Refusal, "did not answer"):
                pw.wait_ready(record, 5)
        report.assert_not_called()

    def test_an_answer_from_the_units_own_listener_is_readiness(self):
        with self.answering(lambda port, name: True) as (record, report):
            pw.wait_ready(record, 5)
        report.assert_called_once()

    def test_a_failing_ss_is_refused_at_once_not_polled_to_the_deadline(self):
        failing = completed(1, "ss: netlink error\n")
        with mock.patch.object(pw.subprocess, "run", return_value=failing):
            with self.assertRaisesRegex(pw.Refusal, "ss failed .*netlink error"):
                pw.listens_in_unit(4400, "a")
        calls = []
        real = pw.listens_in_unit

        def listener(port, name):
            calls.append(port)
            return real(port, name)

        with self.answering(listener) as (record, report):
            with mock.patch.object(pw.subprocess, "run", return_value=failing):
                with self.assertRaisesRegex(pw.Refusal, "netlink error"):
                    pw.wait_ready(record, 5)
        self.assertEqual(len(calls), 1)
        report.assert_not_called()

    def test_an_unreadable_cgroup_is_an_error_not_a_foreign_process(self):
        with mock.patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                pw.in_unit(11, "a")
        with mock.patch.object(Path, "read_text", side_effect=FileNotFoundError("gone")):
            self.assertFalse(pw.in_unit(11, "a"))

    def test_listens_in_unit_matches_the_listener_cgroup(self):
        line = 'LISTEN 0      4096   127.0.0.1:4400 0.0.0.0:* users:(("workerd",pid=11,fd=12),("x",pid=12,fd=3))\n'
        groups = {
            "/proc/11/cgroup": "0::/user.slice/other-wtpreview-a.service\n",
            "/proc/12/cgroup": "0::/user.slice/user@1000.service/app.slice/wtpreview-a.service\n",
        }

        def read(path):
            if str(path) not in groups:
                raise FileNotFoundError(path)
            return groups[str(path)]

        with mock.patch.object(pw.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, line, "")), \
                mock.patch.object(Path, "read_text", read):
            self.assertTrue(pw.listens_in_unit(4400, "a"))
            self.assertFalse(pw.listens_in_unit(4400, "b"))
            groups.pop("/proc/12/cgroup")  # exited since ss listed it
            self.assertFalse(pw.listens_in_unit(4400, "a"))

    def test_a_copy_in_flight_or_torn_leaves_nothing_git_could_publish(self):
        main, worktree = self.root / "main", self.root / "wt"
        main.mkdir()
        git("init", "-q", str(worktree))
        (main / ".dev.vars").write_text("SECRET=main\n")
        real = pw.shutil.copyfileobj
        seen = []

        def spying(source, out, fail=False):
            real(source, out)
            out.flush()
            for args in (["status", "--porcelain"], ["add", "-A", "--dry-run"]):
                seen.append(subprocess.run(["git", "-C", str(worktree), *args], capture_output=True, text=True, check=True).stdout)
            if fail:
                raise OSError("killed")

        torn = lambda source, out: spying(source, out, fail=True)
        with mock.patch.object(pw.shutil, "copyfileobj", torn), self.assertRaises(OSError):
            pw.copy_from_main(RECIPE, worktree, main)
        self.assertEqual([p.name for p in worktree.iterdir()], [".git"])
        with mock.patch.object(pw.shutil, "copyfileobj", spying):
            pw.copy_from_main(RECIPE, worktree, main)
        self.assertEqual(seen, [""] * 4)
        self.assertEqual(sorted(p.name for p in worktree.iterdir()), [".dev.vars", ".git"])
        self.assertEqual((worktree / ".dev.vars").read_text(), "SECRET=main\n")
        self.assertEqual((worktree / ".dev.vars").stat().st_mode & 0o777, 0o600)

    @unittest.skipUnless(os.path.isdir("/dev/shm") and os.stat("/dev/shm").st_dev != os.stat(tempfile.gettempdir()).st_dev,
                         "needs /dev/shm on another filesystem than the temp dir")
    def test_a_worktree_on_another_filesystem_gets_the_copy(self):
        main = self.root / "main"
        main.mkdir()
        (main / ".dev.vars").write_text("SECRET=main\n")
        worktree = Path(tempfile.mkdtemp(dir="/dev/shm", prefix="preview-worktree-test-"))
        self.addCleanup(shutil.rmtree, worktree, True)
        pw.copy_from_main(RECIPE, worktree, main)
        self.assertEqual([p.name for p in worktree.iterdir()], [".dev.vars"])
        self.assertEqual((worktree / ".dev.vars").read_text(), "SECRET=main\n")
        self.assertEqual((worktree / ".dev.vars").stat().st_mode & 0o777, 0o600)

    def test_a_reader_never_sees_a_partly_written_record(self):
        self.record("a", 4400)
        seen = []
        real = Path.write_text

        def torn(path, text, *args, **kwargs):
            real(path, text[:5])
            seen.append(pw.read_states())
            return real(path, text)

        with mock.patch.object(Path, "write_text", torn):
            self.record("a", 4401)
        self.assertEqual([r["port"] for r in seen[0]], [4400])
        self.assertEqual([r["port"] for r in pw.read_states()], [4401])

    def test_a_file_created_between_the_check_and_the_copy_is_not_overwritten(self):
        main, worktree = self.root / "main", self.root / "wt"
        main.mkdir()
        worktree.mkdir()
        (main / ".dev.vars").write_text("SECRET=main\n")
        (worktree / ".dev.vars").write_text("SECRET=branch\n")
        with mock.patch.object(Path, "exists", lambda path: path == main / ".dev.vars"):
            pw.copy_from_main(RECIPE, worktree, main)
        self.assertEqual((worktree / ".dev.vars").read_text(), "SECRET=branch\n")

    def test_stopping_a_preview_twice_succeeds(self):
        self.record(self.NAME, 4400)
        results = iter([completed(0), completed(0), completed(5, "Unit x not loaded."), completed(1, "Unit x not loaded.")])
        out = io.StringIO()
        with mock.patch.object(pw, "systemctl", lambda *args: next(results)), contextlib.redirect_stdout(out):
            self.assertEqual(pw.main(["stop", self.NAME]), 0)
            self.assertEqual(pw.main(["stop", self.NAME]), 0)
        self.assertEqual(out.getvalue(), f"stopped {self.NAME}\n" * 2)
        self.assertEqual(pw.read_states(), [])

    def test_systemd_being_unreachable_is_not_an_inactive_unit(self):
        self.record("a", 4400)
        down = completed(1, "Failed to connect to bus")
        with mock.patch.object(pw, "systemctl", lambda *args: down):
            with self.assertRaisesRegex(pw.Refusal, "Failed to connect to bus"):
                pw.prune()
            with self.assertRaisesRegex(pw.Refusal, "Failed to connect to bus"):
                pw.status([])
        self.assertEqual([r["name"] for r in pw.read_states()], ["a"])

    def test_is_active_reads_inactive_and_unknown_units_as_stopped(self):
        for code, expected in [(0, True), (3, False), (4, False)]:
            with self.subTest(code=code), mock.patch.object(pw, "systemctl", lambda *args: completed(code)):
                self.assertIs(pw.active("a"), expected)

    def test_a_failed_stop_keeps_the_record(self):
        self.record(self.NAME, 4400)
        with mock.patch.object(pw, "systemctl", lambda *args: completed(1, "Access denied")):
            with self.assertRaisesRegex(pw.Refusal, "Access denied"):
                pw.stop([self.NAME])
        self.assertEqual([r["name"] for r in pw.read_states()], [self.NAME])

    def test_extra_arguments_and_unknown_options_are_refused(self):
        for argv in (["start", "a", "b"], ["start", "--bogus"], ["stop", "a", "b"], ["stop", "--no-build"]):
            stderr = io.StringIO()
            with self.subTest(argv=argv), contextlib.redirect_stderr(stderr):
                self.assertEqual(pw.main(argv), 2)
            self.assertIn("usage: preview-worktree", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
