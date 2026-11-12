"""Fichier ouvert (GTK, affichage requis) : sous Xvfb seulement."""

import os
import tempfile
import unittest
from pathlib import Path

from tests.helpers import gui_ready

GTK = gui_ready()
if GTK:
    from gi.repository import GLib

    from ccs_app.gui.file_editor import FileEditor


def spin(until, timeout=8.0):
    ctx = GLib.MainContext.default()
    deadline = GLib.get_monotonic_time() + int(timeout * 1e6)
    while not until() and GLib.get_monotonic_time() < deadline:
        ctx.iteration(False)
    return until()


@unittest.skipUnless(GTK, "affichage graphique requis (CCS_GUI_TESTS=1 sous xvfb-run)")
class FileEditorGuiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ccs-test-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.ed = FileEditor()

    def open_text(self, name, content="un\ndeux\n"):
        p = self.root / name
        p.write_text(content)
        self.ed.open(p)
        self.assertTrue(spin(lambda: self.ed.state(p) in ("text", "too_big")))
        return p

    def test_open_save_clears_dirty(self):
        p = self.open_text("a.py", "print(1)\n")
        self.assertEqual(self.ed.text(p), "print(1)\n")
        self.assertFalse(self.ed.is_dirty(p))
        self.ed.set_text(p, "print(2)\n")
        self.assertTrue(self.ed.is_dirty(p))
        self.ed.save(p)
        self.assertTrue(spin(lambda: not self.ed.is_dirty(p)))
        self.assertEqual(p.read_text(), "print(2)\n")

    def test_external_change_reloads_clean_file(self):
        p = self.open_text("b.txt", "avant\n")
        p.write_text("après, plus long\n")
        self.ed.check_changes()
        self.assertTrue(spin(lambda: self.ed.text(p) == "après, plus long\n"))
        self.assertFalse(self.ed.is_dirty(p))

    def test_external_change_with_edits_shows_banner_and_keeps_text(self):
        p = self.open_text("c.txt", "avant\n")
        self.ed.set_text(p, "mes changements\n")
        p.write_text("version disque, différente\n")
        self.ed.check_changes()
        self.assertTrue(spin(lambda: self.ed.doc(p).notice is not None))
        self.assertEqual(self.ed.text(p), "mes changements\n")
        self.assertTrue(self.ed.is_dirty(p))
        # « Voir les différences » ouvre un diff sans toucher au texte
        self.ed._show_conflict_diff(self.ed.doc(p))
        self.assertTrue(spin(lambda: self.ed.diff_text(p) is not None))
        self.assertIn("mes changements", self.ed.diff_text(p))
        self.assertEqual(self.ed.text(p), "mes changements\n")
        # « Prendre la version du disque »
        self.ed._take_disk(self.ed.doc(p))
        self.assertTrue(spin(lambda: self.ed.text(p) == "version disque, différente\n"))
        self.assertFalse(self.ed.is_dirty(p))

    def test_markdown_preview_toggle(self):
        p = self.open_text("d.md", "# Titre\n\ntexte\n")
        d = self.ed.doc(p)
        self.assertEqual(d.stack.get_visible_child_name(), "source")
        d.toggle[1].set_active(True)
        self.assertEqual(d.stack.get_visible_child_name(), "preview")
        self.assertIsNotNone(d.preview)
        d.toggle[0].set_active(True)
        self.assertEqual(d.stack.get_visible_child_name(), "source")

    def test_deleted_file_shows_status(self):
        p = self.open_text("e.txt", "x\n")
        p.unlink()
        self.ed.check_changes()
        self.assertTrue(spin(lambda: self.ed.state(p) == "missing"))
        absent = self.root / "nope.txt"
        self.ed.open(absent)
        self.assertTrue(spin(lambda: self.ed.state(absent) == "missing"))

    def test_hostile_files(self):
        b = self.root / "b.bin"
        b.write_bytes(b"ab\0cd")
        self.ed.open(b)
        self.assertTrue(spin(lambda: self.ed.state(b) == "binary"))
        big = self.root / "big.txt"
        big.write_bytes(b"x\n" * (1024 * 1024 + 10))
        self.ed.open(big)
        self.assertTrue(spin(lambda: self.ed.state(big) == "too_big"))
        self.assertTrue(self.ed.doc(big).readonly)
        l1 = self.root / "l.txt"
        l1.write_bytes("café".encode("latin-1"))
        self.ed.open(l1)
        self.assertTrue(spin(lambda: self.ed.state(l1) == "text"))
        self.assertEqual(self.ed.text(l1), "café")

    def test_diff_view(self):
        p = self.root / "f.txt"
        self.ed.show_diff(p, "a\nb\n", "a\nc\n")
        text = self.ed.diff_text(p)
        self.assertIn("-b", text)
        self.assertIn("+c", text)
        self.assertEqual(self.ed.paths(), [])

    def test_empty_signal_and_close_confirmation(self):
        p = self.open_text("g.txt", "x\n")
        fired = []
        self.ed.connect("empty", lambda _e: fired.append(1))
        self.ed.set_text(p, "y\n")
        self.ed.close(p)  # modifié : une confirmation s'ouvre, l'onglet reste
        self.assertEqual(self.ed.state(p), "text")
        self.assertEqual(fired, [])
        self.ed._last_dialog.emit("response", "discard")
        self.assertTrue(spin(lambda: fired))
        self.assertIsNone(self.ed.state(p))


if __name__ == "__main__":
    unittest.main()
