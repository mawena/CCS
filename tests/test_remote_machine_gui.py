"""Page Sessions, vue d'un serveur : chats en cours à rejoindre, projets, conversations,
gestion (retirer, supprimer, corbeille). Faux serveur, sans affichage réel."""

import unittest
from types import SimpleNamespace
from unittest import mock

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk  # noqa: F401
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False

PROJECTS = {"entries": [{"cwd": "/home/c/Work/A", "name": "A", "exists": True}],
            "conversations": [{"session_id": "s1", "cwd": "/home/c/Work/A", "title": "Tâche une",
                               "path": "/home/c/.claude/projects/A/s1.jsonl", "folder_exists": True}]}
CHATS = {"chats": [{"chat_id": "c7", "cwd": "/home/c/Work/A", "state": "busy", "session_id": "s1",
                    "path": "/home/c/.claude/projects/A/s1.jsonl", "history_before": True},
                   {"chat_id": "c8", "cwd": "/home/c/Work/A", "state": "stopped", "session_id": None}]}


class FakeConn:
    def __init__(self):
        self.listeners, self.state, self.calls = set(), "online", []

    def call(self, method, callback=None, **params):
        self.calls.append((method, params))
        if callback is not None:
            callback({"projects.list": PROJECTS, "chat.list": CHATS}.get(method, {}), None)


def rows(widget):
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        if isinstance(w, Adw.ActionRow):
            out.append(w)
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return out


def buttons(row):
    out, stack = [], [row]
    while stack:
        w = stack.pop()
        if isinstance(w, Gtk.Button) and w.get_label():
            out.append(w)
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return {b.get_label(): b for b in out}


@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class RemoteMachineViewTest(unittest.TestCase):
    def make(self):
        from ccs_app.gui import remote_machine
        self.conn = FakeConn()
        self.window = mock.Mock()
        self.window.terminals.tabs.return_value = []
        server = SimpleNamespace(name="vps", url="https://ccs.example", user="c", token="t")
        with mock.patch.object(remote_machine.remote_engine, "connection", return_value=self.conn):
            view = remote_machine.RemoteMachineView(self.window, server, lambda fn, *a: fn(*a))
        view.refresh()
        return view

    def test_running_chat_listed_and_joined_live(self):
        view = self.make()
        titles = [r.get_title() for r in rows(view)]
        self.assertIn("Tâche une", titles)              # chat en cours, titre de sa conversation
        live = next(r for r in rows(view) if "Claude travaille" in (r.get_subtitle() or ""))
        buttons(live)["Rejoindre"].emit("clicked")
        args, kwargs = self.window.terminals.open_remote_chat.call_args
        self.assertEqual(kwargs["chat_id"], "c7")
        self.assertEqual(args[1:3], ("/home/c/Work/A", "s1"))

    def test_stopped_chat_not_listed(self):
        view = self.make()
        self.assertFalse(any("arrêté" in (r.get_subtitle() or "") for r in rows(view)))

    def test_already_open_tab_is_presented(self):
        view = self.make()
        tab = SimpleNamespace(remote="vps", engine=SimpleNamespace(chat_id="c7"))
        self.window.terminals.tabs.return_value = [tab]
        view.join(CHATS["chats"][0], "Tâche une")
        self.window.terminals.present.assert_called_once_with(tab)
        self.window.terminals.open_remote_chat.assert_not_called()

    def test_projects_and_conversations_have_actions(self):
        view = self.make()
        proj = next(r for r in rows(view) if r.get_title() == "A")
        self.assertIn("Chat", buttons(proj))
        self.assertIn("Terminal", buttons(proj))
        conv = next(r for r in rows(view) if r.get_title() == "Tâche une" and r.get_subtitle() == "A")
        self.assertIn("Reprendre", buttons(conv))

    def test_trash_goes_through_the_server(self):
        from ccs_app.gui import manage_dialogs
        view = self.make()
        with mock.patch.object(manage_dialogs.Adw.AlertDialog, "present"):
            d = manage_dialogs.trash_conversation(view, view.ops, view.notify,
                                                  {**PROJECTS["conversations"][0]}, view.refresh)
            d.emit("response", "trash")
        method, params = self.conn.calls[-1] if self.conn.calls[-1][0] == "conversation.trash" else \
            next(c for c in self.conn.calls if c[0] == "conversation.trash")
        self.assertEqual(params["session_id"], "s1")

    def test_unreachable_server_is_said(self):
        view = self.make()
        view.projects_loaded(None, SimpleNamespace(message="Délai <dépassé> & coupure"))
        self.assertTrue(any(r for r in view.groups if "injoignable" in (r.get_title() or "")))


if __name__ == "__main__":
    unittest.main()
