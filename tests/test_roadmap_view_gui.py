"""RoadmapView : phases, cases cliquables, fichier changé, écran vide. Sans affichage réel."""

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from tests.helpers import gui_ready

GTK = gui_ready()
if GTK:
    from gi.repository import GLib
    from ccs_app.gui import roadmap_view

TEXT = """# Projet

## Phase 1 — Base (0.1.0) ✅
- [x] a
- [x] b

## Phase 2 — Suite (0.2.0)
- [x] c
- [ ] d
- [ ] e
"""


def pump(cond, timeout=5.0):
    ctx = GLib.MainContext.default()
    end = time.time() + timeout
    while time.time() < end:
        while ctx.iteration(False):
            pass
        if cond():
            return True
        time.sleep(0.01)
    return cond()


@unittest.skipUnless(GTK, "affichage de test indisponible (CCS_GUI_TESTS=1 xvfb-run)")
class RoadmapViewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccs-rv-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.file = self.tmp / "ROADMAP.md"
        self.file.write_text(TEXT)

    def view(self, **kw):
        v = roadmap_view.RoadmapView(self.tmp, **kw)
        self.addCleanup(v.close)
        self.assertTrue(pump(lambda: v.loaded))
        return v

    def test_phases_and_progress(self):
        v = self.view()
        self.assertEqual([p.title for p, _r in v.phase_rows],
                         ["Phase 1 — Base (0.1.0) ✅", "Phase 2 — Suite (0.2.0)"])
        self.assertFalse(v.phase_rows[0][1].get_expanded())   # finie : repliée
        self.assertTrue(v.phase_rows[1][1].get_expanded())    # non finie : dépliée
        self.assertIn("1 phase finie sur 2", v.header_info.get_label())
        self.assertIn("0.1.0", v.header_info.get_label())
        self.assertEqual(len(v.task_rows), 5)

    def test_click_toggles_file(self):
        v = self.view()
        v.task_rows[6].check.set_active(True)    # « d »
        self.assertTrue(pump(lambda: "- [x] d" in self.file.read_text()))
        self.assertEqual(self.file.read_text(), TEXT.replace("- [ ] d", "- [x] d"))
        self.assertTrue(pump(lambda: v.task_rows[6].check.get_active()))

    def test_changed_file_toast_and_reload(self):
        v = self.view()
        self.file.write_text(TEXT.replace("- [ ] d", "- [ ] autre"))
        v.task_rows[6].check.set_active(True)
        self.assertTrue(pump(lambda: v.last_toast is not None))
        self.assertEqual(v.last_toast, "La feuille de route a changé, relue")
        self.assertIn("- [ ] autre", self.file.read_text())
        self.assertTrue(pump(lambda: v.task_rows.get(6) is not None
                             and v.task_rows[6].get_title() == "autre"))

    def test_external_check_highlighted(self):
        v = self.view()
        self.file.write_text(TEXT.replace("- [ ] e", "- [x] e"))
        self.assertTrue(pump(lambda: v.task_rows[7].has_css_class("ccs-just-done")))
        self.assertFalse(v.task_rows[6].has_css_class("ccs-just-done"))

    def test_no_roadmap_status_page(self):
        self.file.unlink()
        asked = []
        v = self.view(on_ask_create=lambda: asked.append(1))
        self.assertIsNone(v.roadmap)
        self.assertIsNotNone(v.ask_button)
        v.ask_button.emit("clicked")
        self.assertEqual(asked, [1])
        # le fichier apparaît : la vue se met à jour
        self.file.write_text(TEXT)
        self.assertTrue(pump(lambda: v.roadmap is not None))


if __name__ == "__main__":
    unittest.main()
