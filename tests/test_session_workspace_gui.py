"""Espace de session (GTK, affichage requis) : sous Xvfb seulement, avec un faux chat."""

import unittest
from pathlib import Path

from tests.helpers import HomeTestCase, gui_ready

GTK = gui_ready()
if GTK:
    from gi.repository import GLib, GObject, Gtk

    from ccs_app import terminal_store
    from ccs_app.gui.session_workspace import SessionWorkspace

    class FakeChat(Gtk.Box):
        __gsignals__ = {
            "open-file": (GObject.SignalFlags.RUN_FIRST, None, (str, int)),
            "show-diff": (GObject.SignalFlags.RUN_FIRST, None, (str, str, str)),
        }

        def __init__(self):
            super().__init__(hexpand=True, vexpand=True)
            self.sent = []
            self.refs = []

        def send_auto(self, text):
            self.sent.append(text)
            return True

        def insert_reference(self, relpath):
            self.refs.append(relpath)


def spin(until, timeout=8.0):
    ctx = GLib.MainContext.default()
    deadline = GLib.get_monotonic_time() + int(timeout * 1e6)
    while not until() and GLib.get_monotonic_time() < deadline:
        ctx.iteration(False)
    return until()


@unittest.skipUnless(GTK, "affichage graphique requis (CCS_GUI_TESTS=1 sous xvfb-run)")
class SessionWorkspaceGuiTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.project = Path(self.tmp) / "projet"
        self.project.mkdir()
        (self.project / "a.py").write_text("print(1)\n")
        self.chat = FakeChat()
        self.ws = SessionWorkspace(self.project, self.chat)
        self.win = Gtk.Window(default_width=1300, default_height=700)
        self.win.set_child(self.ws)
        self.win.present()
        self.addCleanup(self.win.destroy)
        self.assertTrue(spin(lambda: self.ws.outer.get_width() > 0))
        spin(lambda: False, 0.3)

    def test_layout_B_file_panel_hidden_until_open(self):
        self.assertEqual(self.ws.layout, "B")
        self.assertFalse(self.ws.editor_box.get_visible())
        self.assertIs(self.ws.inner.get_start_child(), self.chat)
        self.chat.emit("open-file", str(self.project / "a.py"), 0)
        self.assertTrue(self.ws.editor_box.get_visible())
        self.assertTrue(spin(lambda: self.ws.editor.paths()))
        self.assertIs(self.ws.inner.get_end_child(), self.ws.editor_box)

    def test_closing_last_file_hides_panel_in_B(self):
        p = str(self.project / "a.py")
        self.chat.emit("open-file", p, 0)
        self.assertTrue(spin(lambda: self.ws.editor.paths()))
        self.ws.editor.close(Path(p), force=True)
        self.assertTrue(spin(lambda: not self.ws.editor_box.get_visible()))

    def test_switch_to_A_keeps_widgets(self):
        tree, roadmap, editor, chat = self.ws.tree, self.ws.roadmap, self.ws.editor, self.chat
        self.ws.set_layout("A")
        self.assertIs(self.ws.inner.get_start_child(), self.ws.editor_box)
        self.assertIs(self.ws.inner.get_end_child(), chat)
        self.assertTrue(self.ws.editor_box.get_visible())
        self.ws.set_layout("B")
        self.assertIs(self.ws.inner.get_start_child(), chat)
        self.assertEqual((self.ws.tree, self.ws.roadmap, self.ws.editor, self.ws.center),
                         (tree, roadmap, editor, chat))
        self.assertIs(chat.get_parent(), self.ws.inner)

    def test_pane_positions_saved_per_layout(self):
        self.chat.emit("open-file", str(self.project / "a.py"), 0)
        spin(lambda: False, 0.5)
        self.ws.outer.set_position(300)
        self.ws.inner.set_position(self.ws.inner.get_width() - 380)
        self.ws.save_sizes()
        saved = terminal_store.load_panes()
        self.assertEqual(saved["B"]["tree"], 300)
        self.assertEqual(saved["B"]["side"], 380)
        self.assertEqual(saved["A"], terminal_store.DEFAULT_PANES["A"])  # l'autre n'a pas bougé
        self.ws.set_layout("A")
        spin(lambda: False, 0.3)
        self.ws.outer.set_position(200)
        self.ws.inner.set_position(self.ws.inner.get_width() - 500)
        self.ws.save_sizes()
        saved = terminal_store.load_panes()
        self.assertEqual(saved["A"]["tree"], 200)
        self.assertEqual(saved["A"]["side"], 500)
        self.assertEqual(saved["B"]["side"], 380)

    def test_saved_sizes_are_restored(self):
        panes = terminal_store.load_panes()
        panes["B"] = {"tree": 333, "side": 410}
        terminal_store.save_panes(panes)
        ws = SessionWorkspace(self.project, FakeChat())
        win = Gtk.Window(default_width=1300, default_height=700)
        win.set_child(ws)
        win.present()
        self.addCleanup(win.destroy)
        ws.open_file(str(self.project / "a.py"))
        self.assertTrue(spin(lambda: ws.outer.get_position() == 333))
        self.assertTrue(spin(lambda: ws.sizes()["side"] == 410))

    def test_ctrl_b_toggles_tree(self):
        self.assertTrue(self.ws.left.get_visible())
        self.ws.toggle_tree()
        self.assertFalse(self.ws.left.get_visible())
        self.assertFalse(terminal_store.load_panes()["tree_visible"])
        self.ws.toggle_tree()
        self.assertTrue(self.ws.left.get_visible())
        # le raccourci lui-même est installé sur l'espace
        self.assertTrue(any(isinstance(c, Gtk.ShortcutController)
                            for c in self.ws.observe_controllers()))

    def test_left_stack_choice_is_saved(self):
        self.ws.show_left("feuille")
        self.assertEqual(terminal_store.load_panes()["left"], "feuille")

    def test_diff_signal_opens_editor(self):
        self.chat.emit("show-diff", str(self.project / "a.py"), "un\n", "deux\n")
        self.assertTrue(self.ws.editor_box.get_visible())
        self.assertTrue(spin(lambda: self.ws.editor.tab_view.get_n_pages() == 1))

    def test_insert_reference_reaches_chat(self):
        got = []
        self.ws.connect("insert-reference", lambda _w, rel: got.append(rel))
        self.ws.tree.emit("insert-reference", "a.py")
        self.assertEqual(got, ["a.py"])
        self.assertEqual(self.chat.refs, ["a.py"])

    def test_ask_create_sends_to_chat(self):
        self.ws.ask_create()
        self.assertEqual(len(self.chat.sent), 1)
        self.assertIn("ROADMAP.md", self.chat.sent[0])
        self.assertIn("cases à cocher", self.chat.sent[0])


if __name__ == "__main__":
    unittest.main()
