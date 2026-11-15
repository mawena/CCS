"""GraphView : graphe des commits en deux densités, chargé par pages. Sous Xvfb."""

import unittest
from unittest import mock

from tests.git_helpers import GitTestCase, commit_file, g, many_commits
from tests.helpers import gui_ready

GTK = gui_ready()
if GTK:
    import cairo
    from gi.repository import GLib
    from ccs_app.gui import git_graph_view
    from ccs_app.gui.git_graph_view import GraphView


def spin(until, timeout=8.0):
    ctx = GLib.MainContext.default()
    deadline = GLib.get_monotonic_time() + int(timeout * 1e6)
    while not until() and GLib.get_monotonic_time() < deadline:
        ctx.iteration(False)
    return until()


def paint(view, w=480, h=600):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    view.paint(cairo.Context(surface), w, h)


@unittest.skipUnless(GTK, "affichage graphique requis (CCS_GUI_TESTS=1 sous xvfb-run)")
class GraphViewTest(GitTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(git_graph_view, "_avatars_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_loads_first_page_then_more(self):
        many_commits(self.repo, 450)
        view = GraphView("compact")
        view.load(str(self.repo))
        self.assertTrue(spin(lambda: view.commit_count() == 200))
        view.load_more()
        self.assertTrue(spin(lambda: view.commit_count() == 400))
        view.load_more()
        self.assertTrue(spin(lambda: view.commit_count() == 450))
        view.load_more()                 # plus rien : ne bouge pas, ne plante pas
        self.assertTrue(spin(lambda: not view.loading()))
        self.assertEqual(view.commit_count(), 450)
        paint(view)

    def test_activate_emits_cid(self):
        c1 = commit_file(self.repo, "a.txt", "a\n")
        c2 = commit_file(self.repo, "b.txt", "b\n")
        view = GraphView("compact")
        got = []
        view.connect("commit-activated", lambda _v, cid: got.append(cid))
        view.load(str(self.repo))
        self.assertTrue(spin(lambda: view.commit_count() == 2))
        x, y = view.node_position(c1)
        self.assertEqual(view.node_at(x, y), c1)
        self.assertIsNone(view.node_at(x, y + 1000))
        view.activate(c1)
        self.assertEqual((got, view.selected()), ([c1], c1))
        self.assertNotEqual(view.node_position(c2), (x, y))

    def test_switch_density_keeps_selection(self):
        commit_file(self.repo, "a.txt", "a\n")
        g(self.repo, "checkout", "-q", "-b", "feature/x")
        side = commit_file(self.repo, "b.txt", "b\n")
        g(self.repo, "checkout", "-q", "main")
        commit_file(self.repo, "c.txt", "c\n")
        view = GraphView("compact")
        view.load(str(self.repo))
        self.assertTrue(spin(lambda: view.commit_count() == 3))
        view.select(side)
        paint(view)
        view.set_density("cards")
        self.assertEqual(view.selected(), side)
        paint(view)
        x, y = view.node_position(side)
        self.assertEqual(view.node_at(x, y), side)

    def test_no_avatar_fetch_when_disabled(self):
        commit_file(self.repo, "a.txt", "a\n")
        with mock.patch.object(git_graph_view, "_avatars_enabled", return_value=False), \
                mock.patch.object(git_graph_view.avatars, "fetch") as fetch:
            view = GraphView("cards")
            view.load(str(self.repo))
            self.assertTrue(spin(lambda: view.commit_count() == 1))
            paint(view)
            spin(lambda: False, 0.3)
            fetch.assert_not_called()

    def test_avatar_fetched_once_when_enabled(self):
        commit_file(self.repo, "a.txt", "a\n")
        commit_file(self.repo, "b.txt", "b\n")
        with mock.patch.object(git_graph_view.avatars, "fetch", return_value=None) as fetch:
            view = GraphView("cards")
            view.load(str(self.repo))
            self.assertTrue(spin(lambda: view.commit_count() == 2))
            paint(view)
            paint(view)
            self.assertTrue(spin(lambda: fetch.call_count == 1))
            spin(lambda: False, 0.2)
            self.assertEqual(fetch.call_count, 1)    # même auteur : une seule demande

    def test_not_a_repo_is_empty(self):
        other = self.repo.parent / "vide"
        other.mkdir()
        view = GraphView("compact")
        errors = []
        view.connect("load-failed", lambda _v, text: errors.append(text))
        view.load(str(other))
        self.assertTrue(spin(lambda: errors))
        self.assertEqual(view.commit_count(), 0)
        paint(view)


if __name__ == "__main__":
    unittest.main()
