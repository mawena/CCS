"""Dialogue « Nouvelle session » : mêmes champs et valeurs par défaut que le web, fournisseur,
« Terminal », affichage par tous les chemins (nécessite un affichage, p. ex. Xvfb)."""

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

from ccs_app import chat_options, launch_options, providers  # noqa: E402
from tests.helpers import HomeTestCase  # noqa: E402


@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class NewSessionProviderTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        os.environ.pop("XDG_CONFIG_HOME", None)
        self.folder = self.home / "projet"
        self.folder.mkdir()

    def make(self, **kw):
        from ccs_app.gui.new_session_dialog import NewSessionDialog
        kw.setdefault("prefs", {})
        return NewSessionDialog(str(self.folder), kw.pop("on_ok", lambda spec: None), profiles=[], recent=[],
                                associations=[], paused=False, **kw)

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


@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class NewSessionLikeWebTest(HomeTestCase):
    """Mêmes champs, même ordre, mêmes valeurs par défaut que web/sessions-new.js."""

    def setUp(self):
        super().setUp()
        os.environ.pop("XDG_CONFIG_HOME", None)
        self.folder = self.home / "projet"
        self.folder.mkdir()

    def make(self, **kw):
        from ccs_app.gui.new_session_dialog import NewSessionDialog
        kw.setdefault("prefs", {})
        return NewSessionDialog(str(self.folder), kw.pop("on_ok", lambda spec: None), profiles=[], recent=[],
                                associations=[], paused=False, **kw)

    @staticmethod
    def labels(row):
        m = row.get_model()
        return [m.get_string(i) for i in range(m.get_n_items())]

    def test_fields_order_and_lists_from_shared_form(self):
        d = self.make()
        form = chat_options.new_session_form({})
        rows = [d.provider_row, d.model_row, d.effort_row, d.mode_row]
        group = d.model_row.get_ancestor(Adw.PreferencesGroup)
        self.assertTrue(all(r.get_ancestor(Adw.PreferencesGroup) is group for r in rows))
        titles = [r.get_title() for r in rows]
        self.assertEqual(titles, ["Fournisseur", "Modèle", "Effort", "Droits"])
        self.assertEqual(self.labels(d.model_row), [label for _v, label in form["models"]])
        self.assertEqual(self.labels(d.effort_row), [label for _v, label in form["efforts"]])
        self.assertEqual(self.labels(d.mode_row), [label for _v, label in form["rights"]])

    def test_defaults_like_web(self):
        spec = self.make().spec()
        self.assertEqual((spec.model, spec.effort, spec.permission_mode, spec.provider),
                         (None, None, "manual", None))
        d = self.make(prefs={"chat": {"rights": "tout"}})     # chat.rights, comme form.default_rights au web
        self.assertEqual(d.selected_mode(), "bypassPermissions")
        self.assertTrue(d.danger_row.get_visible())

    def test_effort_in_spec_and_hidden_for_other_provider(self):
        d = self.make()
        d.effort_row.set_selected(3)
        self.assertEqual(d.spec().effort, d.efforts[3][0])
        d.provider_row.set_selected(next(i for i, p in enumerate(d.providers) if p[0] == "openrouter"))
        self.assertFalse(d.effort_row.get_visible())
        self.assertIsNone(d.selected_effort())

    def test_open_chat_and_terminal_buttons(self):
        got = []
        d = self.make(on_ok=lambda spec: got.append(("chat", spec.cwd)),
                      on_term=lambda cwd: got.append(("term", cwd)))
        self.assertEqual(d.ok_btn.get_label(), "Ouvrir un chat")
        self.assertTrue(d.term_btn.get_visible())
        d.term_btn.emit("clicked")
        d.ok_btn.emit("clicked")
        self.assertEqual(got, [("term", str(self.folder)), ("chat", str(self.folder))])
        self.assertFalse(self.make().term_btn.get_visible())      # sans on_term : pas de bouton

    def test_presented_once_parent_is_mapped(self):
        """`--new-session` au lancement : la fenêtre n'est pas encore affichée ; le dialogue
        attend qu'elle le soit au lieu d'être présenté (et perdu) trop tôt."""
        from gi.repository import GLib, Gtk
        from ccs_app.gui.new_session_dialog import ask_new_session
        win = Adw.ApplicationWindow()
        d = ask_new_session(win, str(self.folder), lambda spec: None, profiles=[], recent=[],
                            associations=[], paused=False, prefs={})
        self.assertIsNone(win.get_visible_dialog())
        win.present()
        ctx = GLib.MainContext.default()
        for _ in range(200):
            if win.get_visible_dialog() is d:
                break
            ctx.iteration(False)
        self.assertIs(win.get_visible_dialog(), d)
        d.force_close()
        win.destroy()
        self.assertIsInstance(win, Gtk.Window)


if __name__ == "__main__":
    unittest.main()
