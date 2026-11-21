"""ccs tui : écrans projets, chat (autorisations au clavier), feuille de route, comptes.
Faux client, aucun écran réel."""

import unittest

import urwid

from ccs_app.tui.app import TuiApp

SIZE = (100, 30)

PROJECTS = {"entries": [{"cwd": None, "name": "Tous"}, {"cwd": "/home/a/projet", "name": "projet", "total": 2,
                                                       "open": 0, "exists": True}],
            "conversations": [{"session_id": "s1", "cwd": "/home/a/projet", "title": "Corriger le bug",
                               "updated_at": 0, "folder_exists": True, "path": "/p/s1.jsonl"}],
            "sessions": []}
ROADMAP = {"path": "/home/a/projet/ROADMAP.md", "title": "Projet", "phases": [
    {"title": "Phase 1", "tasks": [{"text": "écrire", "done": False, "line": 5, "depth": 0}]}]}


class FakeClient:
    def __init__(self):
        self.calls = []
        self.on_event = None
        self.on_state = None

    def call(self, method, callback=None, **params):
        self.calls.append((method, params))
        result = {"projects.list": PROJECTS, "chat.open": {"chat_id": "c1", "seq": 0},
                  "chat.attach": {"events": [], "seq": 0, "state": "idle"},
                  "roadmap.read": ROADMAP, "accounts.state": {
                      "active": "perso", "profiles": [{"name": "perso", "plan": "pro", "active": True}],
                      "state": {"accounts": [{"name": "perso", "active": True, "limits": [
                          {"kind": "session", "label": "Session (5 h)", "percent": 42.0}]}]}}}.get(method, {})
        if callback:
            callback(result, None)

    def methods(self):
        return [m for m, _ in self.calls]


def texts(widget):
    canvas = widget.render(SIZE, focus=True)
    return "\n".join(line.decode("utf-8", "replace") for line in canvas.text)


class TuiTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.app = TuiApp(self.client, "local")

    def test_projects_screen_lists(self):
        out = texts(self.app.root)
        self.assertIn("projet", out)
        self.assertIn("Corriger le bug", out)
        self.assertIn("projects.list", self.client.methods())

    def open_chat(self):
        self.app.open_chat("/home/a/projet", "s1", "Corriger le bug")
        self.assertEqual(self.app.current, "chat")
        return self.app.chat

    def test_chat_shows_text_and_tools(self):
        chat = self.open_chat()
        self.app.on_event("chat.event", {"chat_id": "c1", "seq": 1, "event": {"type": "AssistantText", "msg_id": "m", "text": "Bonjour Charles"}})
        self.app.on_event("chat.event", {"chat_id": "c1", "seq": 2, "event": {"type": "ToolUse", "tool_id": "t", "name": "Bash", "input": {"command": "ls -la"}}})
        out = texts(self.app.root)
        self.assertIn("Bonjour Charles", out)
        self.assertIn("ls -la", out)
        self.app.on_event("chat.event", {"chat_id": "autre", "seq": 3, "event": {"type": "AssistantText", "msg_id": "x", "text": "ailleurs"}})
        self.assertNotIn("ailleurs", texts(self.app.root))

    def test_chat_shows_usage_and_cache_expired(self):
        self.open_chat()
        usage = {"cache_read": 36_000, "cache_write": 2000, "input": 4, "output": 850, "cost_usd": 0.5}
        self.app.on_event("chat.event", {"chat_id": "c1", "seq": 1, "event": {"type": "TurnResult", "ok": True, "usage": usage}})
        self.app.on_event("chat.event", {"chat_id": "c1", "seq": 2, "event": {"type": "CacheExpired", "context": 90000,
                                                                              "ttl_s": 3600, "text": "Cache expiré : rien depuis 1 h."}})
        out = texts(self.app.root)
        self.assertIn("36 k lus · 2 k écrits · 850 produits · 0,50 $", out)
        self.assertIn("Cache expiré : rien depuis 1 h.", out)
        self.assertIn("/compact", out)

    def test_send_message(self):
        chat = self.open_chat()
        chat.edit.set_edit_text("fais ceci")
        chat.keypress(SIZE, "enter")
        self.assertIn(("chat.send", {"chat_id": "c1", "text": "fais ceci", "nonce": "tui"}), self.client.calls)
        self.assertEqual(chat.edit.edit_text, "")

    def test_chat_permission_keys(self):
        chat = self.open_chat()
        self.app.on_event("chat.event", {"chat_id": "c1", "seq": 1, "event": {
            "type": "PermissionRequest", "request_id": "r1", "tool_name": "Bash", "display_name": "Commande",
            "input": {"command": "rm x"}}})
        self.assertIn("1 Autoriser", texts(self.app.root))
        chat.keypress(SIZE, "1")
        self.assertIn(("chat.answer", {"chat_id": "c1", "request_id": "r1", "decision": "allow"}), self.client.calls)
        self.app.on_event("chat.event", {"chat_id": "c1", "seq": 2, "event": {"type": "PermissionSettled", "request_id": "r1"}})
        self.assertNotIn("1 Autoriser", texts(self.app.root))
        chat.keypress(SIZE, "3")                          # plus de demande : le chiffre va dans la saisie
        self.assertEqual(chat.edit.edit_text, "3")

    def test_interrupt_key(self):
        chat = self.open_chat()
        self.app.handle_key("ctrl c")
        self.assertIn("chat.interrupt", self.client.methods())

    def test_roadmap_space_toggles(self):
        self.open_chat()
        self.app.show("feuille")
        out = texts(self.app.root)
        self.assertIn("écrire", out)
        self.app.screens["feuille"].keypress(SIZE, " ")
        self.assertIn(("roadmap.toggle", {"path": ROADMAP["path"], "line": 5, "text": "écrire"}), self.client.calls)

    def test_accounts_screen(self):
        self.app.show("comptes")
        out = texts(self.app.root)
        self.assertIn("perso", out)
        self.assertIn("42 %", out)

    def test_tab_cycles_and_quit(self):
        self.app.handle_key("tab")
        self.assertEqual(self.app.current, "feuille")
        self.app.handle_key("esc")
        self.assertEqual(self.app.current, "projets")
        with self.assertRaises(urwid.ExitMainLoop):
            self.app.handle_key("q")


if __name__ == "__main__":
    unittest.main()
