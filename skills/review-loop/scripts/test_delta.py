"""Drive delta.py between two rounds' heads files over a temporary stack."""

from pathlib import Path
import subprocess
import sys
import unittest

SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS / "split-stacked-prs" / "scripts"))

from stack_fixture import StackRepo  # noqa: E402

DELTA = Path(__file__).with_name("delta.py")


def lines(count, width=49):
    """`count` lines that each add `width` + 1 bytes to a diff: the marker plus `width` characters."""
    return "".join(f"line {index}".ljust(width) + "\n" for index in range(count))


class DeltaTests(unittest.TestCase):
    def setUp(self):
        self.repo = StackRepo(self)
        self.out = self.repo.root.parent / "r2"
        self.main = self.repo.git("rev-parse", "main")
        self.r1 = self.repo.branch("s-01-a", "main", {"a.ts": "a\n", "notes.txt": "n\n"})

    def heads(self, name, rows):
        path = self.repo.root.parent / name
        path.write_text("".join("\t".join(row) + "\n" for row in rows))
        return str(path)

    def delta(self, prev, heads, *args, cwd=None):
        result = subprocess.run([sys.executable, str(DELTA), "--prev", prev, "--heads", heads, "--out", str(self.out),
                                 "--repo", str(self.repo.root), *args], capture_output=True, text=True, cwd=cwd)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_a_changed_layer_reports_its_size_and_audit_and_writes_its_diff(self):
        r2 = self.repo.branch("r2", "s-01-a", {"a.ts": "a\n" + lines(100)})
        prev = self.heads("prev.tsv", [("7", "01-a", self.main, self.r1)])
        out = self.delta(prev, self.heads("heads.tsv", [("7", "01-a", self.main, r2)]))
        self.assertEqual(out, f"7 01-a: 5.0 KB, audit=yes -> {self.out}/delta-7.diff\n")
        self.assertIn("+line 99", (self.out / "delta-7.diff").read_text())

    def test_a_small_delta_in_an_audited_language_skips_the_audit(self):
        r2 = self.repo.branch("r2", "s-01-a", {"a.ts": "a\n" + lines(50)})
        prev = self.heads("prev.tsv", [("7", "01-a", self.main, self.r1)])
        out = self.delta(prev, self.heads("heads.tsv", [("7", "01-a", self.main, r2)]))
        self.assertEqual(out, f"7 01-a: 2.5 KB, audit=no (under 3 KB) -> {self.out}/delta-7.diff\n")

    def test_relative_heads_paths_resolve_from_the_working_directory_not_the_repo(self):
        r2 = self.repo.branch("r2", "s-01-a", {"a.ts": "a\n" + lines(100)})
        self.heads("prev.tsv", [("7", "01-a", self.main, self.r1)])
        self.heads("heads.tsv", [("7", "01-a", self.main, r2)])
        out = self.delta("prev.tsv", "heads.tsv", cwd=self.repo.root.parent)
        self.assertEqual(out, f"7 01-a: 5.0 KB, audit=yes -> {self.out}/delta-7.diff\n")

    def test_a_branch_in_the_pr_column_names_an_encoded_delta_file(self):
        r2 = self.repo.branch("r2", "s-01-a", {"a.ts": "a\n" + lines(100)})
        prev = self.heads("prev.tsv", [("pedro/feature", "01-a", self.main, self.r1)])
        out = self.delta(prev, self.heads("heads.tsv", [("pedro/feature", "01-a", self.main, r2)]))
        self.assertEqual(out, f"pedro/feature 01-a: 5.0 KB, audit=yes -> {self.out}/delta-pedro%2Ffeature.diff\n")
        self.assertIn("+line 99", (self.out / "delta-pedro%2Ffeature.diff").read_text())

    def test_an_unknown_previous_head_exits_2_with_gits_message(self):
        prev = self.heads("prev.tsv", [("7", "01-a", self.main, "f" * 40)])
        result = subprocess.run([sys.executable, str(DELTA), "--prev", prev, "--heads",
                                 self.heads("heads.tsv", [("7", "01-a", self.main, self.r1)]), "--out", str(self.out),
                                 "--repo", str(self.repo.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("fatal:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_a_pr_new_this_round_is_reviewed_whole(self):
        prev = self.heads("prev.tsv", [])
        out = self.delta(prev, self.heads("heads.tsv", [("7", "01-a", self.main, self.r1)]))
        self.assertEqual(out, "7 01-a: new in this round, review it whole\n")

    def test_manifests_keep_changes_to_other_layers_files_out(self):
        r2 = self.repo.branch("r2", "s-01-a", {"b.ts": "carried\n"})
        manifests = self.repo.manifests
        self.repo.manifest("01-a", "# base: main\na.ts\n~notes.txt\n")
        prev = self.heads("prev.tsv", [("7", "01-a", self.main, self.r1)])
        out = self.delta(prev, self.heads("heads.tsv", [("7", "01-a", self.main, r2)]), "--manifests", str(manifests))
        self.assertEqual(out, "7 01-a: no delta\n")
        self.assertFalse((self.out / "delta-7.diff").exists())

    def test_a_file_that_becomes_a_symlink_counts_both_sides(self):
        before = self.repo.branch("before", "main", {"doc.txt": lines(100)})
        self.repo.git("checkout", "-q", "-b", "after", "before")
        (self.repo.root / "doc.txt").unlink()
        (self.repo.root / "doc.txt").symlink_to("t")
        after = self.repo.commit({}, "symlink")
        self.repo.git("checkout", "-q", "main")
        prev = self.heads("prev.tsv", [("7", "01-a", self.main, before)])
        out = self.delta(prev, self.heads("heads.tsv", [("7", "01-a", self.main, after)]))
        self.assertEqual(out, f"7 01-a: 5.0 KB, audit=no -> {self.out}/delta-7.diff\n")


if __name__ == "__main__":
    unittest.main()
