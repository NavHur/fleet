"""Behavior tests for sync_all.py. Run from this directory: python3 -m unittest test_sync_all"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sync_all

DONE = "== Release binaries\n  binary     ruff 0.17.3 (x86_64-unknown-linux-gnu)\n  \x1b[32m✓\x1b[0m Updated 3 skills\nDone.\n"
DRY_RUN = "== Host files (hosts/workbox)\n  link       ~/.config/x -> ~/code/fleet/x\n  write      ~/.config/y\n\nDry run: nothing changed. Re-run with --apply to carry out the plan.\n"
IN_SYNC = "== Own skills\n\nAlready in sync.\nDry run: nothing changed. Re-run with --apply to carry out the plan.\n"


class SyncAll(unittest.TestCase):
    def setUp(self):
        self.fleet = Path(tempfile.mkdtemp())
        self.logs = Path(tempfile.mkdtemp()) / "sync"
        patcher = mock.patch.object(sync_all, "LOGS", self.logs)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.host("mac", checkout="~/dev/fleet", reaches=["workbox"])
        self.host("workbox", checkout="~/code/fleet", ssh="workbox")
        self.ran = []

    def host(self, name: str, **conf: object) -> None:
        (self.fleet / "hosts" / name).mkdir(parents=True)
        (self.fleet / "hosts" / name / "host.json").write_text(json.dumps({"hostnames": [name], **conf}))

    def sync(self, outputs: dict[str, tuple[int, str]], *flags: str, self_name: str = "mac") -> tuple[int, str]:
        def fake_run(argv):
            self.ran.append(argv)
            return outputs[argv[-2] if argv[0] == "ssh" else self_name]
        out = io.StringIO()
        with mock.patch.object(sync_all, "run", fake_run), contextlib.redirect_stdout(out):
            code = sync_all.main([str(self.fleet), self_name, *flags])
        return code, out.getvalue()

    def test_this_machine_runs_its_checkout_and_the_others_run_theirs_over_ssh(self):
        self.sync({"mac": (0, DONE), "workbox": (0, DONE)}, "--apply")
        local, remote = sorted(self.ran, key=lambda argv: argv[0] == "ssh")
        self.assertEqual(local, [str(Path("~/dev/fleet").expanduser() / "bin/sync"), "--apply"])
        self.assertEqual(remote[0], "ssh")
        self.assertIn("BatchMode=yes", remote)
        self.assertEqual(remote[-2:], ["workbox", "bash -lc 'cd ~/code/fleet && bin/sync --apply'"])

    def test_one_line_per_machine_and_the_whole_output_in_its_log(self):
        code, out = self.sync({"mac": (0, IN_SYNC), "workbox": (0, DRY_RUN)})
        self.assertEqual(code, 0)
        self.assertIn("  ok         mac: already in sync", out)
        self.assertIn("  plan       workbox: 2 changes planned", out)
        self.assertEqual((self.logs / "workbox.log").read_text(), DRY_RUN)

    def test_an_applied_sync_counts_its_changes_and_logs_without_colors(self):
        _, out = self.sync({"mac": (0, DONE), "workbox": (0, DONE)}, "--apply")
        self.assertIn("  ok         workbox: 1 change made", out)
        self.assertNotIn("\x1b", (self.logs / "workbox.log").read_text())

    def test_a_failed_machine_shows_its_last_line_and_fails_the_run(self):
        code, out = self.sync({"mac": (0, DONE), "workbox": (255, "ssh: connect to host workbox: Operation timed out\n")})
        self.assertEqual(code, 1)
        self.assertIn("  failed     workbox: exit 255: ssh: connect to host workbox: Operation timed out", out)

    def test_a_machine_without_an_ssh_host_is_skipped_from_elsewhere(self):
        code, out = self.sync({"workbox": (0, DONE)}, self_name="workbox")
        self.assertEqual(code, 0)
        self.assertIn("  skipped    mac: not in workbox's reaches, or host.json has no checkout or ssh host", out)
        self.assertEqual(self.ran, [[str(Path("~/code/fleet").expanduser() / "bin/sync")]])

    def test_a_machine_outside_this_ones_reaches_is_skipped(self):
        self.host("devbox", checkout="~/src/fleet", ssh="devbox")
        code, out = self.sync({"mac": (0, DONE), "workbox": (0, DONE)})
        self.assertEqual(code, 0)
        self.assertIn("  skipped    devbox: not in mac's reaches", out)
        self.assertNotIn("devbox", [argv[-2] for argv in self.ran if argv[0] == "ssh"])


if __name__ == "__main__":
    unittest.main()
