"""Onglet Réseau du bureau : fiches des appareils (adresses, chemin, mesure, renommer, retirer),
ajout d'un appareil, ordre des sections comme le web, repli sur ce PC sans serveur CCS.
Faux pont et faux moteur (aucun réseau). Sous Xvfb."""

import unittest

from tests.helpers import HomeTestCase, gui_ready

GTK = gui_ready()
if GTK:
    from gi.repository import Adw
    from ccs_app.gui import network_page
    from ccs_app.gui.network_page import MeshApi, MeshGroup, NetworkPage
    from tests.test_machines_page_gui import FakeBackend, sync_runner

STATUS = {
    "url": "https://network.mawena.cloud", "domain": "mesh.mawena.cloud", "installed": True,
    "server": True, "state": "Running",
    "self": {"name": "vps", "host": "vps", "os": "linux", "ips": ["100.64.0.1"], "online": True,
             "path": "self", "endpoint": "", "relay": "", "addrs": [], "rx": 0, "tx": 0},
    "peers": [
        {"name": "pixel", "host": "pixel", "os": "android", "ips": ["100.64.0.3"], "online": True,
         "path": "direct", "endpoint": "1.2.3.4:41641", "relay": "",
         "addrs": ["192.168.1.20:41641", "1.2.3.4:41641", "[2a02::1]:41641"], "rx": 2048, "tx": 5 * 2 ** 20},
        {"name": "pc-bureau", "host": "pc-bureau", "os": "linux", "ips": ["100.64.0.2"], "online": False,
         "path": "offline", "endpoint": "", "relay": "", "addrs": [], "rx": 0, "tx": 0}],
    "nodes": [{"id": 4, "name": "iphone", "host": "iphone", "ips": ["100.64.0.4"], "online": False}],
}


class FakeBridge:
    def __init__(self, status=None):
        self.calls = []
        self.status = status or STATUS

    def __call__(self, method, **params):
        self.calls.append((method, params))
        if method == "network.status":
            return self.status
        if method == "network.ping":
            return {"ok": True, "path": "lan", "via": "192.168.1.20:41641", "ms": 3.5}
        if method == "network.key":
            return {"key": "k", "linux": ["curl x | sh", "tailscale up --authkey k"]}
        if method == "network.register":
            return {"name": "iphone"}
        return {"ok": True}


def titles(group):
    """Titres des lignes d'un groupe (parcours de l'arbre des widgets)."""
    out = []

    def walk(w):
        while w is not None:
            if isinstance(w, Adw.PreferencesRow):
                out.append(w.get_title())
            else:
                walk(w.get_first_child())
            w = w.get_next_sibling()
    walk(group.get_first_child())
    return out


@unittest.skipUnless(GTK, "affichage graphique requis (CCS_GUI_TESTS=1 sous xvfb-run)")
class MeshGroupTest(HomeTestCase):
    def make(self, status=None):
        self.bridge = FakeBridge(status)
        self.toasts = []
        g = MeshGroup(toast=self.toasts.append, runner=sync_runner, api=MeshApi(call=self.bridge))
        g.here = "pc-bureau"
        g.refresh()
        return g

    def row(self, g, name):
        return next(r for r in g._rows if r.get_title() == name)

    def test_cards_like_the_web(self):
        g = self.make()
        self.assertEqual([r.get_title() for r in g._rows], ["vps", "pixel", "pc-bureau", "iphone"])
        desc = g.get_description()
        self.assertIn("Connecté · 2/3 en ligne · 0 en local · 1 en direct · 0 par relais", desc)
        pixel = self.row(g, "pixel")
        self.assertIn("Direct par internet", pixel.get_subtitle())
        self.assertIn("android", pixel.get_subtitle())
        self.assertIsNotNone(pixel.measure)
        self.assertIsNotNone(pixel.forget)
        inner = titles(pixel)
        self.assertIn("100.64.0.3", inner)
        self.assertIn("Adresses publiées", inner)
        self.assertIn("Trafic", inner)
        self.assertEqual(network_page.published(pixel.device),
                         "Local : 192.168.1.20\nPublic : 1.2.3.4\nIPv6 : 2a02::1")
        vps = self.row(g, "vps")
        self.assertIn("Serveur CCS", vps.get_subtitle())
        self.assertIsNone(vps.measure)
        self.assertIsNone(vps.forget)               # pas de retrait du serveur lui-même
        self.assertIsNotNone(vps.rename)
        off = self.row(g, "pc-bureau")
        self.assertIn("Hors ligne", off.get_subtitle())
        self.assertIsNone(off.measure)
        self.assertTrue(off.has_css_class("dim-label"))
        self.assertIn("Hors ligne", self.row(g, "iphone").get_subtitle())   # connu du serveur seulement

    def test_measure_rename_remove(self):
        g = self.make()
        pixel = self.row(g, "pixel")
        pixel.measure.emit("clicked")
        self.assertIn(("network.ping", {"name": "pixel"}), self.bridge.calls)
        self.assertIn("pixel : 3,5 ms · Réseau local · 192.168.1.20:41641", self.toasts)
        self.assertIn("Mesure", titles(self.row(g, "pixel")))

        alert = g.ask_rename(self.row(g, "pixel").device)
        alert.entry.set_text("Mauvais Nom")
        alert.emit("response", "rename")
        self.assertNotIn("network.rename", [c[0] for c in self.bridge.calls])
        alert.entry.set_text("pixel-8")
        alert.emit("response", "rename")
        self.assertIn(("network.rename", {"name": "pixel", "new": "pixel-8"}), self.bridge.calls)

        alert = g.ask_remove(self.row(g, "pixel").device)
        alert.emit("response", "cancel")
        self.assertNotIn("network.remove", [c[0] for c in self.bridge.calls])
        alert.emit("response", "remove")
        self.assertIn(("network.remove", {"name": "pixel"}), self.bridge.calls)
        self.assertIn("Retiré du réseau", self.toasts)

    def test_not_server_hides_rename(self):
        g = self.make(dict(STATUS, server=False))
        self.assertTrue(all(r.rename is None and r.forget is None for r in g._rows))

    def test_machines_attach_to_cards(self):
        g = self.make()
        g.here = "vps"                   # la machine « locale » du relais est ce PC : le VPS ici
        g.set_machines(FakeBackend().overview_value["machines"])
        names = [r.get_title() for r in g._rows]
        # chaque machine rattachée à sa fiche ; Portable n'est pas dans le réseau maillé : sa
        # propre fiche, hors ligne (« Par Ricochet » quand elle est en ligne).
        self.assertEqual(names, ["vps", "pixel", "pc-bureau", "iphone", "Portable"])
        self.assertIn("Calcul", titles(self.row(g, "pc-bureau")))
        self.assertIn("Calcul", titles(self.row(g, "vps")))
        self.assertNotIn("Calcul", titles(self.row(g, "pixel")))
        self.assertIn("Hors ligne", self.row(g, "Portable").get_subtitle())

    def test_falls_back_to_this_pc(self):
        def down(*_a, **_k):
            raise RuntimeError("Aucun serveur CCS appairé")
        api = MeshApi(call=down, local_status=lambda: dict(STATUS, server=False))
        g = MeshGroup(runner=sync_runner, api=api)
        g.refresh()
        self.assertFalse(api.remote)
        self.assertIn("Vu depuis ce PC", g.get_description())
        self.assertIn("Cet appareil", g._rows[0].get_subtitle())


