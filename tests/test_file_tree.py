"""Fichiers d'un projet (sans GTK) : marques git, types, lecture, écriture."""

import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from ccs_app import file_tree


def git(root, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=root, check=True, capture_output=True)


class FileTreeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ccs-test-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_git_marks_porcelain(self):
        git(self.root, "init", "-q")
        (self.root / "a.txt").write_text("a")
        (self.root / "b.txt").write_text("b")
        (self.root / "gone.txt").write_text("g")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "x")
        (self.root / "a.txt").write_text("changé")
        (self.root / "gone.txt").unlink()
        (self.root / "new.txt").write_text("n")
        (self.root / "added.txt").write_text("n")
        git(self.root, "add", "added.txt")
        (self.root / "dir").mkdir()
        (self.root / "dir" / "deep.txt").write_text("d")
        marks = file_tree.git_marks(self.root)
        self.assertEqual(marks["a.txt"], "M")
        self.assertEqual(marks["gone.txt"], "D")
        self.assertEqual(marks["new.txt"], "?")
        self.assertEqual(marks["added.txt"], "A")
        self.assertEqual(marks["dir/deep.txt"], "?")
        self.assertNotIn("b.txt", marks)

    def test_ignored(self):
        git(self.root, "init", "-q")
        (self.root / ".gitignore").write_text("*.log\n")
        self.assertEqual(file_tree.ignored(self.root, ["x.log", "y.txt"]), {"x.log"})
        self.assertEqual(file_tree.ignored(self.root, []), set())

    def test_not_git_no_marks(self):
        (self.root / "a.txt").write_text("a")
        self.assertEqual(file_tree.git_marks(self.root), {})
        self.assertEqual(file_tree.git_marks(self.root / "absent"), {})

    def test_binary_and_too_big(self):
        text = self.root / "t.txt"
        text.write_text("bonjour")
        binf = self.root / "b.bin"
        binf.write_bytes(b"abc\0def")
        big = self.root / "big.txt"
        big.write_bytes(b"a" * (file_tree.MAX_EDIT_BYTES + 1))
        img = self.root / "i.PNG"
        img.write_bytes(b"\x89PNG")
        self.assertEqual(file_tree.kind(text), "text")
        self.assertEqual(file_tree.kind(binf), "binary")
        self.assertEqual(file_tree.kind(big), "too_big")
        self.assertEqual(file_tree.kind(img), "image")
        self.assertEqual(file_tree.kind(self.root / "nope"), "missing")
        self.assertEqual(file_tree.kind(self.root), "missing")

    def test_latin1_read_and_save_round_trip(self):
        p = self.root / "l.txt"
        p.write_bytes("café\n".encode("latin-1"))
        text, enc = file_tree.read_text(p)
        self.assertEqual((text, enc), ("café\n", "latin-1"))
        file_tree.save(p, text + "é", enc)
        self.assertEqual(p.read_bytes(), "café\né".encode("latin-1"))
        u = self.root / "u.txt"
        u.write_text("é", encoding="utf-8")
        self.assertEqual(file_tree.read_text(u), ("é", "utf-8"))

    def test_save_keeps_mode(self):
        p = self.root / "run.sh"
        p.write_text("#!/bin/sh\n")
        p.chmod(0o750)
        file_tree.save(p, "#!/bin/sh\necho\n")
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o750)
        self.assertEqual(p.read_text(), "#!/bin/sh\necho\n")
        self.assertEqual([f.name for f in self.root.iterdir()], ["run.sh"])

    def test_changed_detects_external_write(self):
        p = self.root / "c.txt"
        p.write_text("un")
        s = file_tree.stamp(p)
        self.assertFalse(file_tree.changed(p, s))
        time.sleep(0.01)
        p.write_text("deux")
        self.assertTrue(file_tree.changed(p, s))
        p.unlink()
        self.assertTrue(file_tree.changed(p, s))


if __name__ == "__main__":
    unittest.main()
