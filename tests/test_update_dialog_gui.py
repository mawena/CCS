"""Dialogue « Mise à jour » (nécessite un affichage, p. ex. Xvfb) : fausses fonctions
d'installation, aucun réseau ni pkexec."""

import time
import unittest

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib, Gtk
    Adw.init()
    from gi.repository import Gdk
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False

from ccs_app import installer  # noqa: E402


def spin(cond, timeout=5.0):
    ctx = GLib.MainContext.default()
    end = time.time() + timeout
    while not cond() and time.time() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


PLAN = installer.Plan("0.7.0", "## Ajouté\n- **Mise à jour** en un clic", "ccs_0.7.0_all.deb", "u", "s")


@unittest.skipUnless(GTK, "affichage GTK 4 absent (lancer sous Xvfb)")
class UpdateDialogTest(unittest.TestCase):
    def make(self, install, fetch=None, restart=None):
        from ccs_app.gui.update_dialog import UpdateDialog
        d = UpdateDialog("0.7.0", "https://github.com/mawena/CCS/releases/tag/v0.7.0",
                         on_restart=restart or (lambda: None),
                         fetch=fetch or (lambda v: PLAN), do_install=install)
        return d

    def test_notes_puis_installation_reussie(self):
        steps = []

        def fake(plan, progress=None):
            for p in installer.PHASES:
                progress(p, None)
                steps.append(p)
            return installer.Result(True, "0.7.0", "CCS 0.7.0 est installé.")
        restarted = []
        d = self.make(fake, restart=lambda: restarted.append(1))
        self.assertTrue(spin(lambda: d.button.get_sensitive()))
        self.assertIn("• Mise à jour en un clic", d.notes.get_label())
        d.on_button(d.button)
        self.assertTrue(spin(lambda: d.button.get_label() == "Redémarrer l'application"))
        self.assertEqual(steps, list(installer.PHASES))
        self.assertEqual(d.status.get_label(), "CCS 0.7.0 est installé.")
        d.on_button(d.button)
        self.assertEqual(restarted, [1])

    def test_echec_avec_commande_a_copier(self):
        def fake(plan, progress=None):
            raise installer.InstallError("pkexec est introuvable", fallback="sudo apt install /tmp/x.deb")
        d = self.make(fake)
        spin(lambda: d.button.get_sensitive())
        d.on_button(d.button)
        self.assertTrue(spin(lambda: d.button.get_label() == "Réessayer"))
        self.assertTrue(d.command_entry.get_visible())
        self.assertEqual(d.command_entry.get_text(), "sudo apt install /tmp/x.deb")
        self.assertTrue(d.get_can_close())

    def test_notes_indisponibles(self):
        def fetch(v):
            raise installer.InstallError("Réseau indisponible")
        d = self.make(lambda *a, **k: None, fetch=fetch)
        self.assertTrue(spin(lambda: "Réseau" in d.status.get_label()))
        self.assertFalse(d.button.get_sensitive())

    def test_commande_de_relance(self):
        from ccs_app.gui.update_dialog import relaunch_command
        cmd = relaunch_command()
        self.assertEqual(cmd[:2], ["sh", "-c"])
        self.assertIn(cmd[4], __import__("sys").executable)


if __name__ == "__main__":
    unittest.main()
