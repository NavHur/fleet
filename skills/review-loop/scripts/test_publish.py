"""Publish's failure paths: a failing gh is a clean error, and the body file never lingers."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("loop.py")

FAKE_GH = """\
#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if args[0] != "api":
    sys.exit("fake gh: only gh api is allowed")
if os.environ["FAKE_GH_FAIL"] in " ".join(args):
    sys.exit("HTTP 502: bad gateway")
if args[1] == "repos/acme/app/pulls/7":
    print(json.dumps({"head": {"sha": os.environ["FAKE_GH_HEAD"]}, "base": {"ref": "main"}}))
"""


class PublishFailureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.repo, self.tmp, self.bin = root / "repo", root / "tmp", root / "bin"
        for path in (self.repo, self.tmp, self.bin):
            path.mkdir()
        subprocess.run(["git", "init", "--quiet"], cwd=self.repo, check=True)
        subprocess.run(["git", "remote", "add", "origin", "git@github.com:acme/app.git"], cwd=self.repo, check=True)
        self.loop = root / "loop"
        (self.loop / "r1").mkdir(parents=True)
        (self.loop / "r1" / "heads.tsv").write_text(f"7\tbranch\t{'a' * 40}\t{'b' * 40}\n")
        (self.bin / "gh").write_text(FAKE_GH)
        (self.bin / "gh").chmod(0o755)

    def publish(self, fail):
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "TMPDIR": str(self.tmp),
               "FAKE_GH_FAIL": fail, "FAKE_GH_HEAD": "b" * 40}
        result = subprocess.run([sys.executable, str(SCRIPT), "publish", str(self.loop), "--checkout", str(self.repo)],
                                capture_output=True, text=True, env=env)
        return result.returncode, result.stdout + result.stderr

    def test_a_failing_comment_listing_is_a_clean_error(self):
        code, out = self.publish("issues/7/comments")
        self.assertEqual(code, 2)
        self.assertIn("loop.py: gh api repos/acme/app/issues/7/comments", out)
        self.assertIn("HTTP 502", out)
        self.assertNotIn("Traceback", out)

    def test_a_failing_post_is_a_clean_error_and_leaves_no_body_file(self):
        code, out = self.publish("POST")
        self.assertEqual(code, 2)
        self.assertIn("HTTP 502", out)
        self.assertNotIn("Traceback", out)
        self.assertEqual(list(self.tmp.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
