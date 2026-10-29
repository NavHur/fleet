import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import opencode_servers  # noqa: E402

LSOF_LISTEN = """COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
opencode 478 pedro 7u IPv4 0x1 0t0 TCP 127.0.0.1:49374 (LISTEN)
"""
LSOF_ESTABLISHED = """COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
opencode 478 pedro 13u IPv4 0x2 0t0 TCP 192.168.1.199:59309->172.66.173.149:443 (ESTABLISHED)
opencode 478 pedro 21u IPv4 0x3 0t0 TCP 127.0.0.1:49374->127.0.0.1:60001 (ESTABLISHED)
"""


class Seconds(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(opencode_servers.seconds("05:07"), 307)
        self.assertEqual(opencode_servers.seconds("02:05:07"), 7507)
        self.assertEqual(opencode_servers.seconds(" 9-02:05:07"), 9 * 86400 + 7507)


class IsServer(unittest.TestCase):
    def test_matches_serve_only(self):
        self.assertTrue(opencode_servers.is_server("/home/u/.opencode/bin/opencode serve --service"))
        self.assertTrue(opencode_servers.is_server("node /nvm/bin/opencode serve --port 3790"))
        self.assertFalse(opencode_servers.is_server("/home/u/.opencode/bin/opencode run hello"))
        self.assertFalse(opencode_servers.is_server("vim serve.md opencode"))


class Clients(unittest.TestCase):
    def test_counts_inbound_connections_only(self):
        outputs = {"-sTCP:LISTEN": LSOF_LISTEN, "-sTCP:ESTABLISHED": LSOF_ESTABLISHED}
        with mock.patch.object(opencode_servers, "run", side_effect=lambda *a: outputs[a[-1]]):
            self.assertEqual(opencode_servers.clients(478), ["127.0.0.1:49374->127.0.0.1:60001"])

    def test_outbound_only_is_idle(self):
        outputs = {"-sTCP:LISTEN": LSOF_LISTEN, "-sTCP:ESTABLISHED": LSOF_ESTABLISHED.splitlines()[0]
                   + "\n" + LSOF_ESTABLISHED.splitlines()[1]}
        with mock.patch.object(opencode_servers, "run", side_effect=lambda *a: outputs[a[-1]]):
            self.assertEqual(opencode_servers.clients(478), [])


class RestartCommand(unittest.TestCase):
    def test_prefers_systemd_unit(self):
        with mock.patch.object(opencode_servers, "unit", return_value="opencode-server.service"):
            self.assertEqual(opencode_servers.restart_command(1, "opencode serve --port 3790"),
                             ["systemctl", "--user", "restart", "opencode-server.service"])

    def test_kills_detached_service_daemon(self):
        with mock.patch.object(opencode_servers, "unit", return_value=None):
            self.assertEqual(opencode_servers.restart_command(7, "opencode serve --service"), ["kill", "7"])

    def test_leaves_other_servers_alone(self):
        with mock.patch.object(opencode_servers, "unit", return_value=None):
            self.assertIsNone(opencode_servers.restart_command(7, "opencode serve --port 4096"))


class BinaryReplaced(unittest.TestCase):
    def executable(self, exe):
        patch = mock.patch.object(opencode_servers.os, "readlink", return_value=exe)
        patch.start()
        self.addCleanup(patch.stop)

    def binary(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        binary = Path(tmp.name) / "opencode"
        binary.write_text("#!/bin/sh\n")
        os.utime(binary, (0, 0))  # the install script keeps the tarball's 1985 mtime
        return binary

    def test_installed_after_start_is_replaced(self):
        binary = self.binary()
        self.executable(str(binary))
        self.assertTrue(opencode_servers.binary_replaced(7, binary.stat().st_ctime - 10))
        self.assertFalse(opencode_servers.binary_replaced(7, binary.stat().st_ctime + 10))

    def test_deleted_executable_is_replaced(self):
        self.executable("/x/@opencode/.cli-dcyX9P6v/bin/opencode.exe (deleted)")
        self.assertTrue(opencode_servers.binary_replaced(7, 1e12))

    def test_vanished_executable_is_replaced(self):
        self.executable("/nonexistent/opencode")
        self.assertTrue(opencode_servers.binary_replaced(7, 1e12))

    def test_without_proc_reads_the_path_from_ps(self):
        binary = self.binary()
        with mock.patch.object(opencode_servers.os, "readlink", side_effect=FileNotFoundError), \
                mock.patch.object(opencode_servers, "run", return_value=f"{binary}\n") as ps:
            self.assertTrue(opencode_servers.binary_replaced(7, binary.stat().st_ctime - 10))
        ps.assert_called_once_with("ps", "-o", "comm=", "-p", "7")

    def test_exited_process_is_not_replaced(self):
        with mock.patch.object(opencode_servers.os, "readlink", side_effect=FileNotFoundError), \
                mock.patch.object(opencode_servers, "run", return_value=""):
            self.assertFalse(opencode_servers.binary_replaced(7, 0))

    def test_unreadable_executable_raises(self):
        self.executable("/locked/opencode")
        with mock.patch.object(opencode_servers.os, "stat", side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                opencode_servers.binary_replaced(7, 0)


class Main(unittest.TestCase):
    def plan(self, started, busy=False, replaced=False):
        patches = [
            mock.patch.object(opencode_servers, "plugins_changed", return_value=100.0),
            mock.patch.object(opencode_servers, "binary_replaced", return_value=replaced),
            mock.patch.object(opencode_servers, "servers", return_value=[(7, started, "opencode serve --service")]),
            mock.patch.object(opencode_servers, "unit", return_value=None),
            mock.patch.object(opencode_servers, "clients", return_value=["x"] if busy else []),
            mock.patch.object(opencode_servers, "restart"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        with mock.patch("builtins.print") as printed:
            opencode_servers.main(["--apply"])
        return [call.args[0].split()[0] for call in printed.call_args_list], opencode_servers.restart

    def test_fresh_server_is_left_running(self):
        lines, restart = self.plan(started=200.0)
        self.assertEqual(lines, [])
        restart.assert_not_called()

    def test_stale_idle_server_restarts(self):
        lines, restart = self.plan(started=50.0)
        self.assertEqual(lines, ["restart"])
        restart.assert_called_once_with(7, ["kill", "7"])

    def test_server_older_than_its_binary_restarts(self):
        lines, restart = self.plan(started=200.0, replaced=True)
        self.assertEqual(lines, ["restart"])
        restart.assert_called_once_with(7, ["kill", "7"])

    def test_stale_busy_server_waits(self):
        lines, restart = self.plan(started=50.0, busy=True)
        self.assertEqual(lines, ["restart", "warning"])
        restart.assert_not_called()


if __name__ == "__main__":
    unittest.main()
