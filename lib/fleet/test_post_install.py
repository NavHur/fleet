from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

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


class BlockText(unittest.TestCase):
    def setUp(self):
        self.skills = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(post_install, "SKILLS", self.skills)
        patcher.start()
        self.addCleanup(patcher.stop)

    def add_principle(self, name, description):
        (self.skills / f"principle-{name}").mkdir()
        (self.skills / f"principle-{name}" / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n")

    def test_agent_file_follows_the_shared_text(self):
        self.add_principle("a", "Apply always.")
        shared = post_install.SHARED.read_text().strip()
        codex = post_install.SHARED.with_name("instructions.codex.md").read_text().strip()
        self.assertIn(shared + "\n\n" + codex + "\n\n## Engineering principles", post_install.block_text("codex"))
        self.assertIn(shared + "\n\n## Engineering principles", post_install.block_text("claude"))

    def test_quotes_each_principle_without_its_path(self):
        self.add_principle("zeta", "Apply last.")
        self.add_principle("alpha", "Apply first.")
        block = post_install.block_text("claude")
        self.assertTrue(block.endswith("\n- **alpha**: Apply first.\n- **zeta**: Apply last.\n" + post_install.BLOCK_END + "\n"))
        self.assertNotIn("principles.md", block)
        self.assertIn("`~/.agents/skills/principle-zeta/SKILL.md`", post_install.index_text())

    def test_no_principles_leaves_the_section_out(self):
        shared = post_install.SHARED.read_text().strip()
        self.assertTrue(post_install.block_text("claude").endswith(shared + "\n" + post_install.BLOCK_END + "\n"))


class WithHost(unittest.TestCase):
    def test_replaces_everything_above_the_block(self):
        text = "# Old heading\n\n- old rule\n\n" + BLOCK + "after\n"
        self.assertEqual(post_install.with_host(text, "# Mac\n\n"), "# Mac\n\n" + BLOCK + "after\n")


if __name__ == "__main__":
    unittest.main()
