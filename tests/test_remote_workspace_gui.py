"""Espace de session d'un chat distant (GTK, sous Xvfb) : arbre, éditeur, feuille de route et Git
passent par le pont (vrais gestionnaires servis dans le processus, voir `remote_helpers`)."""

import unittest
from unittest import mock

from tests.git_helpers import GitTestCase, commit_file, g
from tests.helpers import gui_ready
from tests.remote_helpers import InProcessClient

GTK = gui_ready()
if GTK:
    from gi.repository import GLib, GObject, Gtk

    from ccs_app import tasks
    from ccs_app.gui import git_page
    from ccs_app.gui.session_workspace import SessionWorkspace
    from ccs_app.remote.workspace import RemoteWorkspace

    class FakeChat(Gtk.Box):
        __gsignals__ = {
            "open-file": (GObject.SignalFlags.RUN_FIRST, None, (str, int)),
            "show-diff": (GObject.SignalFlags.RUN_FIRST, None, (str, str, str)),
        }

        def __init__(self):
            super().__init__(hexpand=True, vexpand=True)
            self.sent = []

        def send_auto(self, text):
            self.sent.append(text)
            return True

        def do_roadmap_task(self, *_a):
            raise AssertionError("lit le disque local : jamais pour un chat distant")


def spin(until, timeout=8.0):
    ctx = GLib.MainContext.default()
    deadline = GLib.get_monotonic_time() + int(timeout * 1e6)
    while not until() and GLib.get_monotonic_time() < deadline:
        ctx.iteration(False)
    return until()


ROADMAP = "# Projet\n\n## Phase 1\n\n- [ ] faire a\n- [x] faire b\n"


