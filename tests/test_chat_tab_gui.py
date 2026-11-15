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



def labels_in(widget):
    """Texte de tous les Gtk.Label sous `widget` (même dans une page de pile cachée)."""
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        if isinstance(w, Gtk.Label):
            out.append(w.get_text())
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return " ".join(out)


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

    def test_remote_tab_title_has_server(self):
        made = []

        class FakeRemote:
            def __init__(self, cwd, session_id, options, on_event):
                made.append(cwd)
                self.cwd, self.session_id, self.state, self.pid, self.started_at = cwd, session_id, "stopped", None, None
                self.effort = None

            def __getattr__(self, name):
                return lambda *a, **k: None
        launch = terminal.claude_launch("/srv/projet-distant", None, "Projet")
        tab = ChatTab(FakeOwner(), launch, engine_factory=FakeRemote, remote="vps")
        self.assertEqual(made, ["/srv/projet-distant"])
        self.assertEqual(tab.display_title(), "Projet · vps")
        tab.remote_state("offline")
        self.assertTrue(tab.offline_banner.get_revealed())
        tab.remote_state("reconnected")
        self.assertFalse(tab.offline_banner.get_revealed())
        tab._closed = True

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

    def test_message_while_busy_is_sent_now(self):
        tab, owner = self.make("permissions-allow-toujours.jsonl")
        self.say(tab, "Lance la commande `touch essai1.txt` puis dis juste OK.")
        self.assertTrue(pump_until(lambda: tab.engine.state == "permission"))
        self.say(tab, "et ensuite ceci")
        self.assertEqual(tab.state.queue, [])                      # plus de mise en file
        self.assertIn("et ensuite ceci", texts(tab))               # la bulle part tout de suite
        self.assertTrue(any("pendant que Claude travaille" in t for t in texts(tab)))
        self.assertEqual(tab.composer.text, "")

    def test_image_while_busy_is_sent_now(self):
        tab, _owner = self.make("permissions-allow-toujours.jsonl")
        self.say(tab, "Lance la commande `touch essai1.txt` puis dis juste OK.")
        self.assertTrue(pump_until(lambda: tab.engine.state == "permission"))
        png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00"
               b"\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7"
               b"5\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82")
        tab._on_send(tab.composer, "regarde", [("image/png", png)])
        self.assertIn("regarde", texts(tab))
        self.assertFalse(any("ne peuvent pas attendre" in t for t in texts(tab)))

    def test_send_now_during_a_turn(self):
        tab, _owner = self.make("permissions-allow-toujours.jsonl")
        self.say(tab, "Lance la commande `touch essai1.txt` puis dis juste OK.")
        self.assertTrue(pump_until(lambda: tab.engine.state == "permission"))
        tab.state.queue[:] = ["déjà en file"]
        tab.send_message_now(0)
        self.assertEqual(tab.state.queue, [])
        self.assertIn("déjà en file", texts(tab))

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

    def test_unknown_question_is_shown(self):
        tab, _owner = self.make()
        tab._dispatch(chat_engine.UnhandledRequest("question_mystere", "question : Activer ?"))
        self.assertTrue(any("question_mystere" in t and "Activer" in t for t in texts(tab)))

    def test_subagent_permission_says_so(self):
        tab, _owner = self.make()
        tab._dispatch(proto.PermissionRequest("r1", "Bash", "Bash", {"command": "ls"}, agent_id="agent-1"))
        self.assertTrue(any("sous-agent" in t for t in texts(tab)))

    def test_subagent_has_its_own_view_and_pill(self):
        tab, _owner = self.make()
        self.assertFalse(tab.agent_bar.get_visible())
        tab._dispatch(proto.ToolUse("toolu_A", "Task", {"description": "Explorer le code", "prompt": "…"}, None))
        self.assertIn("toolu_A", tab.agents)
        self.assertTrue(tab.agent_bar.get_visible())
        self.assertIn("Explorer le code", labels_in(tab.agent_bar))
        tab._dispatch(proto.ToolUse("toolu_x", "Bash", {"command": "ls"}, "toolu_A"))
        tab._dispatch(proto.AssistantText("m-sub", "trouvé trois fichiers", "toolu_A"))
        self.assertNotIn("trouvé trois fichiers", labels_in(tab.messages))   # pas dans le fil principal
        agent = tab.agents["toolu_A"]
        tab.show_agent("toolu_A")
        self.assertIs(tab.view_stack.get_visible_child(), agent.view)
        self.assertTrue(pump_until(lambda: "trouvé trois fichiers" in labels_in(agent.messages)))
        self.assertFalse(agent.done)
        tab._dispatch(proto.ToolResult("toolu_A", "fini", False, None))
        self.assertTrue(agent.done)
        tab.show_agent(None)                                       # « ← Principale »
        self.assertIs(tab.view_stack.get_visible_child(), tab.messages_overlay)
        self.say(tab, "message")                                   # la saisie reste pour la principale
        self.assertIn("message", labels_in(tab.messages))

    def test_finished_subagent_leaves_the_bar(self):
        """Comme VS Code : un sous-agent fini quitte la barre ; sa carte le rouvre."""
        tab, _owner = self.make()
        tab._dispatch(proto.ToolUse("toolu_A", "Task", {"description": "Explorer", "prompt": "…"}, None))
        tab._dispatch(proto.ToolUse("toolu_B", "Task", {"description": "Relire", "prompt": "…"}, None))
        a, b = tab.agents["toolu_A"], tab.agents["toolu_B"]
        tab._dispatch(proto.ToolResult("toolu_A", "fini", False, None))
        self.assertFalse(a.pill.get_visible())                     # fini : plus dans la barre
        self.assertTrue(b.pill.get_visible())
        self.assertTrue(tab.agent_bar.get_visible())
        tab._dispatch(proto.ToolResult("toolu_B", "fini", False, None))
        self.assertFalse(tab.agent_bar.get_visible())              # plus personne : barre cachée
        tab.show_agent("toolu_A")                                  # « Voir le sous-agent » sur sa carte
        self.assertTrue(a.pill.get_visible())
        self.assertTrue(tab.agent_bar.get_visible())
        self.assertIs(tab.view_stack.get_visible_child(), a.view)
        tab.show_agent(None)
        self.assertFalse(tab.agent_bar.get_visible())

    def test_background_subagent_ends_with_its_notice(self):
        tab, _owner = self.make()
        tab._dispatch(proto.ToolUse("toolu_F", "Agent", {"description": "De fond", "prompt": "…",
                                                         "run_in_background": True}, None))
        agent = tab.agents["toolu_F"]
        tab._dispatch(proto.ToolResult("toolu_F", "Async agent launched", False, None))
        self.assertFalse(agent.done)                               # lancé, pas fini
        self.assertTrue(agent.pill.get_visible())
        line = json.dumps({"type": "user", "message": {"role": "user", "content":
                           "<task-notification>\n<task-id>abc</task-id>\n<tool-use-id>toolu_F</tool-use-id>\n"
                           "<status>completed</status>\n<summary>Agent fini</summary>\n</task-notification>"}})
        for ev in proto.parse_line(line):
            tab._dispatch(ev)
        self.assertTrue(agent.done)
        self.assertFalse(tab.agent_bar.get_visible())

    def test_todos_pinned_above_the_composer(self):
        """Comme VS Code : la liste de tâches reste visible au-dessus de la saisie."""
        tab, _owner = self.make(spawn=False)
        self.assertFalse(tab.todos_bar.get_visible())
        tab._dispatch(proto.Todos((("Lire", "completed"), ("Écrire les tests", "in_progress"),
                                   ("Publier", "pending"))))
        self.assertTrue(tab.todos_bar.get_visible())
        self.assertEqual(tab.todos_bar.summary.get_label(), "Tâches 1/3 · Écrire les tests")
        self.assertIsNone(tab.messages._todos)                   # pas dans le fil
        tab._dispatch(proto.Todos((("Lire", "completed"), ("Écrire les tests", "completed"),
                                   ("Publier", "completed"))))
        self.assertIn("terminées", tab.todos_bar.summary.get_label())
        self.assertTrue(tab.todos_bar.get_visible())
        tab.todos_bar.new_turn()                                 # message suivant : liste finie effacée
        self.assertFalse(tab.todos_bar.get_visible())

    def test_shift_tab_cycles_rights(self):
        tab, _owner = self.make(spawn=False)
        tab.bar._change(rights="manual")
        seen = []
        for _ in range(3):
            tab.composer.emit("cycle-rights")
            seen.append(tab.bar.options.rights)
        self.assertEqual(seen, ["acceptEdits", "plan", "manual"])

    def test_permission_answered_with_number_keys(self):
        tab, _owner = self.make("permissions-allow-toujours.jsonl")
        self.say(tab, "Lance la commande `touch essai1.txt` puis dis juste OK.")
        self.assertTrue(pump_until(lambda: tab.messages._perms))
        self.assertIsNotNone(tab.composer.permission_keys)
        self.assertIn("1 Autoriser", tab.composer.placeholder.get_label())
        card = tab.messages.pending_permission()
        self.assertFalse(tab._permission_key("9"))               # touche sans rôle : rien
        self.assertTrue(tab._permission_key("1"))
        self.assertTrue(card.answered)
        self.assertTrue(pump_until(lambda: tab.composer.permission_keys is None
                                   or tab.messages.pending_permission() is not None))

    def test_question_card_sends_answers(self):
        """Outil AskUserQuestion : une vraie carte de questions, et les réponses rendues à Claude
        (avant : « The user did not answer the questions »)."""
        tab, _owner = self.make(spawn=False)
        sent = []
        tab.engine.answer_questions = lambda rid, answers: sent.append((rid, answers)) or True
        qs = {"questions": [
            {"question": "Quel nom ?", "header": "Nom", "multiSelect": False,
             "options": [{"label": "Diapason", "description": "se mettre au diapason"}, {"label": "Timbre"}]},
            {"question": "Quelles sorties ?", "header": "Sorties", "multiSelect": True,
             "options": [{"label": "Casque"}, {"label": "Bluetooth"}, {"label": "HDMI"}]}]}
        tab._dispatch(proto.PermissionRequest("q1", "AskUserQuestion", "AskUserQuestion", qs))
        from ccs_app.gui.chat_messages import QuestionCard
        card = tab.messages.pending_permission()
        self.assertIsInstance(card, QuestionCard)
        self.assertIn("1. Diapason", texts(tab))
        self.assertIn("question", tab.composer.placeholder.get_label())
        self.assertFalse(card.send.get_sensitive())
        self.assertTrue(tab._permission_key("1"))                  # 1 : Diapason
        card.choices[1][1][0][0].set_active(True)                  # Casque
        card.choices[1][3].set_text("Dock Dell")                   # Autre : texte libre
        self.assertEqual(card.answers(), {"Quel nom ?": "Diapason",
                                          "Quelles sorties ?": ["Casque", "Dock Dell"]})
        card.send.emit("clicked")
        self.assertEqual(sent, [("q1", {"Quel nom ?": "Diapason", "Quelles sorties ?": ["Casque", "Dock Dell"]})])
        self.assertTrue(card.answered)

    def test_answers_reach_the_cli_in_updated_input(self):
        line = proto.answer_questions("q1", {"questions": [{"question": "Q ?"}]}, {"Q ?": "Oui"})
        data = json.loads(line)
        resp = data["response"]["response"]
        self.assertEqual(resp["behavior"], "allow")
        self.assertEqual(resp["updatedInput"]["answers"], {"Q ?": "Oui"})
        self.assertEqual(resp["updatedInput"]["questions"], [{"question": "Q ?"}])

    def test_journal_notices_ignore_quoted_tags(self):
        """Avis de fin lus dans le journal : entrée de file ou pièce jointe ; une balise citée
        dans un message de Claude ne compte pas."""
        notice = "<task-notification>\n<tool-use-id>toolu_BON</tool-use-id>\n<status>completed</status>\n</task-notification>"
        lines = [json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "input":
                    {"content": "<task-notification><tool-use-id>toolu_FAUX</tool-use-id>"}}]}}),
                 json.dumps({"type": "queue-operation", "operation": "enqueue", "content": notice})]
        found = proto.journal_notices(("\n".join(lines)).encode())
        self.assertEqual([n.tool_id for n in found], ["toolu_BON"])

    def test_composer_has_no_hint_line(self):
        # Pas de ligne d'indications sous la saisie : les boutons sont à droite du texte, les
        # indications dans le texte gris de la zone vide et dans l'info-bulle d'Envoyer.
        tab, _owner = self.make()
        c = tab.composer
        self.assertFalse(hasattr(c, "hint"))
        self.assertIs(c.send_button.get_parent(), c.stop_button.get_parent())
        self.assertIs(c.send_button.get_parent().get_parent(), c.input_row)
        self.assertIn("@", c.placeholder.get_label())
        c.set_busy(True)
        self.assertIn("Échap", c.placeholder.get_label())
        self.assertIn("Maj+Entrée", c.send_button.get_tooltip_text())

    def test_attach_files_button_and_chips(self):
        from ccs_app.gui.chat_composer import Composer
        doc = Path(self.tmp) / "rapport.pdf"
        doc.write_bytes(b"%PDF-1.4 faux")
        note = self.cwd / "notes.txt"
        note.write_text("x")
        c = Composer(base_dir=str(self.cwd))
        sent = []
        c.connect("send", lambda _c, text, images: sent.append((text, images)))
        self.assertIn("Joindre", c.attach_button.get_tooltip_text())
        c.add_path(str(doc))
        c.add_path(str(note))
        self.assertEqual(c.files, [str(doc), str(note)])
        self.assertTrue(c.thumbs.get_visible())
        self.assertEqual(c.text, "")                       # pas de texte inséré : une étiquette
        c._remove_file(0)
        self.assertEqual(c.files, [str(note)])
        c.add_path(str(doc))
        self.assertTrue(c.submit())                        # sans texte, les fichiers suffisent
        text = sent[0][0]
        self.assertIn(f"@{doc}", text)
        self.assertIn("@notes.txt", text)                  # relatif au projet
        self.assertEqual(c.files, [])

    def test_turn_footer_after_an_answer(self):
        tab, _owner = self.make("permissions-allow-toujours.jsonl")
        self.say(tab, "Lance la commande `touch essai1.txt` puis dis juste OK.")
        self.assertTrue(pump_until(lambda: tab.messages._perms))
        next(iter(tab.messages._perms.values())).allow.emit("clicked")
        self.assertTrue(pump_until(lambda: tab.messages._last_footer is not None))
        self.assertIn("Terminé en", tab.messages._last_footer.get_label())

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

    def test_show_older_rereads_the_journal(self):
        # après un élagage (longue session), « Afficher » relit le fil depuis le journal
        journal = Path(self.tmp) / "conv.jsonl"
        lines = [{"type": "user", "message": {"role": "user", "content": "question retirée"}},
                 {"type": "assistant", "message": {"id": "m1", "role": "assistant",
                                                   "content": [{"type": "text", "text": "réponse retirée"}]}}]
        journal.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
        tab, _owner = self.make(session_id="sess-9", history_path=str(journal), spawn=False)
        self.assertTrue(pump_until(lambda: "réponse retirée" in texts(tab)))
        tab.messages.reset()
        tab.messages.add_user("récente", ())
        tab.engine.state = "busy"
        tab._show_older()                                         # pendant un tour : rien
        self.assertIn("récente", texts(tab))
        tab.engine.state = "idle"
        tab.messages.older_button.emit("clicked")
        self.assertTrue(pump_until(lambda: "réponse retirée" in texts(tab)))
        self.assertNotIn("récente", texts(tab))                   # pas dans ce faux journal

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

    ROADMAP = "# P\n\n## Phase 1 — A\n- [ ] ma tâche\n- [ ] autre\n"

    def roadmap_file(self, checked=False):
        path = self.cwd / "ROADMAP.md"
        path.write_text(self.ROADMAP.replace("- [ ] ma", "- [x] ma") if checked else self.ROADMAP)
        return path

    def let_claude_finish(self, tab):
        """Le scénario demande une autorisation : on l'accorde, le tour se termine."""
        self.assertTrue(pump_until(lambda: tab.messages._perms))
        next(iter(tab.messages._perms.values())).allow.emit("clicked")
        self.assertTrue(pump_until(lambda: tab._turn_done and tab.engine.state == "idle"))

    def test_do_task_banner_when_unchecked(self):
        tab, _owner = self.make("permissions-allow-toujours.jsonl")
        path = self.roadmap_file()
        self.assertTrue(tab.do_roadmap_task(str(path), "ma tâche", "Phase 1 — A"))
        self.assertTrue(any("Fais la tâche « ma tâche » (phase « Phase 1 — A »)" in t for t in texts(tab)))
        self.let_claude_finish(tab)
        self.assertTrue(pump_until(lambda: tab.task_banner.get_visible()))
        tab.task_check.emit("clicked")
        self.assertTrue(pump_until(lambda: "- [x] ma tâche" in path.read_text()))
        self.assertIn("- [ ] autre", path.read_text())          # la bonne case seulement
        self.assertFalse(tab.task_banner.get_visible())

    def test_do_task_not_yet_hides_banner(self):
        tab, _owner = self.make("permissions-allow-toujours.jsonl")
        path = self.roadmap_file()
        tab.do_roadmap_task(str(path), "ma tâche", "Phase 1 — A")
        self.let_claude_finish(tab)
        self.assertTrue(pump_until(lambda: tab.task_banner.get_visible()))
        tab.task_later.emit("clicked")
        self.assertFalse(tab.task_banner.get_visible())
        self.assertIn("- [ ] ma tâche", path.read_text())

    def test_no_banner_when_claude_checked(self):
        tab, _owner = self.make("permissions-allow-toujours.jsonl")
        path = self.roadmap_file()
        self.assertTrue(tab.do_roadmap_task(str(path), "ma tâche", "Phase 1 — A"))
        self.roadmap_file(checked=True)                          # Claude a coché pendant le tour
        self.let_claude_finish(tab)
        pump_until(lambda: False, 0.6)
        self.assertFalse(tab.task_banner.get_visible())

    def test_do_task_unknown_task_refused(self):
        tab, _owner = self.make("permissions-allow-toujours.jsonl")
        path = self.roadmap_file()
        self.assertFalse(tab.do_roadmap_task(str(path), "inconnue", "Phase 1 — A"))

    def test_rewind_from_bubble_menu(self):
        from unittest import mock
        from ccs_app import sessions
        from ccs_app.gui.chat_messages import open_rewind_menu
        tab, _owner = self.make(session_id="sess-rw", spawn=False)
        win = Gtk.Window()
        win.set_child(tab)
        win.present()
        self.addCleanup(win.destroy)
        target = self.cwd / "a.txt"
        target.write_text("après\n")
        copies = Path(self.home) / ".claude" / "file-history" / "sess-rw"
        copies.mkdir(parents=True)
        (copies / "h@v1").write_bytes(b"avant\n")
        journal = sessions.transcript_path(str(self.cwd), "sess-rw")
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("\n".join([
            json.dumps({"type": "user", "uuid": "u1", "message": {"role": "user", "content": "premier"}}),
            json.dumps({"type": "user", "uuid": "u2", "message": {"role": "user", "content": "second"}}),
            json.dumps({"type": "file-history-snapshot", "messageId": "u2", "isSnapshotUpdate": False,
                        "snapshot": {"messageId": "u2", "timestamp": "t", "trackedFileBackups": {
                            str(target): {"backupFileName": "h@v1", "version": 1, "backupTime": "t"}}}}),
        ]) + "\n")
        tab.messages.add_user("premier")
        row = tab.messages.add_user("second")
        self.assertEqual(tab.messages.user_index_from_end(row), 0)
        asked = []
        with mock.patch.object(tab, "_confirm_rewind", lambda plan, yes: asked.append((plan, yes))):
            open_rewind_menu(row, tab.rewind_from_bubble)
            row.rewind_button.emit("clicked")
            self.assertTrue(pump_until(lambda: asked))
        plan, yes = asked[0]
        self.assertEqual([(s.path, s.content) for s in plan], [(str(target), b"avant\n")])
        self.assertEqual(target.read_text(), "après\n")        # rien avant l'accord
        yes()
        self.assertTrue(pump_until(lambda: target.read_text() == "avant\n"))

    def test_ctrl_f_opens_search_bar_and_finds(self):
        tab, _owner = self.make(spawn=False)
        tab.messages.add_user("Salut Éléphant", ())
        tab.messages.add_user("un autre éléphant", ())
        self.assertFalse(tab.search_bar.get_search_mode())
        tab.open_find()
        self.assertTrue(tab.search_bar.get_search_mode())
        tab.search_entry.set_text("elephant")
        self.assertTrue(pump_until(lambda: tab.messages.find_count() == 2))
        self.assertEqual(tab.find_label.get_label(), "1 / 2")
        tab.find_step(1)
        self.assertEqual(tab.find_label.get_label(), "2 / 2")
        tab.search_bar.set_search_mode(False)
        self.assertEqual(tab.messages.find_count(), 0)

    def test_find_after_trim_reloads(self):
        journal = Path(self.tmp) / "conv.jsonl"
        lines = [{"type": "user", "message": {"role": "user", "content": "question retirée"}},
                 {"type": "assistant", "message": {"id": "m1", "role": "assistant",
                                                   "content": [{"type": "text", "text": "réponse retirée"}]}}]
        journal.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
        tab, _owner = self.make(session_id="sess-9", history_path=str(journal), spawn=False)
        self.assertTrue(pump_until(lambda: "réponse retirée" in texts(tab)))
        tab.messages.reset()
        tab.messages.add_user("récente", ())
        tab.messages._dropped = 4                                 # comme après un élagage
        tab.open_find()
        tab.search_entry.set_text("REPONSE retiree")
        self.assertTrue(pump_until(lambda: tab.messages.find_count() == 1))
        self.assertEqual(tab.find_label.get_label(), "1 / 1")

    def test_find_while_busy_keeps_live_thread(self):
        tab, _owner = self.make(spawn=False)
        tab.messages.add_user("récente", ())
        tab.messages._dropped = 4
        tab.engine.state = "busy"
        tab.open_find()
        tab.search_entry.set_text("recente")
        self.assertTrue(pump_until(lambda: tab.messages.find_count() == 1))
        self.assertIn("Disponible quand Claude aura fini", tab.find_label.get_label())

    def test_saved_messages_load_and_persist(self):
        from ccs_app import saved_messages
        saved_messages.save("global", [saved_messages.Saved("merci", "Merci !", "global")])
        tab, _owner = self.make(spawn=False)
        self.assertTrue(pump_until(lambda: [s.name for s in tab.composer.saved] == ["merci"]))
        tab.composer.add_saved("ici", "Texte du projet", "projet")
        self.assertTrue(pump_until(lambda: (self.cwd / ".ccs" / "messages.json").exists()))
        got = {s.name: s.scope for s in saved_messages.load(str(self.cwd))}
        self.assertEqual(got, {"merci": "global", "ici": "projet"})


if __name__ == "__main__":
    unittest.main()
