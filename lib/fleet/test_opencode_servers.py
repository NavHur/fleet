from pathlib import Path
import sys
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


class Main(unittest.TestCase):
    def plan(self, started, busy=False):
        patches = [
            mock.patch.object(opencode_servers, "plugins_changed", return_value=100.0),
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

    def test_stale_busy_server_waits(self):
        lines, restart = self.plan(started=50.0, busy=True)
        self.assertEqual(lines, ["restart", "warning"])
        restart.assert_not_called()


if __name__ == "__main__":
    unittest.main()
