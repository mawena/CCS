"""GitPage : écrans vides, dispositions A, B, C, erreurs, fetch automatique. Sous Xvfb."""

import unittest
from unittest import mock

from tests.git_helpers import GitTestCase, commit_file
from tests.helpers import gui_ready

GTK = gui_ready()
if GTK:
    from gi.repository import GLib
    from ccs_app import git_repo
    from ccs_app.gui import git_page
    from ccs_app.gui.git_page import GitPage


def spin(until, timeout=8.0):
    ctx = GLib.MainContext.default()
    deadline = GLib.get_monotonic_time() + int(timeout * 1e6)
    while not until() and GLib.get_monotonic_time() < deadline:
        ctx.iteration(False)
    return until()


@unittest.skipUnless(GTK, "affichage graphique requis (CCS_GUI_TESTS=1 sous xvfb-run)")
class GitPageTest(GitTestCase):
    def setUp(self):
        super().setUp()
        self.opened = []
        self.layouts = []
        self.pages = []

    def page(self, cwd=None, layout="A"):
        with mock.patch.object(git_page, "_saved_layout", return_value=layout):
            p = GitPage(str(cwd or self.repo),
                        lambda key, title, w: self.opened.append((key, title, w)),
                        self.layouts.append)
        self.pages.append(p)
        return p

    def tearDown(self):
        super().tearDown()
        for p in self.pages:
            p.close()

    def test_not_a_repo_shows_empty(self):
        other = self.repo.parent / "pas-un-depot"
        other.mkdir()
        p = self.page(other)
        self.assertTrue(spin(lambda: p.empty_shown()))
        self.assertFalse(p.banner.get_revealed())

    def test_layout_a_opens_commit_in_editor(self):
        cid = commit_file(self.repo, "a.txt", "un\n")
        p = self.page(layout="A")
        self.assertTrue(spin(lambda: p.graph.commit_count() == 1))
        p.graph.activate(cid)
        self.assertEqual(len(self.opened), 1)
        key, title, widget = self.opened[0]
        self.assertEqual(key, f"commit:{cid}")
        self.assertEqual(title, f"Commit {cid[:7]}")
        self.assertTrue(spin(lambda: widget.loaded()))

    def test_layout_b_opens_history_tab(self):
        commit_file(self.repo, "a.txt", "un\n")
        p = self.page(layout="A")
        self.assertTrue(spin(lambda: p.graph.commit_count() == 1))
        p.set_layout("B")
        self.assertEqual(p.layout(), "B")
        self.assertEqual([o[0] for o in self.opened], ["git:historique"])
        self.assertEqual(self.opened[0][1], "Historique")
        self.assertEqual(self.layouts, ["B"])

    def test_error_banner_details(self):
        commit_file(self.repo, "a.txt", "un\n")
        p = self.page()
        self.assertTrue(spin(lambda: p.graph.commit_count() == 1))
        p.push()
        self.assertTrue(spin(lambda: p.banner.get_revealed()))
        self.assertIn("distant", p.error_details())
        self.assertIn("git push", p.error_details())

    def test_auto_fetch_only_when_visible(self):
        commit_file(self.repo, "a.txt", "un\n")
        p = self.page()
        with mock.patch.object(git_repo, "fetch") as fetch, \
                mock.patch.object(p, "_visible", return_value=False):
            p._last_fetch = -1e9
            p._tick()
            spin(lambda: False, 0.3)
            fetch.assert_not_called()
        with mock.patch.object(git_repo, "fetch") as fetch, \
                mock.patch.object(p, "_visible", return_value=True):
            p._last_fetch = -1e9
            p._tick()
            self.assertTrue(spin(lambda: fetch.call_count == 1))

    def test_disk_change_refreshes(self):
        commit_file(self.repo, "a.txt", "un\n")
        p = self.page()
        self.assertTrue(spin(lambda: p.graph.commit_count() == 1))
        commit_file(self.repo, "b.txt", "deux\n")
        self.assertTrue(spin(lambda: p.graph.commit_count() == 2, 10))


if __name__ == "__main__":
    unittest.main()
