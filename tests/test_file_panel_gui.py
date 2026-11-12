"""Panneau Fichiers (GTK, affichage requis) : sous Xvfb seulement."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import gui_ready

GTK = gui_ready()
if GTK:
    from gi.repository import GLib

    from ccs_app.gui.file_panel import FileTree


def spin(until, timeout=8.0):
    ctx = GLib.MainContext.default()
    deadline = GLib.get_monotonic_time() + int(timeout * 1e6)
    while not until() and GLib.get_monotonic_time() < deadline:
        ctx.iteration(False)
    return until()


def git(root, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=root, check=True, capture_output=True)


@unittest.skipUnless(GTK, "affichage graphique requis (CCS_GUI_TESTS=1 sous xvfb-run)")
class FileTreeGuiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ccs-test-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def names(self, tree):
        return [r[0] for r in tree.rows()]

    def test_lists_root_hides_git_dir(self):
        git(self.root, "init", "-q")
        (self.root / "src").mkdir()
        (self.root / "src" / "m.py").write_text("x")
        (self.root / "node_modules").mkdir()
        (self.root / "a.txt").write_text("a")
        (self.root / ".gitignore").write_text("secret.txt\n")
        (self.root / "secret.txt").write_text("s")
        tree = FileTree(self.root, lambda p: None)
        self.assertTrue(spin(lambda: "a.txt" in self.names(tree)))
        names = self.names(tree)
        self.assertEqual(names[0], "src")  # dossiers d'abord
        self.assertNotIn(".git", names)
        self.assertNotIn("node_modules", names)
        self.assertNotIn("secret.txt", names)
        self.assertIn(".gitignore", names)
        tree.expand("src")
        self.assertTrue(spin(lambda: "m.py" in self.names(tree)))
        self.assertEqual(tree.rows()[1], ("m.py", 1, "?"))

    def test_show_ignored(self):
        git(self.root, "init", "-q")
        (self.root / ".gitignore").write_text("secret.txt\n")
        (self.root / "secret.txt").write_text("s")
        tree = FileTree(self.root, lambda p: None)
        self.assertTrue(spin(lambda: ".gitignore" in self.names(tree)))
        tree.set_show_ignored(True)
        self.assertTrue(spin(lambda: "secret.txt" in self.names(tree)))
        self.assertNotIn(".git", self.names(tree))

    def test_symlink_loop_not_followed(self):
        (self.root / "d").mkdir()
        (self.root / "d" / "f.txt").write_text("f")
        os.symlink(self.root, self.root / "d" / "loop")
        os.symlink(self.root / "d", self.root / "lien")
        tree = FileTree(self.root, lambda p: None)
        self.assertTrue(spin(lambda: "d" in self.names(tree)))
        tree.expand("d")
        self.assertTrue(spin(lambda: "loop" in self.names(tree)))
        n = len(self.names(tree))
        # le lien n'est pas un dossier : on ne peut pas le déplier
        self.assertFalse(tree.model.get_item(tree.row_index("d/loop")).is_expandable())
        self.assertFalse(tree.model.get_item(tree.row_index("lien")).is_expandable())
        spin(lambda: False, 0.7)
        self.assertEqual(len(self.names(tree)), n)

    def test_marks_shown(self):
        git(self.root, "init", "-q")
        (self.root / "a.txt").write_text("a")
        (self.root / "b.txt").write_text("b")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "x")
        (self.root / "a.txt").write_text("changé")
        (self.root / "n.txt").write_text("n")
        (self.root / "b.txt").unlink()
        tree = FileTree(self.root, lambda p: None)
        self.assertTrue(spin(lambda: ("a.txt", 0, "M") in tree.rows()))
        rows = tree.rows()
        self.assertIn(("n.txt", 0, "?"), rows)
        self.assertIn(("b.txt", 0, "D"), rows)

    def test_new_file_appears_and_activation_opens(self):
        opened = []
        (self.root / "a.txt").write_text("a")
        tree = FileTree(self.root, opened.append)
        self.assertTrue(spin(lambda: "a.txt" in self.names(tree)))
        (self.root / "z.txt").write_text("z")
        self.assertTrue(spin(lambda: "z.txt" in self.names(tree)))
        tree.list_view.emit("activate", tree.row_index("z.txt"))
        self.assertEqual(opened, [str(self.root / "z.txt")])

    def test_insert_reference_signal(self):
        (self.root / "a.txt").write_text("a")
        tree = FileTree(self.root, lambda p: None)
        got = []
        tree.connect("insert-reference", lambda _t, rel: got.append(rel))
        self.assertTrue(spin(lambda: "a.txt" in self.names(tree)))
        tree._menu_node = tree.model.get_item(0).get_item()
        tree._act_insert()
        self.assertEqual(got, ["a.txt"])


if __name__ == "__main__":
    unittest.main()
