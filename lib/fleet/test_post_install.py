from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
import post_install  # noqa: E402

BLOCK = f"{post_install.BLOCK_START}\nshared\n{post_install.BLOCK_END}\n"


class HostText(unittest.TestCase):
    def setUp(self):
        self.host = Path(tempfile.mkdtemp())

    def test_shared_then_agent_file(self):
        (self.host / "instructions.md").write_text("# Mac\n\n- shared rule\n")
        (self.host / "instructions.codex.md").write_text("## Plan names\n")
        self.assertEqual(post_install.host_text(self.host, "codex"), "# Mac\n\n- shared rule\n\n## Plan names\n\n")
        self.assertEqual(post_install.host_text(self.host, "claude"), "# Mac\n\n- shared rule\n\n")

    def test_no_files_leaves_the_host_unmanaged(self):
        self.assertIsNone(post_install.host_text(self.host, "claude"))


class WithHost(unittest.TestCase):
    def test_replaces_everything_above_the_block(self):
        text = "# Old heading\n\n- old rule\n\n" + BLOCK + "after\n"
        self.assertEqual(post_install.with_host(text, "# Mac\n\n"), "# Mac\n\n" + BLOCK + "after\n")


if __name__ == "__main__":
    unittest.main()
