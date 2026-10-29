"""Drive layer_gates.sh over a stack built by build_layers.sh, with stub checks."""

from pathlib import Path
import subprocess
import unittest

from stack_fixture import StackRepo

HERE = Path(__file__).parent
BASH_MAJOR = int(subprocess.run(["bash", "-c", "echo ${BASH_VERSINFO[0]}"], capture_output=True, text=True).stdout)


@unittest.skipIf(BASH_MAJOR < 4, "layer_gates.sh needs bash 4 or newer (mapfile)")
class LayerGatesTests(unittest.TestCase):
    def setUp(self):
        self.repo = StackRepo(self)
        self.repo.branch("source", "main", {name: name + "\n" for name in ("a.ts", "b.ts", "c.ts", "d.ts")})
        self.repo.manifest("01-a", "# commit: add a\na.ts\n# commit: add d\nd.ts\n")
        self.repo.manifest("02-b", "b.ts\n")
        self.repo.manifest("03-c", "c.ts\n")
        subprocess.run(
            ["bash", str(HERE / "build_layers.sh"), "--base", "main", "--source", "source",
             "--manifests", str(self.repo.manifests), "--prefix", "s-"],
            cwd=self.repo.root, check=True, capture_output=True, env=self.repo.env(),
        )

    def gates(self, *options, returncode=0, **overrides):
        calls = self.repo.temp / "tests.calls"
        checks = {
            "HOST_CHECK_ACTIVE": "1", "TYPECHECK_CMD": "true", "LINT_CMD": "true", "FORMAT_CMD": "true",
            "TEST_CMD": f'echo "$(git rev-parse --abbrev-ref HEAD) $1" >> {calls}; :', **overrides,
        }
        result = subprocess.run(
            ["bash", str(HERE / "layer_gates.sh"), "--manifests", str(self.repo.manifests), "--prefix", "s-",
             "--base", "main", "--no-setup", *options],
            cwd=self.repo.root, text=True, capture_output=True, env=self.repo.env(**checks),
        )
        self.assertEqual(result.returncode, returncode, result.stdout + result.stderr)
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

    def test_commits_check_each_intermediate_commit_on_its_own_changes(self):
        typecheck = self.repo.temp / "typecheck.calls"
        _calls, verdicts = self.gates(TYPECHECK_CMD=f'echo "$(git rev-parse HEAD)" >> {typecheck}; :')
        intermediate, tip, b, c = self.repo.git("rev-parse", "s-01-a~1", "s-01-a", "s-02-b", "s-03-c").split()
        self.assertEqual(typecheck.read_text().splitlines(), [intermediate, tip, b, c])
        self.assertIn("commits=OK", verdicts["01-a"])
        self.assertIn("commits=none", verdicts["02-b"])
        self.assertIn("commits=none", verdicts["03-c"])

    def test_a_failing_intermediate_commit_fails_the_layer_but_not_the_tip(self):
        intermediate = self.repo.git("rev-parse", "s-01-a~1")
        _calls, verdicts = self.gates(
            returncode=1, TYPECHECK_CMD=f'[ "$(git rev-parse HEAD)" != "{intermediate}" ] || exit 1; :',
        )
        self.assertIn("commits=FAIL", verdicts["01-a"])
        self.assertIn("typecheck=OK", verdicts["01-a"])

    def test_a_broken_commit_on_a_merged_side_branch_fails_the_layer(self):
        self.repo.git("checkout", "-q", "-b", "side", "s-02-b")
        (self.repo.root / "broken.ts").write_text("broken\n")
        self.repo.git("add", "-A")
        self.repo.git("commit", "-q", "-m", "break")
        self.repo.git("rm", "-q", "broken.ts")
        self.repo.git("commit", "-q", "-m", "repair")
        self.repo.git("checkout", "-q", "s-03-c")
        self.repo.git("merge", "-q", "--no-ff", "-m", "merge side", "side")
        self.repo.git("checkout", "-q", "main")
        _calls, verdicts = self.gates(returncode=1, TYPECHECK_CMD="[ ! -f broken.ts ] || exit 1; :")
        self.assertIn("commits=FAIL", verdicts["03-c"])
        self.assertIn("typecheck=OK", verdicts["03-c"])


if __name__ == "__main__":
    unittest.main()
