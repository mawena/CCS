"""CommitView, DiffLinesView et ChangesView : indexation par fichier et par ligne, commit.
Sous Xvfb."""

import unittest
from unittest import mock

from tests.git_helpers import GitTestCase, commit_file, g
from tests.helpers import gui_ready

GTK = gui_ready()
if GTK:
    from gi.repository import Gdk, GLib
    from ccs_app import git_repo
    from ccs_app.gui.git_changes import ChangesView
    from ccs_app.gui.git_commit_view import CommitView, DiffLinesView


def spin(until, timeout=8.0):
    ctx = GLib.MainContext.default()
    deadline = GLib.get_monotonic_time() + int(timeout * 1e6)
    while not until() and GLib.get_monotonic_time() < deadline:
        ctx.iteration(False)
    return until()


def settle(view, pause=0.3):
    """Laisse finir les opérations en fil de la vue."""
    spin(lambda: not view.busy())
    end = GLib.get_monotonic_time() + int(pause * 1e6)
    ctx = GLib.MainContext.default()
    while GLib.get_monotonic_time() < end:
        ctx.iteration(False)
    spin(lambda: not view.busy())


@unittest.skipUnless(GTK, "affichage graphique requis (CCS_GUI_TESTS=1 sous xvfb-run)")
class ChangesViewTest(GitTestCase):
    def view(self):
        v = ChangesView(str(self.repo))
        v.refresh()
        settle(v)
        return v

    def test_stage_by_checkbox(self):
        commit_file(self.repo, "a.txt", "un\n")
        (self.repo / "a.txt").write_text("deux\n")
        (self.repo / "b.txt").write_text("neuf\n")
        v = self.view()
        self.assertEqual([s.path for s in v.unstaged_files()], ["a.txt", "b.txt"])
        v.set_staged("b.txt", True)
        settle(v)
        self.assertEqual(g(self.repo, "diff", "--cached", "--name-only").strip(), "b.txt")
        self.assertEqual([s.path for s in v.staged_files()], ["b.txt"])
        v.set_staged("b.txt", False)
        settle(v)
        self.assertEqual(g(self.repo, "diff", "--cached", "--name-only").strip(), "")

    def test_shift_click_selects_range(self):
        commit_file(self.repo, "a.txt", "1\n2\n3\n4\n5\n")
        (self.repo / "a.txt").write_text("1\nx\ny\nz\n5\n")
        fd = git_repo.diff(str(self.repo), "a.txt", staged=False)
        dv = DiffLinesView(fd, selectable=True)
        changed = [(0, i) for i, l in enumerate(fd.hunks[0].lines) if l.kind != " "]
        self.assertGreaterEqual(len(changed), 4)
        dv.click_line(*changed[0])
        dv.click_line(*changed[2], shift=True)
        self.assertEqual(dv.selected(), set(changed[:3]))
        dv.click_line(*changed[3])
        self.assertEqual(dv.selected(), {changed[3]})
        dv.click_header(0)
        self.assertEqual(dv.selected(), set(changed))

    def test_stage_selection_partial(self):
        commit_file(self.repo, "a.txt", "1\n2\n3\n")
        (self.repo / "a.txt").write_text("1\n2\n3\nA\nB\n")
        v = self.view()
        v.select_file("a.txt", staged=False)
        settle(v)
        lines = v.diff_view().fd.hunks[0].lines
        idx = [i for i, l in enumerate(lines) if l.kind == "+"]
        v.diff_view().click_line(0, idx[0])
        v.stage_selection()
        settle(v)
        self.assertEqual(g(self.repo, "diff", "--cached").count("\n+A"), 1)
        self.assertNotIn("+B", g(self.repo, "diff", "--cached"))
        v.select_file("a.txt", staged=True)
        settle(v)
        idx = [i for i, l in enumerate(v.diff_view().fd.hunks[0].lines) if l.kind == "+"]
        v.diff_view().click_line(0, idx[0])
        v.unstage_selection()
        settle(v)
        self.assertEqual(g(self.repo, "diff", "--cached").strip(), "")

    def test_discard_asks_confirmation(self):
        commit_file(self.repo, "a.txt", "un\n")
        (self.repo / "a.txt").write_text("deux\n")
        v = self.view()
        asked = []
        with mock.patch.object(v, "_confirm", lambda h, b, label, yes: asked.append(yes)):
            v.discard_file("a.txt")
            settle(v)
            self.assertEqual((self.repo / "a.txt").read_text(), "deux\n")
            self.assertEqual(len(asked), 1)
            asked[0]()
        settle(v)
        self.assertEqual((self.repo / "a.txt").read_text(), "un\n")

    def test_ctrl_enter_commits(self):
        (self.repo / "a.txt").write_text("un\n")
        v = self.view()
        v.set_staged("a.txt", True)
        settle(v)
        v.set_message("feat: premier")
        done = []
        v.connect("changed", lambda _v: done.append(1))
        ok = v.on_message_key(None, Gdk.KEY_Return, 0, Gdk.ModifierType.CONTROL_MASK)
        self.assertTrue(ok)
        settle(v)
        self.assertEqual(g(self.repo, "log", "-1", "--format=%s").strip(), "feat: premier")
        self.assertTrue(done)
        self.assertEqual(v.message(), "")

    def test_amend_prefills_message(self):
        commit_file(self.repo, "a.txt", "un\n", msg="feat: ancien message")
        v = self.view()
        v.set_amend(True)
        settle(v)
        self.assertEqual(v.message(), "feat: ancien message")

    def test_propose_fills_message(self):
        (self.repo / "docs.md").write_text("x\n")
        v = self.view()
        v.set_staged("docs.md", True)
        settle(v)
        v.propose()
        settle(v)
        self.assertTrue(v.message().startswith("docs: ajoute docs.md"))


@unittest.skipUnless(GTK, "affichage graphique requis (CCS_GUI_TESTS=1 sous xvfb-run)")
class CommitViewTest(GitTestCase):
    def test_commit_view_parent_click_emits(self):
        first = commit_file(self.repo, "a.txt", "un\n", msg="premier")
        second = commit_file(self.repo, "a.txt", "deux\n", msg="second\n\ncorps long")
        v = CommitView(str(self.repo), second)
        self.assertTrue(spin(lambda: v.loaded()))
        self.assertEqual(v.subject(), "second")
        self.assertEqual(v.files(), ["a.txt"])
        got = []
        v.connect("commit-activated", lambda _v, cid: got.append(cid))
        v.click_parent(0)
        self.assertEqual(got, [first])


if __name__ == "__main__":
    unittest.main()
