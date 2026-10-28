import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import tarfile
import tempfile
import unittest
from unittest import mock

loader = importlib.machinery.SourceFileLoader("actions_runners", str(Path(__file__).parent / "actions-runners"))
actions_runners = importlib.util.module_from_spec(importlib.util.spec_from_loader("actions_runners", loader))
loader.exec_module(actions_runners)

# Stands in for gh: logs each call and answers the three endpoints the script uses.
GH = """#!/bin/sh
echo "$@" >> "$CALLS"
case "$*" in
  *releases/latest*) echo v2.0.0 ;;
  *-token*) echo TOKEN ;;
esac
"""
# Stands in for systemctl: logs each call.
SYSTEMCTL = '#!/bin/sh\necho systemctl "$@" >> "$CALLS"\n'
# The runner's config.sh: logs its arguments and leaves what a registration leaves.
CONFIG_SH = """#!/bin/sh
echo config.sh "$@" >> "$CALLS"
if [ "$1" = remove ]; then rm -f .runner; exit 0; fi
echo '{}' > .runner
printf 'LANG=C.UTF-8\\nnpm_config_store_dir=/elsewhere\\n' > .env
echo /usr/bin > .path
"""


def stub(folder, name, body):
    path = folder / name
    path.write_text(body)
    path.chmod(0o755)


class Runners(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        stub(bin_dir, "gh", GH)
        stub(bin_dir, "systemctl", SYSTEMCTL)
        self.calls = self.tmp / "calls"
        self.calls.touch()
        cache = self.tmp / "cache"
        cache.mkdir()
        arch = actions_runners.ARCH[platform.machine()]
        with tarfile.open(cache / f"actions-runner-linux-{arch}-2.0.0.tar.gz", "w:gz") as tar:
            info = tarfile.TarInfo("config.sh")
            info.size = len(CONFIG_SH)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(CONFIG_SH.encode()))
        config = self.tmp / "runners.json"
        config.write_text(json.dumps({"labels": ["devbox"], "repos": {"one": "me/one", "two": "me/two"}}))
        env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "CALLS": str(self.calls)}
        patches = [mock.patch.dict(os.environ, env),
                   mock.patch.object(actions_runners, "CONFIG", config),
                   mock.patch.object(actions_runners, "ROOT", self.tmp / "runners"),
                   mock.patch.object(actions_runners, "CACHE", cache),
                   mock.patch.object(actions_runners.socket, "gethostname", return_value="devbox.pnav.dev")]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def log(self):
        return self.calls.read_text().splitlines()

    def test_install_registers_starts_and_sets_the_job_environment(self):
        self.assertEqual(actions_runners.main(["install", "one"]), 0)
        self.assertIn("config.sh --unattended --replace --url https://github.com/me/one --token TOKEN "
                      "--name devbox-one --labels devbox --work _work", self.log())
        self.assertIn("api -X POST repos/me/one/actions/runners/registration-token --jq .token", self.log())
        self.assertIn("systemctl --user enable --now actions-runner@one.service", self.log())
        folder = self.tmp / "runners" / "one"
        self.assertEqual((folder / ".path").read_text(), actions_runners.JOB_PATH + "\n")
        env = (folder / ".env").read_text().splitlines()
        self.assertIn("LANG=C.UTF-8", env)
        self.assertEqual([line for line in env if line.startswith("npm_config_store_dir=")],
                         [f"npm_config_store_dir={actions_runners.JOB_ENV['npm_config_store_dir']}"])
        self.assertEqual(actions_runners.missing(), ["two"])

    def test_install_skips_installed_runners(self):
        actions_runners.main(["install", "one"])
        self.calls.write_text("")
        actions_runners.main(["install"])
        self.assertFalse([line for line in self.log() if "devbox-one" in line])
        self.assertTrue([line for line in self.log() if "--name devbox-two" in line])

    def test_install_rejects_an_unknown_name(self):
        self.assertEqual(actions_runners.main(["install", "three"]), 2)
        self.assertEqual(self.log(), [])

    def test_remove_deregisters_and_deletes(self):
        actions_runners.main(["install", "one"])
        self.assertEqual(actions_runners.main(["remove", "one"]), 0)
        self.assertIn("config.sh remove --token TOKEN", self.log())
        self.assertIn("api -X POST repos/me/one/actions/runners/remove-token --jq .token", self.log())
        self.assertFalse((self.tmp / "runners" / "one").exists())
        self.assertEqual(actions_runners.missing(), ["one", "two"])


if __name__ == "__main__":
    unittest.main()
