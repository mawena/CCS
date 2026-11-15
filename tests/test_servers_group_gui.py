"""Réglages → Serveurs : appairage dans un fil, retrait confirmé, mot de passe jamais gardé.
Sous Xvfb ; appairage simulé (aucun réseau)."""

import unittest

from tests.helpers import HomeTestCase, gui_ready

GTK = gui_ready()
if GTK:
    from ccs_app.gui.servers_group import ServersGroup
    from ccs_app.remote import servers


def sync_runner(work, done):
    try:
        result, error = work(), None
    except Exception as e:  # noqa: BLE001
        result, error = None, e
    done(result, error)


@unittest.skipUnless(GTK, "affichage graphique requis (CCS_GUI_TESTS=1 sous xvfb-run)")
class ServersGroupTest(HomeTestCase):
    def make(self, replies):
        self.sent = []

        def pair(url, user, password, code, name):
            self.sent.append(("pair", url, user, password, code))
            r = replies.pop(0)
            if r == "ok":
                s = servers.Server("ccs.mawena.cloud", "https://ccs.mawena.cloud", user, "APP-1")
                servers.add(s)
                return s
            return r

        def finish(url, user, pending, code, name):
            self.sent.append(("finish", pending, code))
            s = servers.Server("ccs.mawena.cloud", "https://ccs.mawena.cloud", user, "APP-2")
            servers.add(s)
            return s
        return ServersGroup(runner=sync_runner, pair=pair, finish=finish)

    def fill(self, g, url="ccs.mawena.cloud", user="alice", password="mdp-secret", code=""):
        g.open_add_dialog()
        g.f_url.set_text(url)
        g.f_user.set_text(user)
        g.f_password.set_text(password)
        g.f_code.set_text(code)

    def test_add_server_pairs_in_thread(self):
        ran = []

        def runner(work, done):
            ran.append(1)
            sync_runner(work, done)
        g = self.make(["ok"])
        g.runner = runner
        self.fill(g, code="123456")
        g.submit()
        self.assertEqual(ran, [1])
        self.assertEqual(self.sent[0], ("pair", "ccs.mawena.cloud", "alice", "mdp-secret", "123456"))
        self.assertEqual(g.server_names(), ["ccs.mawena.cloud"])
        self.assertIsNone(g.dialog)

    def test_code_then_enroll_flow(self):
        g = self.make([{"status": "code"}])
        self.fill(g)
        g.submit()
        self.assertTrue(g.f_code.get_visible())
        self.assertIsNotNone(g.dialog)
        g2 = self.make([{"status": "enroll", "pending": "P", "secret": "ABC", "qr_svg": "<svg/>"}])
        self.fill(g2)
        g2.submit()
        self.assertTrue(g2.qr.get_visible())
        g2.f_code.set_text("654321")
        g2.submit()
        self.assertEqual(self.sent[-1], ("finish", "P", "654321"))
        self.assertEqual(g2.server_names(), ["ccs.mawena.cloud"])

    def test_refused_shows_message(self):
        g = self.make([{"status": "refused", "message": "Identifiant, mot de passe ou code incorrect"}])
        self.fill(g, code="1")
        g.submit()
        self.assertIn("incorrect", g.message.get_text())
        self.assertEqual(g.server_names(), [])

    def test_remove_asks_confirmation(self):
        servers.add(servers.Server("vps", "https://v", "alice", "T"))
        g = self.make([])
        g.ask_remove("vps")
        self.assertEqual(g.server_names(), ["vps"])           # rien avant la confirmation
        g.last_alert.emit("response", "cancel")
        self.assertEqual(g.server_names(), ["vps"])
        g.ask_remove("vps")
        g.last_alert.emit("response", "remove")
        self.assertEqual(g.server_names(), [])

    def test_password_not_kept(self):
        g = self.make(["ok"])
        self.fill(g, code="123456")
        g.submit()
        self.assertNotIn("mdp-secret", servers.path().read_text())
        self.assertFalse(hasattr(g, "f_password") and g.f_password.get_text())


if __name__ == "__main__":
    unittest.main()
