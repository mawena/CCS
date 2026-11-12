"""Onglet de chat de bout en bout, avec le faux `claude` (jamais le vrai)."""

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from tests.helpers import HomeTestCase, gui_ready

GTK = gui_ready()
FAKE = str(Path(__file__).parent / "fake_claude.py")
FIXTURES = Path(__file__).parent / "fixtures" / "chat"

if GTK:
    from gi.repository import GLib, Gtk
    from ccs_app import chat_engine, terminal
    from ccs_app import chat_protocol as proto
    from ccs_app.gui.chat_tab import ChatTab


def pump_until(cond, timeout=15.0):
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        while ctx.iteration(False):
            pass
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def descendants(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from descendants(child)
        child = child.get_next_sibling()


def texts(tab):
    return [w.get_label() or "" for w in descendants(tab.messages.box) if isinstance(w, Gtk.Label)]


class FakeOwner:
    """Ce que la page Terminaux fournit à un onglet."""

    def __init__(self):
        self.events, self.dark, self.font = [], False, None

    def changed(self, tab=None):
        self.events.append("changed")

    def emit(self, name, *args):
        self.events.append(name)

    def queue_changed(self, tab):
        self.events.append("queue")

    def schedule_save(self):
        self.events.append("save")

    def shown(self, tab):
        return False

    def on_screen(self):
        return False

    def update_badge(self):
        pass

    def is_split(self):
        return False

    def close(self, tab):
        self.events.append("close")


@unittest.skipUnless(GTK, "tests graphiques : CCS_GUI_TESTS=1 avec xvfb-run")
class ChatTabTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.cwd = Path(self.tmp) / "projet"
        self.cwd.mkdir()
        self.tabs = []

    def tearDown(self):
        for tab in self.tabs:
            tab._closed = True
            tab.engine.stop(grace_s=1)
        super().tearDown()

    def make(self, scenario="reprise-resume.jsonl", session_id=None, env=None, history_path=None, spawn=True):
        environ = {"PATH": os.environ["PATH"], "HOME": str(self.home),
                   "FAKE_CLAUDE_SCENARIO": str(FIXTURES / scenario), **(env or {})}
        launch = terminal.claude_launch(str(self.cwd), session_id, "Essai")
        owner = FakeOwner()
        tab = ChatTab(owner, launch, claude=FAKE, environ=environ, history_path=history_path)
        if spawn:   # la page Sessions, elle, ouvre ses chats sans spawn() : processus au premier envoi
            tab.spawn()
        self.tabs.append(tab)
        return tab, owner

    def say(self, tab, text):
        tab.composer.set_text(text)
        tab.composer.submit()

    def test_send_shows_bubble_and_streams_answer(self):
        tab, _owner = self.make("permissions-allow-toujours.jsonl")
        self.assertIsNone(tab.engine.pid)                          # pas de processus avant l'envoi
        self.say(tab, "Lance la commande `touch essai1.txt` puis dis juste OK.")
        self.assertIn("Lance la commande `touch essai1.txt` puis dis juste OK.", texts(tab))
        self.assertTrue(pump_until(lambda: tab.messages._perms))
        next(iter(tab.messages._perms.values())).allow.emit("clicked")
        self.assertTrue(pump_until(lambda: tab.state.waiting_for == "input"))
        self.assertTrue(any(t.strip() == "OK" for t in texts(tab)))   # la réponse de Claude
        self.assertEqual(tab.state.state, "waiting")

    def test_state_busy_then_waiting(self):
        tab, owner = self.make("permissions-allow-toujours.jsonl")
        self.assertEqual((tab.state.running, tab.state.state), (True, "idle"))
        self.say(tab, "Lance la commande `touch essai1.txt` puis dis juste OK.")
        self.assertEqual(tab.state.state, "busy")
        self.assertTrue(pump_until(lambda: tab.state.waiting_for == "permission"))
        self.assertEqual(tab.state.state, "waiting")
        self.assertFalse(terminal.free_for_input(tab.state))      # jamais d'envoi pendant une demande
        card = tab.messages._perms[next(iter(tab.messages._perms))]
        card.allow.emit("clicked")
        self.assertTrue(pump_until(lambda: tab.state.waiting_for == "input"))
        self.assertTrue(terminal.free_for_input(tab.state))
        self.assertIn("tab-state-changed", owner.events)
        self.assertIsNotNone(tab.state.busy_since)

    def test_permission_card_allow(self):
        tab, _owner = self.make("permissions-allow-toujours.jsonl")
        self.say(tab, "Lance la commande `touch essai1.txt` puis dis juste OK.")
        self.assertTrue(pump_until(lambda: tab.messages._perms))
        card = next(iter(tab.messages._perms.values()))
        self.assertTrue(any("touch essai1.txt" in (w.get_label() or "")
                            for w in descendants(card) if isinstance(w, Gtk.Label)))
        card.allow.emit("clicked")
        self.assertTrue(pump_until(lambda: tab.engine.state == "idle"))
        self.assertTrue(card.answered)

    def test_queue_while_busy(self):
        tab, owner = self.make("permissions-allow-toujours.jsonl")
        self.say(tab, "Lance la commande `touch essai1.txt` puis dis juste OK.")
        self.assertTrue(pump_until(lambda: tab.engine.state == "permission"))
        self.say(tab, "et ensuite ceci")
        self.assertEqual(tab.state.queue, ["et ensuite ceci"])     # en file, pas envoyé
        self.assertIsNotNone(tab.state.queued_at)
        self.assertIn("queue", owner.events)
        self.assertEqual(tab.composer._queue_shown, ["et ensuite ceci"])
        card = next(iter(tab.messages._perms.values()))
        card.allow.emit("clicked")
        self.assertTrue(pump_until(lambda: tab.engine.state == "idle"))
        # la page enverrait maintenant : la décision est celle des terminaux
        decision = terminal.queue_next(tab.state, time.time() + 5)
        self.assertEqual(decision.text, "et ensuite ceci")
        self.assertTrue(tab.send_auto(decision.text))
        self.assertIsNotNone(tab.state.sent_at)

    def test_send_now_from_a_chat_opened_without_spawn(self):
        # Comme un chat ouvert ou rouvert par la page Sessions : pas de spawn(), pas de processus.
        tab, _owner = self.make(spawn=False)
        self.assertFalse(tab.state.running)
        tab.state.queue[:] = ["Réponds juste OK."]
        tab.send_message_now(0)                                    # « Envoyer maintenant »
        self.assertEqual(tab.state.queue, [])
        self.assertIn("Réponds juste OK.", texts(tab))
        self.assertEqual(tab.state.state, "busy")
        self.assertTrue(pump_until(lambda: tab.engine.state == "idle"))

    def test_send_auto_starts_a_chat_without_process(self):
        tab, _owner = self.make(spawn=False)
        self.assertTrue(tab.send_auto("Réponds juste OK."))       # file de messages, reprise, « créer une feuille de route »
        self.assertIsNotNone(tab.state.sent_at)
        self.assertTrue(pump_until(lambda: tab.engine.state == "idle"))

    def test_composer_text_readable_in_dark_mode(self):
        tab, _owner = self.make()
        tab.apply_colors(True)
        self.assertIn("dark", tab.composer.buffer.get_style_scheme().get_id())
        tab.apply_colors(False)
        self.assertNotIn("dark", tab.composer.buffer.get_style_scheme().get_id())

    def test_bar_follows_the_mode_confirmed_by_claude(self):
        tab, _owner = self.make()
        tab._dispatch(proto.Status("bypassPermissions"))
        self.assertEqual(tab.options.rights, "bypassPermissions")
        self.assertEqual(tab.bar.options.rights, "bypassPermissions")
        tab._dispatch(proto.Status("default"))                    # « default » = Demander
        self.assertEqual(tab.options.rights, "manual")

    def test_refused_option_is_shown(self):
        tab, _owner = self.make()
        tab._dispatch(chat_engine.OptionRefused("set_permission_mode", "Cannot set permission mode"))
        self.assertTrue(any("refusé" in t for t in texts(tab)))

    def test_start_failure_shows_notice(self):
        tab, owner = self.make(env={"FAKE_CLAUDE_EXIT": "1"})
        self.say(tab, "Bonjour")
        self.assertTrue(pump_until(lambda: tab._error_notice is not None))
        self.assertTrue(any("Not logged in" in t for t in texts(tab)))
        self.assertFalse(tab.state.running)
        self.assertNotEqual(tab.state.state, "busy")
        self.assertEqual(tab.composer.text, "Bonjour")             # le message n'est pas perdu
        self.assertIn("tab-exited", owner.events)
        button = next(w for w in descendants(tab._error_notice) if isinstance(w, Gtk.Button))
        button.emit("clicked")                                    # « Relancer »
        self.assertTrue(tab.state.running)
        self.assertIsNone(tab._error_notice)

    def test_reopened_chat_shows_history_without_process(self):
        journal = Path(self.tmp) / "conv.jsonl"
        lines = [{"type": "user", "message": {"role": "user", "content": "ancienne question"}},
                 {"type": "assistant", "message": {"id": "m1", "role": "assistant",
                                                   "content": [{"type": "text", "text": "ancienne réponse"}]}}]
        journal.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
        tab, _owner = self.make(session_id="sess-123", history_path=str(journal))
        self.assertTrue(pump_until(lambda: "ancienne réponse" in " ".join(texts(tab))))
        self.assertIn("ancienne question", texts(tab))
        self.assertIsNone(tab.engine.pid)
        self.assertIsNone(tab.state.pid)
        self.assertEqual(tab.state.session_id, "sess-123")

    def test_stop_button_interrupts(self):
        tab, _owner = self.make("refus-et-interruption.jsonl")
        self.say(tab, "Lance la commande `touch essai4.txt`. Si elle est refusée, écris alors les nombres.")
        self.assertTrue(pump_until(lambda: tab.messages._perms))
        next(iter(tab.messages._perms.values())).deny.emit("clicked")
        self.assertTrue(pump_until(lambda: tab.state.waiting_for == "input"))
        self.say(tab, "Réponds juste OK.")
        self.assertEqual(tab.state.state, "busy")
        self.assertTrue(tab.composer.stop_button.get_visible())
        tab.composer.stop_button.emit("clicked")
        self.assertTrue(pump_until(lambda: any(t == "Arrêté." for t in texts(tab))))
        self.assertTrue(pump_until(lambda: tab.engine.state == "stopped"))
        self.assertFalse(tab.composer.stop_button.get_visible())
        self.assertTrue(tab.state.running)                          # arrêt voulu : pas d'erreur
        self.assertIsNone(tab._error_notice)

    def test_options_change_is_kept_and_announced(self):
        tab, owner = self.make()
        tab.bar.model_picker.rows["haiku"].emit("clicked")
        self.assertEqual(tab.options.model, "haiku")
        self.assertEqual(tab.engine.options.model, "haiku")
        self.assertTrue(any("Modèle changé" in t for t in texts(tab)))
        self.assertIn("save", owner.events)

    def test_page_interface(self):
        tab, _owner = self.make()
        for name in ("state", "panel", "page", "focus", "hang_up", "update_page", "attention", "refresh_queue",
                     "toggle_queue", "send_auto", "show_notice", "apply_colors", "set_title", "spawn",
                     "foreground_busy", "queue_reason", "limits_done"):
            self.assertTrue(hasattr(tab, name), name)
        self.assertFalse(tab.foreground_busy())
        tab.apply_colors(True)
        tab.show_notice("Limite atteinte")
        self.assertIn("Limite atteinte", texts(tab))
        tab.set_title("Autre titre")
        self.assertEqual(tab.state.title, "Autre titre")
        tab.hang_up()


if __name__ == "__main__":
    unittest.main()
