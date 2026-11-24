"""Dialogue « Nouvelle session » : choix du fournisseur de modèles (nécessite un affichage,
p. ex. Xvfb)."""

import os
import unittest

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw
    Adw.init()
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False

from ccs_app import launch_options, providers  # noqa: E402
from tests.helpers import HomeTestCase  # noqa: E402


@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class NewSessionProviderTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        os.environ.pop("XDG_CONFIG_HOME", None)
        self.folder = self.home / "projet"
        self.folder.mkdir()

    def make(self):
        from ccs_app.gui.new_session_dialog import NewSessionDialog
        return NewSessionDialog(str(self.folder), lambda spec: None, profiles=[], recent=[],
                                associations=[], paused=False)

    def choose(self, d, name):
        d.provider_row.set_selected(next(i for i, p in enumerate(d.providers) if p[0] == name))

    def test_claude_by_default(self):
        d = self.make()
        self.assertTrue(d.provider_row.get_visible())
        self.assertIsNone(d.selected_provider())
        self.assertEqual(d.model_values, list(launch_options.MODELS))
        self.assertIsNone(d.spec().provider)
        self.assertTrue(d.ok_btn.get_sensitive())

    def test_provider_without_key_blocks_open(self):
        d = self.make()
        self.choose(d, "openrouter")
        self.assertEqual(d.selected_provider(), "openrouter")
        self.assertEqual(d.model_values, list(providers.get("openrouter").models))
        self.assertFalse(d.ok_btn.get_sensitive())
        self.assertIn("clé absente", d.provider_row.get_subtitle())

    def test_provider_with_key_gives_spec(self):
        providers.save_key("openrouter", "sk-or-essai")
        d = self.make()
        self.choose(d, "openrouter")
        self.assertTrue(d.ok_btn.get_sensitive())
        spec = d.spec()
        self.assertEqual((spec.provider, spec.model), ("openrouter", providers.get("openrouter").default_model))
        self.choose(d, "claude")
        self.assertEqual(d.model_values, list(launch_options.MODELS))
        self.assertIsNone(d.spec().provider)


if __name__ == "__main__":
    unittest.main()
