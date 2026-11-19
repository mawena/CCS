"""Réglages → page Machines du bureau : commandes en cours (arrêt confirmé), machines du relais,
réglages du client Ricochet. Relais et SSH remplacés ; affichage virtuel (xvfb)."""

import unittest
from unittest import mock

from ccs_app import distant
from tests.helpers import HomeTestCase

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk  # noqa: F401
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False


def machines():
    return [distant.Machine(id="pc", name="PC", online=True, ports=[22], cores=8, load=2.0,
                            mem_used=4 << 30, mem_total=16 << 30),
            distant.Machine(id="vieux", online=False)]


class SubtitleTest(unittest.TestCase):
    def test_subtitles(self):
        from ccs_app.gui import machines_page as mp
        pc, vieux = machines()
        self.assertEqual(mp.machine_subtitle(vieux), "Hors ligne")
        self.assertEqual(mp.machine_subtitle(pc, ["flutter"]),
                         "charge 2.0 sur 8 cœurs · mémoire 4 / 16 Go · outils : flutter")
        pc.ports = []
        self.assertIn("tunnel SSH non activé", mp.machine_subtitle(pc))
        self.assertEqual(mp.since(100, now=100 + 3725), "1 h 02")
        self.assertEqual(mp.since(100, now=165), "1 min 05")


@unittest.skipUnless(GTK, "GTK 4 / libadwaita indisponibles")
class MachinesPageTest(HomeTestCase):
    def page(self):
        from ccs_app.gui.machines_page import MachinesPage
        self.toasts = []
        return MachinesPage(toast=self.toasts.append, runner=lambda work, done: done(*self._run(work)),
                            fetch=machines)

    @staticmethod
    def _run(work):
        try:
            return work(), None
        except Exception as e:  # noqa: BLE001
            return None, e

    def test_lists_machines_and_running_commands(self):
        records = [{"pid": 77, "machine": "pc", "projet": "/p", "dossier": "app",
                    "commande": "flutter build apk", "debut": 0}]
        with mock.patch.object(distant, "running", return_value=records):
            p = self.page()
            p.reload()
        self.assertEqual([r.get_title() for r in p._rows["running"]], ["flutter build apk"])
        self.assertEqual([r.get_title() for r in p._rows["machines"]], ["PC (pc)", "vieux"])
        killed = []
        with mock.patch.object(distant, "running", return_value=records), \
                mock.patch.object(distant.os, "kill", lambda pid, sig: killed.append(pid)):
            p.ask_stop(records[0])
            p.last_alert.emit("response", "cancel")
            self.assertEqual(killed, [])
            p.last_alert.emit("response", "stop")
        self.assertEqual(killed, [77])
        self.assertEqual(self.toasts, ["Commande arrêtée"])

    def test_relay_error_is_shown(self):
        from ccs_app.gui.machines_page import MachinesPage

        def broken():
            raise distant.DistantError("Relais injoignable")
        p = MachinesPage(toast=lambda _t: None, runner=lambda w, d: d(*self._run(w)), fetch=broken)
        p.reload()
        self.assertEqual(p._rows["machines"][0].get_subtitle(), "Relais injoignable")

    def test_settings_save_and_keep_token(self):
        p = self.page()
        p.f_relais.set_text("https://relais.test")
        self.assertFalse(p.save_settings())                 # pas encore de jeton
        p.f_jeton.set_text("secret")
        self.assertTrue(p.save_settings())
        self.assertEqual(p.f_jeton.get_text(), "")
        p.f_relais.set_text("https://autre.test")
        self.assertTrue(p.save_settings())
        self.assertEqual(distant.load_client(), {"relais": "https://autre.test", "jeton": "secret"})
