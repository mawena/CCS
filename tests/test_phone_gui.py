"""Groupe « Téléphone » des Réglages : widgets créés sans être affichés (tests sautés sans
GTK 4 / libadwaita / affichage). Aucun réseau (`sender` simulé), presse-papiers simulé."""

import importlib.util
import unittest
from unittest import mock

from ccs_app import phone

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False

TOPIC = "ccs-abcdefghijklmnopqrstuvwx"


@unittest.skipUnless(GTK, "GTK 4, libadwaita ou affichage absents")
class PhoneGroupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Adw.init()

    def setUp(self):
        from ccs_app.gui import phone_group
        self.mod = phone_group
        self.s, self.saved, self.toasts, self.sent = {}, [], [], []
        self.clip = mock.MagicMock()
        p = mock.patch.object(phone_group.GLib, "idle_add", side_effect=lambda f, *a: f(*a))
        p.start()
        self.addCleanup(p.stop)

    def group(self, sender=None):
        def fake(settings):
            self.sent.append(settings)
            return True, "Message envoyé : regarde ton téléphone."
        g = self.mod.PhoneGroup(self.s, lambda: self.saved.append(phone.config(self.s)),
                                toast=self.toasts.append, sender=sender or fake, run=lambda f: f())
        g.get_clipboard = lambda: self.clip
        return g

    def test_disabled_by_default_and_nothing_saved_on_creation(self):
        g = self.group()
        self.assertFalse(g.enabled.get_active())
        self.assertEqual(self.saved, [])
        self.assertEqual(self.s, {})
        self.assertFalse(g.try_button.get_sensitive())
        self.assertEqual(list(g.events), [k for k, _l in phone.EVENTS])

    def test_enabling_creates_a_secret_topic_once(self):
        g = self.group()
        g.enabled.set_active(True)
        topic = self.s["phone"]["topic"]
        self.assertTrue(topic.startswith("ccs-") and phone.valid_topic(topic))
        self.assertTrue(self.s["phone"]["enabled"])
        self.assertEqual(len(self.saved), 1)
        g.enabled.set_active(False)
        g.enabled.set_active(True)
        self.assertEqual(self.s["phone"]["topic"], topic)          # le canal est gardé
        self.assertIn(topic, g.link.get_subtitle())
        self.assertTrue(g.copy_button.get_sensitive())

    def test_new_topic_changes_it(self):
        self.s["phone"] = {"enabled": True, "topic": TOPIC}
        g = self.group()
        g.new_topic()
        self.assertNotEqual(self.s["phone"]["topic"], TOPIC)
        self.assertEqual(g.topic.get_subtitle(), self.s["phone"]["topic"])

    def test_server_validation(self):
        self.s["phone"] = {"enabled": True, "topic": TOPIC}
        g = self.group()
        g.server.set_text("ftp://mauvais")
        g.on_server(g.server)
        self.assertEqual(g.server.get_text(), "https://ntfy.sh")
        self.assertTrue(self.toasts)
        g.server.set_text("https://ntfy.exemple.org/")
        g.on_server(g.server)
        self.assertEqual(self.s["phone"]["server"], "https://ntfy.exemple.org")
        self.assertEqual(g.link.get_subtitle(), "https://ntfy.exemple.org/" + TOPIC)

    def test_event_switches(self):
        self.s["phone"] = {"enabled": True, "topic": TOPIC}
        g = self.group()
        g.events["task"].set_active(False)
        self.assertFalse(self.s["phone"]["events"]["task"])
        self.assertTrue(self.s["phone"]["events"]["waiting"])

    def test_copy_link(self):
        self.s["phone"] = {"enabled": True, "topic": TOPIC}
        g = self.group()
        self.assertTrue(g.copy_link())
        self.clip.set.assert_called_once_with("https://ntfy.sh/" + TOPIC)
        self.assertEqual(self.toasts[-1], "Lien copié")

    def test_try_button_uses_the_sender_and_toasts(self):
        self.s["phone"] = {"enabled": True, "topic": TOPIC}
        g = self.group()
        g.try_now()
        self.assertEqual(self.sent[0]["phone"]["topic"], TOPIC)
        self.assertIn("téléphone", self.toasts[-1])
        self.assertTrue(g.try_button.get_sensitive())

    def test_try_failure_is_reported_not_raised(self):
        self.s["phone"] = {"enabled": True, "topic": TOPIC}

        def boom(_settings):
            raise RuntimeError("secret")
        g = self.group(sender=boom)
        g.try_now()
        self.assertIn("impossible", self.toasts[-1])
        self.assertNotIn("secret", self.toasts[-1])

    def test_qr_row_hidden_without_qr(self):
        self.s["phone"] = {"enabled": True, "topic": TOPIC}
        with mock.patch.object(self.mod, "qr_texture", return_value=None):
            self.assertFalse(self.group().qr_row.get_visible())

    @unittest.skipUnless(importlib.util.find_spec("qrcode"), "module qrcode absent")
    def test_real_qr_texture_and_row(self):
        t = self.mod.qr_texture("https://ntfy.sh/" + TOPIC)
        self.assertIsNotNone(t)
        self.assertEqual(t.get_width(), t.get_height())
        self.s["phone"] = {"enabled": True, "topic": TOPIC}
        self.assertTrue(self.group().qr_row.get_visible())

    def test_missing_qrcode_module_gives_none(self):
        with mock.patch.dict("sys.modules", {"qrcode": None}):
            self.assertIsNone(self.mod.qr_texture("x"))
            self.assertFalse(self.mod.qr_available())


if __name__ == "__main__":
    unittest.main()
