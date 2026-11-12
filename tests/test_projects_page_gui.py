"""ProjectsPage : cartes, détail (versions, graphique), ouverture d'une session."""

import os
import subprocess
import time
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.helpers import HomeTestCase, gui_ready
from tests.test_roadmap_view_gui import pump

GTK = gui_ready()
if GTK:
    from ccs_app.gui import projects_page

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]


def git(cwd, *args):
    subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True)


def conv(cwd):
    return SimpleNamespace(cwd=str(cwd), updated_at=time.time())


@unittest.skipUnless(GTK, "affichage de test indisponible (CCS_GUI_TESTS=1 xvfb-run)")
class ProjectsPageTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.proj = Path(self.tmp) / "Alpha"
        self.proj.mkdir()
        self.bare = Path(self.tmp) / "SansFeuille"
        self.bare.mkdir()
        git(self.proj, "init", "-q")
        (self.proj / "ROADMAP.md").write_text("# Alpha\n\n## Phase 1 (0.1.0)\n- [ ] a\n- [ ] b\n")
        git(self.proj, "add", "-A")
        git(self.proj, "commit", "-qm", "un")
        git(self.proj, "tag", "-a", "v0.1.0", "-m", "v0.1.0")
        (self.proj / "ROADMAP.md").write_text("# Alpha\n\n## Phase 1 (0.1.0)\n- [x] a\n- [ ] b\n")
        git(self.proj, "commit", "-qam", "deux")
        self.window = mock.Mock()
        scan = mock.patch("ccs_app.gui.projects_page.conversations.scan",
                          return_value=[conv(self.proj), conv(self.bare)])
        scan.start()
        self.addCleanup(scan.stop)
        self.page = projects_page.ProjectsPage(self.window)
        self.page.refresh()
        self.assertTrue(pump(lambda: self.page.loaded))

    def test_cards_for_projects_with_roadmap(self):
        self.assertEqual(list(self.page.cards), [str(self.proj)])
        self.assertEqual(self.page.stack.get_visible_child_name(), "cards")

    def test_hide_then_show_again(self):
        import json
        from ccs_app import settings
        card = self.page.cards[str(self.proj)]
        self.assertTrue(card.menu_button.get_menu_model().get_item_attribute_value(
            0, "label", None).get_string() == "Masquer ce projet")
        card.hide_action.activate(None)
        self.assertEqual(settings.load_settings()["projects"]["hidden"], [str(self.proj)])
        self.assertTrue(pump(lambda: not self.page.cards))
        self.assertEqual(self.page.stack.get_visible_child_name(), "empty")
        current = settings.load_settings()
        current["projects"]["hidden"] = []        # « Réafficher » des Réglages
        settings.save_settings(current)
        self.page.refresh()
        self.assertTrue(pump(lambda: list(self.page.cards) == [str(self.proj)]))

    def test_detail_shows_versions_and_chart(self):
        self.page.show_project(self.proj)
        self.assertTrue(pump(lambda: hasattr(self.page, "history")))
        labels = []
        w = self.page.versions_box.get_first_child()
        while w is not None:
            labels.append(w)
            w = w.get_next_sibling()
        self.assertEqual(len(labels), 1)
        self.assertEqual(self.page.chart.values[-1], (date.today(), 1))
        self.assertEqual(len(self.page.chart.values), projects_page.DAYS_SHOWN)
        self.assertTrue(pump(lambda: self.page.roadmap_view.loaded))
        self.assertEqual(self.page.nav.get_visible_page().get_title(), "Alpha")

    def test_open_session_button(self):
        self.page.show_project(self.proj)
        self.page.open_button.emit("clicked")
        self.window.open_session.assert_called_once_with(str(self.proj))


if __name__ == "__main__":
    unittest.main()
