"""A temporary repository with a manifest directory beside it, for stack tests in any skill."""

import os
from pathlib import Path
import subprocess
import tempfile

IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class StackRepo:
    """`root` is a repository on `main` with one commit; `manifests` is an empty directory.

    `temp` holds both; `environ` is the environment every git call and `env()` start from.
    """

    def __init__(self, test):
        temp = tempfile.TemporaryDirectory()
        test.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        self.environ = {**os.environ, **IDENTITY}
        self.environ.pop("GIT_DIR", None)  # a hook's GIT_DIR would point every call at the outer repository
        self.root = self.temp / "repo"
        self.manifests = self.temp / "layers"
        self.root.mkdir()
        self.manifests.mkdir()
        self.git("init", "-q", "-b", "main")
        self.commit({"app.ts": "app\n"}, "base")
        cwd = os.getcwd()
        os.chdir(self.root)
        test.addCleanup(os.chdir, cwd)

    def env(self, **extra):
        return {**self.environ, **extra}

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True, env=self.environ).strip()

    def add_origin(self):
        """Create a bare `origin.git` beside the repository, add it as `origin`, and push `main`."""
        origin = self.temp / "origin.git"
        self.git("init", "-q", "--bare", "-b", "main", str(origin))
        self.git("remote", "add", "origin", str(origin))
        self.git("push", "-q", "origin", "main")
        return origin

    def manifest(self, name, text):
        (self.manifests / name).write_text(text)

    def commit(self, files, message):
        """Write `files` ({path: content, or None to delete}), commit them, and return the new SHA."""
        for path, content in files.items():
            target = self.root / path
            if content is None:
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def branch(self, name, start, files):
        """Create `name` at `start` with one commit of `files`; return its head."""
        self.git("checkout", "-q", "-b", name, start)
        head = self.commit(files, name)
        self.git("checkout", "-q", "main")
        return head
