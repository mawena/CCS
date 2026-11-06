"""Application : actions « show-session » (notifications), « show-page » et « new-session »
(`gui --page`, `gui --new-session`), sans fenêtre ni affichage."""

import os
import unittest
from unittest import mock

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib  # noqa: F401
    GTK = True
except (ImportError, ValueError):
    GTK = False


@unittest.skipUnless(GTK, "GTK 4 et libadwaita absents")
class ShowSessionActionTest(unittest.TestCase):
    def setUp(self):
        from ccs_app.gui import app
        self.appmod = app

    def test_action_registered_with_a_string_parameter(self):
        with mock.patch.dict(os.environ, {"CCS_APP_ID": "io.ccs.ClaudeAccounts.Test"}):
            a = self.appmod.App()
        self.assertEqual(a.get_application_id(), "io.ccs.ClaudeAccounts.Test")
        action = a.lookup_action("show-session")
        self.assertIsNotNone(action)
        self.assertEqual(action.get_parameter_type().dup_string(), "s")

    def test_session_kept_for_the_first_window(self):
        a = self.appmod.App("4242:3f2a")
        self.assertEqual(a.pending_session, "4242:3f2a")
        self.assertIsNone(self.appmod.App().pending_session)

    def test_page_and_new_session_actions(self):
        a = self.appmod.App()
        page = a.lookup_action("show-page")
        self.assertEqual(page.get_parameter_type().dup_string(), "s")
        new = a.lookup_action("new-session")
        self.assertIsNotNone(new)
        self.assertIsNone(new.get_parameter_type())

    def test_page_and_new_session_kept_for_the_first_window(self):
        a = self.appmod.App(page="history", new_session=True)
        self.assertEqual((a.pending_page, a.pending_new_session), ("history", True))
        b = self.appmod.App()
        self.assertEqual((b.pending_page, b.pending_new_session), (None, False))

    def test_actions_sent_to_the_running_app(self):
        sent = self.appmod.remote_actions(session="7:s", page="sessions", new_session=True)
        self.assertEqual([name for name, _ in sent], ["show-page", "show-session", "new-session"])
        self.assertEqual(sent[0][1].get_string(), "sessions")
        self.assertEqual(sent[1][1].get_string(), "7:s")
        self.assertIsNone(sent[2][1])
        self.assertEqual(self.appmod.remote_actions(), [])

    def test_switch_notes_its_origin_for_the_journal(self):
        calls = []
        with mock.patch.object(self.appmod.switch_log, "note_origin",
                               side_effect=lambda *a: calls.append(("note",) + a)), \
                mock.patch.object(self.appmod, "run_ccs_async",
                                  side_effect=lambda _w, args, _t=None: calls.append(("ccs", args))):
            self.appmod.Window.switch(object(), "pro")
        # La note précède la bascule : le service la lit quand il la constate.
        self.assertEqual(calls, [("note", "pro", "application"), ("ccs", ["use", "pro"])])

    def test_stack_pages_are_the_known_pages(self):
        # Le ViewStack et `gui --page` (desktop.PAGES) doivent rester d'accord.
        import inspect
        source = inspect.getsource(self.appmod.Window.__init__)
        from ccs_app import desktop
        for name in desktop.PAGES:
            self.assertIn(f'"{name}"', source)
        self.assertNotIn('"conversations"', source)


if __name__ == "__main__":
    unittest.main()
