"""Mot de passe root au bureau : dialogue à `root.ask`, erreur, refus, fermeture à
`root.resolved` et à l'expiration, indicateur « root gardé » et « Oublier », avis.
Faux pont, sous Xvfb seulement."""

import unittest
from types import SimpleNamespace

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib, Gtk  # noqa: F401
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False

ASK = {"id": "r1", "machine": "mawena-cloud", "command": "apt update", "expires_at": 4e9, "tries_left": 3}


class FakeConn:
    def __init__(self):
        self.listeners, self.state, self.calls = set(), "online", []
        self.client = SimpleNamespace(on_event=None)
        self.chat_events = []
        self.client.on_event = lambda n, d: self.chat_events.append(n)   # comme RemoteConnection
        self.answer_result = ({"ok": True}, None)
        self.status = {"machine": "mawena-cloud", "kept": False, "remaining": 0, "pending": None}

    def call(self, method, callback=None, **params):
        self.calls.append((method, params))
        if callback is None:
            return
        if method == "root.answer":
            callback(*self.answer_result)
        elif method == "root.status":
            callback(dict(self.status), None)
        else:
            callback({}, None)

    def methods(self):
        return [m for m, _ in self.calls]


def flush():
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)


@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class RootPromptTest(unittest.TestCase):
    def setUp(self):
        from ccs_app.gui import root_prompt
        self.mod = root_prompt
        self.toasts = []
        self.win = Gtk.Window()
        self.win.toast = self.toasts.append
        self.addCleanup(self.win.destroy)
        self.win.present()
        self.conn = FakeConn()
        self.guard = root_prompt.RootGuard(self.win)
        self.guard.attach(self.conn)
        self.addCleanup(self.guard.close)    # avant win.destroy : pas de minuterie orpheline

    def emit(self, name, data):
        self.conn.client.on_event(name, data)
        flush()

    def test_status_at_start_and_events_chained(self):
        self.assertIn("root.status", self.conn.methods())
        self.emit("chat.event", {})
        self.assertEqual(self.conn.chat_events, ["chat.event"])   # les chats reçoivent toujours

    def test_ask_opens_dialog_and_sends_password_once(self):
        self.emit("root.ask", dict(ASK))
        d = self.guard.dialog
        self.assertIsInstance(d.entry, Gtk.PasswordEntry)
        self.assertIn("mawena-cloud", d.machine_label.get_label())
        self.assertEqual(d.command_label.get_label(), "apt update")
        self.assertIn("3 essais", d.tries_label.get_label())
        self.assertFalse(d.send_button.get_sensitive())
        d.entry.set_text("s3cret")
        self.assertTrue(d.send_button.get_sensitive())
        d.send_button.emit("clicked")
        flush()
        answer = [c for c in self.conn.calls if c[0] == "root.answer"]
        self.assertEqual(answer, [("root.answer", {"id": "r1", "password": "s3cret"})])
        self.assertEqual(d.entry.get_text(), "")
        self.assertIsNone(self.guard.dialog)
        self.assertTrue(any("accepté" in t for t in self.toasts))
        self.assertFalse(any("s3cret" in t for t in self.toasts))

    def test_wrong_password_keeps_dialog_with_error(self):
        self.conn.answer_result = ({"ok": False, "error": "Mot de passe incorrect."}, None)
        self.emit("root.ask", dict(ASK))
        d = self.guard.dialog
        d.entry.set_text("faux")
        d.send()
        self.assertIs(self.guard.dialog, d)
        self.assertTrue(d.error_label.get_visible())
        self.assertEqual(d.entry.get_text(), "")
        self.emit("root.ask", dict(ASK, tries_left=1, error="Mot de passe incorrect."))
        self.assertIs(self.guard.dialog, d)
        self.assertIn("1 essai restant", d.tries_label.get_label())

    def test_rpc_error_code_is_translated(self):
        self.conn.answer_result = (None, SimpleNamespace(code="conflit", message="x"))
        self.emit("root.ask", dict(ASK))
        self.guard.dialog.entry.set_text("pw")
        self.guard.dialog.send()
        self.assertIn("autre appareil", self.guard.dialog.error_label.get_label())

    def test_deny_cancels(self):
        self.emit("root.ask", dict(ASK))
        self.guard.dialog.deny_button.emit("clicked")
        flush()
        self.assertIn(("root.answer", {"id": "r1", "cancel": True}), self.conn.calls)
        self.assertIsNone(self.guard.dialog)

    def test_resolved_and_expiry_close(self):
        self.emit("root.ask", dict(ASK))
        self.emit("root.resolved", {"id": "autre", "ok": False})
        self.assertIsNotNone(self.guard.dialog)
        self.emit("root.resolved", {"id": "r1", "ok": True})
        self.assertIsNone(self.guard.dialog)
        self.emit("root.ask", dict(ASK, id="r2", expires_at=1))
        self.guard.dialog._check_expiry()
        flush()
        self.assertIsNone(self.guard.dialog)

    def test_closed_dialog_can_be_reopened_from_header(self):
        self.emit("root.ask", dict(ASK))
        self.guard.dialog.emit("closed")          # fermé par Échap : ni refus ni réponse
        flush()
        self.assertTrue(self.guard.button.get_visible())
        self.assertEqual(self.guard.label.get_label(), "root demandé")
        self.guard.reopen()
        self.assertEqual(self.guard.dialog.request_id, "r1")

    def test_kept_indicator_forget_and_notices(self):
        self.conn.status = {"machine": "mawena-cloud", "kept": True, "remaining": 2520, "pending": None}
        self.guard.refresh()
        self.assertTrue(self.guard.button.get_visible())
        self.assertEqual(self.guard.label.get_label(), "root gardé, 42 min")
        self.assertTrue(self.guard.forget_button.get_visible())
        self.emit("root.used", {"machine": "mawena-cloud", "command": "apt upgrade", "at": 1})
        self.assertTrue(any("apt upgrade" in t for t in self.toasts))
        self.guard.forget_button.emit("clicked")
        self.assertIn("root.forget", self.conn.methods())
        self.emit("root.forgotten", {"machine": "mawena-cloud", "reason": "expired"})
        self.assertFalse(self.guard.button.get_visible())
        self.assertTrue(any("heure" in t for t in self.toasts))

    def test_pending_from_status_opens_dialog(self):
        self.conn.status = dict(self.conn.status, pending=dict(ASK))
        self.guard.refresh()
        self.assertEqual(self.guard.dialog.request_id, "r1")

    def test_no_bridge_retries_later(self):
        guard = self.mod.RootGuard(self.win)
        guard.attach(None)                       # pas de pont : aucun appel, rien d'affiché
        self.assertIsNone(guard.conn)
        self.assertFalse(guard.button.get_visible())


if __name__ == "__main__":
    unittest.main()