@unittest.skipUnless(GTK, "affichage graphique requis (CCS_GUI_TESTS=1 sous xvfb-run)")
class NetworkPageTest(HomeTestCase):
    def make(self, settings=None):
        self.bridge = FakeBridge()
        self.backend = FakeBackend()
        if settings is not None:
            self.backend.settings = lambda: settings
        self.toasts = []
        return NetworkPage(toast=self.toasts.append, runner=sync_runner, backend=self.backend,
                           mesh_api=MeshApi(call=self.bridge), sound=Adw.PreferencesGroup(title="Son partagé"),
                           default_cwd="/tmp")

    def groups(self, page):
        out = []

        def walk(w):
            while w is not None:
                if isinstance(w, Adw.PreferencesGroup):
                    out.append(w.get_title())
                else:
                    walk(w.get_first_child())
                w = w.get_next_sibling()
        walk(page.get_first_child())
        return out

    def test_sections_in_web_order(self):
        p = self.make()
        self.assertEqual(self.groups(p), ["Appareils", "Son partagé", "Lecteurs", "Travaux", "Lancer une commande",
                                          "Ajouter un appareil", "Secours Ricochet"])
        p.mesh.refresh()
        self.assertIn("pc-bureau", [r.get_title() for r in p.mesh._rows])

    def test_add_device_key_and_phones(self):
        p = self.make()                     # pas de jeton opérateur : clé jetable du réseau
        p.mesh.refresh()
        add = p.add_device
        self.assertTrue(add.pc.get_visible())
        self.assertTrue(add.k_name.get_visible())
        self.assertFalse(p.a_id.get_visible())
        add.k_name.set_text("laptop-maison")
        add.k_go.emit("clicked")
        self.assertIn(("network.key", {"name": "laptop-maison"}), self.bridge.calls)
        self.assertEqual(add.k_line.get_text(), "sudo sh -c 'curl x | sh && tailscale up --authkey k'")
        self.assertTrue(add.k_copy.get_visible())
        key = add.phones["iPhone"].key
        key.set_text("hskey-authreq-abcdef12")
        add.register(key)
        self.assertIn(("network.register", {"key": "hskey-authreq-abcdef12"}), self.bridge.calls)
        self.assertIn("iphone ajouté au réseau", self.toasts)
        self.assertEqual(key.get_text(), "")

    def test_add_pc_by_ricochet_with_operator_token(self):
        p = self.make({"relay": "https://r", "token_set": True, "operator_set": True, "path": "/x"})
        self.assertTrue(p.a_id.get_visible())
        self.assertFalse(p.add_device.k_name.get_visible())

    def test_not_server_hides_phones(self):
        p = self.make()
        self.bridge.status = dict(STATUS, server=False)
        p.mesh.refresh()
        self.assertFalse(p.add_device.phones["Android"].get_visible())
        self.assertFalse(p.add_device.pc.get_visible())
        self.assertIn("depuis le serveur du réseau", p.add_device.get_description())


if __name__ == "__main__":
    unittest.main()
