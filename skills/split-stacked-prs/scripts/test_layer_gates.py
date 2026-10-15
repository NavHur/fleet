"""Drive layer_gates.sh over a stack built by build_layers.sh, with stub checks."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).parent
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
BASH_MAJOR = int(subprocess.run(["bash", "-c", "echo ${BASH_VERSINFO[0]}"], capture_output=True, text=True).stdout)


@unittest.skipIf(BASH_MAJOR < 4, "layer_gates.sh needs bash 4 or newer (mapfile)")
class LayerGatesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.root = self.tmp / "repo"
        self.manifests = self.tmp / "layers"
        self.manifests.mkdir()
        self.root.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.root / "app.ts").write_text("app\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "source")
        for name in ("a.ts", "b.ts", "c.ts"):
            (self.root / name).write_text(name + "\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "source")
        self.git("checkout", "-q", "main")
        for name, path in (("01-a", "a.ts"), ("02-b", "b.ts"), ("03-c", "c.ts")):
            (self.manifests / name).write_text(path + "\n")
        subprocess.run(
            ["bash", str(HERE / "build_layers.sh"), "--base", "main", "--source", "source",
             "--manifests", str(self.manifests), "--prefix", "s-"],
            cwd=self.root, check=True, capture_output=True, env=self.env(),
        )

    def env(self, **extra):
        return {**os.environ, **IDENTITY, **extra}

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True, env=self.env()).strip()

    def gates(self, *options):
        calls = self.tmp / "tests.calls"
        env = self.env(
            HOST_CHECK_ACTIVE="1", TYPECHECK_CMD="true", LINT_CMD="true", FORMAT_CMD="true",
            TEST_CMD=f'echo "$(git rev-parse --abbrev-ref HEAD) $1" >> {calls}; :',
        )
        result = subprocess.run(
            ["bash", str(HERE / "layer_gates.sh"), "--manifests", str(self.manifests), "--prefix", "s-",
             "--base", "main", "--no-setup", *options],
            cwd=self.root, text=True, capture_output=True, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        verdicts = {line.split()[0]: line.split()[1:] for line in result.stdout.splitlines() if line[:2] in ("01", "02", "03")}
        return calls.read_text().splitlines(), verdicts

    def test_tests_run_once_on_the_top_layer_against_the_base(self):
        calls, verdicts = self.gates()
        self.assertEqual(calls, ["s-03-c main"])
        self.assertIn("tests=deferred", verdicts["01-a"])
        self.assertIn("tests=deferred", verdicts["02-b"])
        self.assertIn("tests=OK", verdicts["03-c"])

    def test_tests_each_runs_every_layer_against_its_parent(self):
        calls, _verdicts = self.gates("--tests-each")
        self.assertEqual(calls, ["s-01-a main", "s-02-b s-01-a", "s-03-c s-02-b"])


if __name__ == "__main__":
    unittest.main()
