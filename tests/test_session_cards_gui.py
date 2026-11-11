"""Cartes des sessions ouvertes : RAM, inactivité, « Fermer », badge de contexte lourd
(GTK, affichage requis).

Lancées seulement avec CCS_GUI_TESTS=1 (sous Xvfb, jamais sur le bureau réel)."""

import os
import unittest
from unittest import mock

GTK = False
if os.environ.get("CCS_GUI_TESTS") == "1":
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk
        GTK = Gtk.init_check() if hasattr(Gtk, "init_check") else True
    except (ImportError, ValueError):
        GTK = False

NOW = 1_800_000_000.0


def walk(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from walk(child)
        child = child.get_next_sibling()


@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class SessionCardsTest(unittest.TestCase):
    def setUp(self):
        Adw.init()
        from ccs_app import context_alert, session_memory
        from ccs_app.gui.session_cards import SessionCards
        from ccs_app.sessions import Session
        self.ca, self.sm = context_alert, session_memory
        window = mock.MagicMock()
        window.terminals.find.return_value = None
        window.terminals.available = False
        with mock.patch("ccs_app.core.active_profile_name", return_value="perso"):
            self.cards = SessionCards(window, lambda: None)
        self.session = Session(pid=10, session_id="s1", name="n", cwd="/home/u/App", project="App",
                               state="idle", waiting_for=None, started_at=NOW - 9000, state_since=NOW - 8000,
                               kind="interactive", entrypoint="cli")

    def render(self, **extra):
        with mock.patch("ccs_app.core.active_profile_name", return_value="perso"):
            self.cards.render([self.session], {}, {}, {}, True, **extra)

    def labels(self):
        return [w.get_label() for w in walk(self.cards) if isinstance(w, Gtk.Label)]

    def buttons(self):
        return [w.get_label() for w in walk(self.cards) if isinstance(w, Gtk.Button) and w.get_label()]

    def test_old_api_still_works_and_shows_no_memory(self):
        self.render()
        self.assertFalse(any("Mo" in t or "Go" in t for t in self.labels()))
        self.assertNotIn("Fermer", self.buttons())

    def test_memory_line_banner_and_close_button_for_idle_sessions(self):
        mem = {10: self.sm.SessionMemory(10, 1536 * 1024 ** 2, 8000, True)}
        closed = []
        self.render(memory=mem, on_close=closed.append)
        texts = self.labels()
        self.assertTrue(any("1,5 Go · inactive depuis 2 h 13" in t for t in texts), texts)
        banners = [w for w in walk(self.cards) if isinstance(w, Adw.Banner)]
        self.assertEqual([b.get_title() for b in banners], ["1 session inactive occupe 1,5 Go"])
        self.assertIn("Fermer", self.buttons())
        with mock.patch("ccs_app.gui.session_cards.Adw.AlertDialog"):
            [w for w in walk(self.cards) if isinstance(w, Gtk.Button) and w.get_label() == "Fermer"][0].emit(
                "clicked")
        self.assertEqual(closed, [])          # rien ne se ferme sans la confirmation

    def test_no_close_button_for_active_session_or_without_callback(self):
        active = {10: self.sm.SessionMemory(10, 100 * 1024 ** 2, 60, False)}
        self.render(memory=active, on_close=lambda s: None)
        self.assertNotIn("Fermer", self.buttons())
        idle = {10: self.sm.SessionMemory(10, 100 * 1024 ** 2, 9000, True)}
        self.render(memory=idle)
        self.assertNotIn("Fermer", self.buttons())

    def test_heavy_context_badge(self):
        self.render(contexts={10: self.ca.Context(182_000, "claude-opus-5-5")})
        self.assertIn("contexte lourd · 182 k", self.labels())
        self.render(contexts={10: self.ca.Context(20_000, "claude-opus-5-5")})
        self.assertFalse(any("contexte lourd" in t for t in self.labels()))
        self.render(contexts={10: self.ca.Context(60_000, "claude-opus-5-5")}, heavy_tokens=50_000)
        self.assertIn("contexte lourd · 60 k", self.labels())


if __name__ == "__main__":
    unittest.main()