@unittest.skipUnless(GTK, "affichage graphique requis (CCS_GUI_TESTS=1 sous xvfb-run)")
class RemoteWorkspaceGuiTest(GitTestCase):
    def setUp(self):
        super().setUp()
        commit_file(self.repo, "a.txt", "un\n")
        commit_file(self.repo, "src/b.py", "print(1)\n")
        (self.repo / "ROADMAP.md").write_text(ROADMAP)
        self.client = InProcessClient()
        self.addCleanup(self.client.close)
        self.chat = FakeChat()
        with mock.patch.object(git_page, "_saved_layout", return_value="A"):
            self.ws = SessionWorkspace(str(self.repo), self.chat,
                                       remote=RemoteWorkspace(self.client, "serveur"))
        self.addCleanup(self.ws.close)
        self.win = Gtk.Window(default_width=1300, default_height=700)
        self.win.set_child(self.ws)
        self.win.present()
        self.addCleanup(self.win.destroy)
        self.assertTrue(spin(lambda: self.ws.outer.get_width() > 0))

    def names(self):
        return [r[0] for r in self.ws.tree.rows()]

    # ---- arbre -------------------------------------------------------------------------

    def test_tree_lists_server_folder_without_local_watch(self):
        self.assertTrue(spin(lambda: {"src", "a.txt", "ROADMAP.md"} <= set(self.names())))
        self.assertIn("files.list", self.client.calls)
        self.assertEqual(self.ws.tree._monitors, {})
        items = [self.ws.tree._menu_model.get_item_attribute_value(i, "action", None).get_string()
                 for i in range(self.ws.tree._menu_model.get_n_items())]
        self.assertNotIn("fichiers.default-app", items)
        self.assertNotIn("fichiers.show", items)
        self.assertFalse(self.ws.changes_btn.get_visible())

    def test_tree_marks_and_refresh(self):
        self.assertTrue(spin(lambda: "a.txt" in self.names()))
        (self.repo / "a.txt").write_text("deux\n")
        (self.repo / "neuf.txt").write_text("n\n")
        self.ws.refresh_remote()
        self.assertTrue(spin(lambda: ("neuf.txt", 0, "?") in self.ws.tree.rows()))
        self.assertIn(("a.txt", 0, "M"), self.ws.tree.rows())

    # ---- éditeur -----------------------------------------------------------------------

    def test_open_edit_and_save_on_server(self):
        path = str(self.repo / "a.txt")
        self.ws.open_file(path)
        ed = self.ws.editor
        self.assertTrue(spin(lambda: ed.text(path) == "un\n"))
        ed.set_text(path, "modifié\n")
        saved = []
        ed.save(path, saved.append)
        self.assertTrue(spin(lambda: saved == [True]))
        self.assertEqual((self.repo / "a.txt").read_text(), "modifié\n")
        self.assertIn("files.write", self.client.calls)
        self.assertEqual(ed._docs[path].monitor, None)

    def test_editor_follows_server_and_refuses_stale_save(self):
        path = str(self.repo / "a.txt")
        self.ws.open_file(path)
        ed = self.ws.editor
        self.assertTrue(spin(lambda: ed.text(path) == "un\n"))
        (self.repo / "a.txt").write_text("ailleurs\n")
        ed.check_changes()
        self.assertTrue(spin(lambda: ed.text(path) == "ailleurs\n"))
        (self.repo / "a.txt").write_text("encore ailleurs, plus long\n")
        ed.set_text(path, "le mien\n")
        saved = []
        ed.save(path, saved.append)
        self.assertTrue(spin(lambda: saved == [False]))
        self.assertEqual((self.repo / "a.txt").read_text(), "encore ailleurs, plus long\n")

    def test_unreachable_file(self):
        self.client.offline = True
        path = str(self.repo / "a.txt")
        self.ws.open_file(path)
        self.assertTrue(spin(lambda: self.ws.editor.state(path) == "unavailable"))

    # ---- feuille de route --------------------------------------------------------------

    def test_roadmap_read_and_ticked_on_server(self):
        rv = self.ws.roadmap
        self.assertTrue(spin(lambda: rv.loaded and rv.roadmap is not None))
        self.assertEqual(len(rv.task_rows), 2)
        line = next(n for n, r in rv.task_rows.items() if not r.check.get_active())
        rv.task_rows[line].check.set_active(True)
        self.assertTrue(spin(lambda: "- [x] faire a" in (self.repo / "ROADMAP.md").read_text()))
        self.assertIsNone(rv._monitor)

    def test_no_roadmap_no_local_chooser(self):
        (self.repo / "ROADMAP.md").unlink()
        self.ws.roadmap.reload()
        rv = self.ws.roadmap
        self.assertTrue(spin(lambda: rv.loaded and rv.roadmap is None and rv.ask_button))
        self.assertIsNone(rv.choose_button)

    def test_roadmap_play_now_and_night_queue(self):
        rv = self.ws.roadmap
        self.assertTrue(spin(lambda: rv.roadmap is not None))
        row = next(r for r in rv.task_rows.values() if r.play is not None)
        row.do_task("chat")
        self.assertEqual(len(self.chat.sent), 1)
        self.assertIn("faire a", self.chat.sent[0])
        row.do_task("nuit")
        self.assertTrue(spin(lambda: rv.last_toast is not None))
        self.assertIn("nuit", rv.last_toast)
        queued = tasks.all()
        self.assertEqual([(t.cwd, t.when) for t in queued], [(str(self.repo), "nuit")])

    def test_tool_on_roadmap_is_followed(self):
        self.ws.follow_tool("Edit", {"file_path": str(self.repo / "ROADMAP.md")})
        self.assertEqual(self.ws.followed_roadmap, str(self.repo / "ROADMAP.md"))
        self.assertTrue(self.ws._soon_source)

    # ---- git ---------------------------------------------------------------------------

    def test_git_stage_commit_and_history(self):
        gp = self.ws.git_page
        self.assertTrue(spin(lambda: gp.branch_btn.get_label() == "main"))
        self.assertTrue(spin(lambda: gp.graph.commit_count() == 2))
        self.assertEqual(gp._monitors, [])
        self.assertFalse(gp.changes.btn_discard_sel.get_visible())
        (self.repo / "a.txt").write_text("deux\n")
        gp.refresh()
        self.assertTrue(spin(lambda: sorted(f.path for f in gp.changes.unstaged_files())
                             == ["ROADMAP.md", "a.txt"]), gp.changes.unstaged_files())
        gp.changes.set_staged("a.txt", True)
        self.assertTrue(spin(lambda: [f.path for f in gp.changes.staged_files()] == ["a.txt"]))
        gp.changes.set_message("modifie a")
        gp.changes.commit()
        self.assertTrue(spin(lambda: g(self.repo, "log", "-1", "--format=%s").strip() == "modifie a"))
        gp.refresh(full=True)
        self.assertTrue(spin(lambda: gp.graph.commit_count() == 3))
        opened = []
        gp._open_in_editor = lambda key, title, w: opened.append(w)
        cid = g(self.repo, "rev-parse", "HEAD").strip()
        gp.open_commit(cid)
        self.assertTrue(spin(lambda: opened and opened[0].loaded()))
        self.assertEqual(opened[0].subject(), "modifie a")
        self.assertEqual(opened[0].files(), ["a.txt"])

    def test_git_selected_lines_and_no_flow(self):
        gp = self.ws.git_page
        self.assertTrue(spin(lambda: gp.branch_btn.get_label() == "main"))
        buttons = []
        child = gp._flow_box.get_first_child()
        while child is not None:
            buttons.append(child)
            child = child.get_next_sibling()
        self.assertTrue(buttons)
        self.assertFalse(any(b.get_sensitive() for b in buttons))
        (self.repo / "a.txt").write_text("un\ndeux\ntrois\n")
        gp.refresh()
        self.assertTrue(spin(lambda: "a.txt" in [f.path for f in gp.changes.unstaged_files()]))
        gp.changes.select_file("a.txt", False)
        self.assertTrue(spin(lambda: gp.changes.diff_view() is not None))
        view = gp.changes.diff_view()
        li = next(i for i, l in enumerate(view.fd.hunks[0].lines) if l.text == "deux")
        view.click_line(0, li)
        gp.changes.stage_selection()
        self.assertTrue(spin(lambda: "+deux" in g(self.repo, "diff", "--cached")))
        self.assertNotIn("trois", g(self.repo, "diff", "--cached"))


if __name__ == "__main__":
    unittest.main()
