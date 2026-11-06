"""Groupe « Raccourcis clavier » des Réglages : réglages simulés, jamais ceux du bureau.
Les widgets sont créés sans être affichés (affichage requis, sinon tests sautés)."""

import os
import unittest
from unittest import mock

from ccs_app import shortcuts as sc

from .test_shortcuts import DIR, FOREIGN, custom, custom_list, gnome

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, GLib, Gtk
    GTK = bool(Gtk.init_check())
except (ImportError, ValueError):
    GTK = False

M = Gdk.ModifierType if GTK else None


@unittest.skipUnless(GTK, "GTK 4, libadwaita ou affichage absents")
class ShortcutsGroupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Adw.init()

    def setUp(self):
        from ccs_app.gui import shortcuts_group
        self.mod = shortcuts_group
        for p in (mock.patch.object(sc, "default_backend",
                                    side_effect=AssertionError("vrais réglages GNOME interdits en test")),
                  mock.patch.object(sc, "command_for", side_effect=lambda a: "/usr/bin/" + sc.action(a).display),
                  mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"})):
            p.start()
            self.addCleanup(p.stop)
        self.b = gnome()
        self.toasts = []

    def group(self, backend=None):
        return self.mod.ShortcutsGroup(backend=backend or self.b, toast=self.toasts.append)

    def test_rows_reflect_status(self):
        sc.install("ouvrir", backend=self.b)
        g = self.group()
        self.assertEqual(list(g.rows), list(sc.ACTION_IDS))
        self.assertTrue(g.rows["ouvrir"].switch.get_active())
        self.assertFalse(g.rows["sessions"].switch.get_active())
        self.assertEqual(g.rows["ouvrir"].accel.get_accelerator(), "<Super><Alt>c")
        self.assertEqual(g.rows["sessions"].accel.get_accelerator(), "<Super><Alt>v")
        self.assertEqual(g.rows["suivant"].get_subtitle(), "ccs next --notifier")
        self.assertFalse(g.rows["ouvrir"].warning.get_visible())

    def test_switch_on_installs_and_off_removes(self):
        g = self.group()
        g.rows["pause"].switch.set_active(True)
        self.assertEqual(custom_list(self.b), FOREIGN + [DIR + "ccs-pause/"])
        self.assertIn("Super+Alt+P", self.toasts[-1])
        g.rows["pause"].switch.set_active(False)
        self.assertEqual(custom_list(self.b), FOREIGN)
        self.assertIn("retiré", self.toasts[-1])

    def test_refresh_does_not_write(self):
        sc.install("ouvrir", backend=self.b)
        self.b.log.clear()
        g = self.group()
        g.refresh()
        self.assertEqual(self.b.log, [])

    def test_conflict_warning(self):
        sc.install("sessions", "<Super><Alt>s", backend=self.b)
        g = self.group()
        row = g.rows["sessions"]
        self.assertTrue(row.warning.get_visible())
        self.assertIn("Lecteur d'écran", row.get_subtitle())
        self.assertIn("Lecteur d'écran", row.warning.get_tooltip_text())

    def test_capture_sets_binding_and_installs(self):
        g = self.group()
        dialog = g.capture(g.rows["meilleur"], present=False)
        self.assertTrue(dialog.on_key(None, Gdk.KEY_o, 0, M.SUPER_MASK | M.ALT_MASK))
        self.assertEqual(custom(self.b, DIR + "ccs-meilleur/")["binding"], "<Super><Alt>o")
        self.assertTrue(g.rows["meilleur"].switch.get_active())
        self.assertIn("Super+Alt+O", self.toasts[-1])

    def test_capture_uppercase_keeps_shift(self):
        g = self.group()
        dialog = g.capture(g.rows["meilleur"], present=False)
        dialog.on_key(None, Gdk.KEY_O, 0, M.SUPER_MASK | M.SHIFT_MASK)
        self.assertEqual(custom(self.b, DIR + "ccs-meilleur/")["binding"], "<Super><Shift>o")

    def test_capture_conflict_is_announced(self):
        g = self.group()
        dialog = g.capture(g.rows["sessions"], present=False)
        dialog.on_key(None, Gdk.KEY_s, 0, M.SUPER_MASK | M.ALT_MASK)
        self.assertIn("Lecteur d'écran", self.toasts[-1])
        self.assertTrue(g.rows["sessions"].warning.get_visible())

    def test_capture_escape_cancels(self):
        sc.install("pause", backend=self.b)
        self.b.log.clear()
        g = self.group()
        dialog = g.capture(g.rows["pause"], present=False)
        self.assertTrue(dialog.on_key(None, Gdk.KEY_Escape, 0, 0))
        self.assertEqual(self.b.log, [])

    def test_capture_backspace_clears(self):
        sc.install("pause", backend=self.b)
        g = self.group()
        dialog = g.capture(g.rows["pause"], present=False)
        self.assertTrue(dialog.on_key(None, Gdk.KEY_BackSpace, 0, 0))
        self.assertEqual(custom_list(self.b), FOREIGN)
        self.assertFalse(g.rows["pause"].switch.get_active())

    def test_capture_waits_for_a_real_key(self):
        g = self.group()
        dialog = g.capture(g.rows["pause"], present=False)
        self.assertTrue(dialog.on_key(None, Gdk.KEY_Super_L, 0, M.SUPER_MASK))
        self.assertTrue(dialog.on_key(None, Gdk.KEY_Alt_L, 0, M.SUPER_MASK | M.ALT_MASK))
        self.assertEqual(self.b.log, [])
        self.assertFalse(dialog.error.get_visible())

    def test_capture_refuses_a_key_alone(self):
        g = self.group()
        dialog = g.capture(g.rows["pause"], present=False)
        self.assertTrue(dialog.on_key(None, Gdk.KEY_c, 0, 0))
        self.assertTrue(dialog.error.get_visible())
        self.assertIn("Super, Ctrl ou Alt", dialog.error.get_label())
        self.assertEqual(self.b.log, [])

    def test_backend_error_is_shown(self):
        g = self.group()
        with mock.patch.object(sc, "install", side_effect=sc.ShortcutError("Réglage verrouillé")):
            g.rows["pause"].switch.set_active(True)
        self.assertEqual(self.toasts[-1], "Réglage verrouillé")
        self.assertFalse(g.rows["pause"].switch.get_active())

    def test_unsupported_desktop(self):
        g = self.group(backend=sc.MemoryBackend())
        self.assertEqual(g.rows, {})
        self.assertIn("introuvables", g.get_description())
        self.assertEqual(len(g.extra), len(sc.ACTIONS))
        self.assertEqual(g.extra[3].get_subtitle(), "/usr/bin/ccs next --notifier")

    def test_outdated_commands(self):
        sc.install("suivant", backend=self.b)
        self.b.set(sc.CUSTOM_SCHEMA, {"command": "/vieux/ccs next"}, DIR + "ccs-suivant/")
        g = self.group()
        self.assertTrue(g.update_btn.get_visible())
        self.assertIn("mettre à jour", g.rows["suivant"].get_subtitle())
        g.update_btn.emit("clicked")
        self.assertEqual(custom(self.b, DIR + "ccs-suivant/")["command"], "/usr/bin/ccs next --notifier")
        self.assertFalse(g.update_btn.get_visible())

    def test_external_change_refreshes(self):
        sc.install("ouvrir", backend=self.b)
        g = self.group()
        g.start_watching()
        self.addCleanup(g.stop_watching)
        self.b.set(sc.MEDIA_KEYS, {sc.CUSTOM_KEY: list(FOREIGN)})  # retiré dans Paramètres
        ctx = GLib.MainContext.default()
        while ctx.pending():
            ctx.iteration(False)
        self.assertFalse(g.rows["ouvrir"].switch.get_active())
        g.stop_watching()
        self.assertEqual(self.b._watchers, {})


if __name__ == "__main__":
    unittest.main()
