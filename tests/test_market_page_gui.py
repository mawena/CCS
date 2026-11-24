"""Bureau : onglet Market (phase 45). Le bouton ouvre le chat Market dans l'onglet Sessions
(dossier préparé, dernière conversation reprise) ou retrouve son onglet déjà ouvert. Fenêtre
réelle dans un HOME temporaire, sous Xvfb."""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.helpers import HomeTestCase

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib  # noqa: F401
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False


@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class MarketPageTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        for p in (mock.patch.dict(os.environ, {"CCS_APP_ID": "io.ccs.ClaudeAccounts.TestMarket", "CCS_NO_VTE": "1"}),
                  mock.patch("ccs_app.gui.app.refresh_data"),
                  mock.patch("ccs_app.daemon.running_pid", return_value=None),
                  mock.patch("ccs_app.sessions.list_sessions", return_value=[]),
                  mock.patch("ccs_app.updates.available", return_value=None)):
            p.start()
            self.addCleanup(p.stop)
        from ccs_app.gui import app
        self.appmod = app
        self.app = app.App()
        self.win = app.Window(self.app)
        self.addCleanup(self.win.destroy)

    def test_tab_and_button(self):
        self.assertIsNotNone(self.win.stack.get_child_by_name("market"))
        self.assertTrue(self.win.show_page("market"))
        self.assertEqual(self.win.stack.get_visible_child_name(), "market")
        with mock.patch.object(self.win, "open_market") as opened:
            self.win.market.open_button.emit("clicked")
        opened.assert_called_once_with()

    def test_open_market_prepares_folder_then_opens_chat(self):
        shown = []
        with mock.patch.object(self.appmod, "in_thread", lambda work, done: done(work())), \
                mock.patch.object(self.win, "show_market_chat", lambda cwd, sid: shown.append((cwd, sid))):
            self.win.open_market()
        cwd, sid = shown[0]
        self.assertTrue(cwd.endswith(os.path.join("ccs", "market")))
        self.assertTrue(os.path.isfile(os.path.join(cwd, "CLAUDE.md")))
        self.assertIsNone(sid)

    def test_new_tab_or_existing_one(self):
        terms = self.win.terminals
        new_tab = object()
        with mock.patch.object(terms, "find", return_value=None), \
                mock.patch.object(terms, "tabs", return_value=[]), \
                mock.patch.object(terms, "open_claude", return_value=new_tab) as opened:
            self.assertIs(self.win.show_market_chat("/m", "s1"), new_tab)
        opened.assert_called_once_with("/m", "s1", "Market")
        self.assertEqual(self.win.stack.get_visible_child_name(), "sessions")
        existing = SimpleNamespace(state=SimpleNamespace(chat=True, cwd="/m"))
        with mock.patch.object(terms, "find", return_value=None), \
                mock.patch.object(terms, "tabs", return_value=[existing]), \
                mock.patch.object(terms, "present") as present, \
                mock.patch.object(terms, "open_claude") as opened:
            self.assertIs(self.win.show_market_chat("/m", None), existing)
        present.assert_called_once_with(existing)
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
