"""Application : action « show-session » des notifications (sans fenêtre ni affichage)."""

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


if __name__ == "__main__":
    unittest.main()
