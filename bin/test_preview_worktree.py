import contextlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
