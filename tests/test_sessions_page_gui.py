"""Onglet Sessions : raccordement de la mémoire, du contexte et de « Fermer » ; conversations
archivées dont le dossier a disparu (filtre par projet, suggestions). Sans affichage réel."""

import unittest
from types import SimpleNamespace
from unittest import mock

from ccs_app import conversations, session_hub as hub

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gtk  # noqa: F401
    GTK = True
except (ImportError, ValueError):
    GTK = False


def archived(sid, cwd, exists=False, updated=1_800_000_000.0):
    return conversations.Conversation(
        session_id=sid, path=f"/archive/{sid}.jsonl", cwd=cwd, title=f"t-{sid}", first_prompt="a",
        last_prompt="b", prompts=1, started_at=None, updated_at=updated, origin="terminal",
        git_branch="", size=10, folder_exists=exists, archived=True)


class ArchivedProjectsTest(unittest.TestCase):
    def test_project_filter_keeps_archived_conversations_of_a_vanished_folder(self):
        convs = [archived("a", "/disparu/Projet"), archived("b", "/disparu/Projet"),
                 archived("c", "/ici/Autre", exists=True)]
        view = hub.build(convs, [], selected="/disparu/Projet")
        self.assertEqual(view.selected.cwd, "/disparu/Projet")
        self.assertFalse(view.selected.exists)
        self.assertEqual(sorted(c.session_id for c in view.conversations), ["a", "b"])

    def test_conversation_without_folder_does_not_break_the_hub(self):
        view = hub.build([archived("x", "")], [], selected=hub.ALL)
        self.assertEqual(view.total, 1)

    def test_suggestion_finds_the_new_folder_of_a_moved_project(self):
        convs = [archived("a", "/disparu/Projet"), archived("b", "/ici/Projet", exists=True)]
        suggestions = conversations.suggest_folders(convs)
        self.assertEqual(suggestions, {"a": "/ici/Projet"})
        view = hub.build(convs, [], selected=hub.ALL, suggestions=suggestions)
        moved = {e.cwd: e.moved_to for e in view.entries}
        self.assertEqual(moved["/disparu/Projet"], "/ici/Projet")

    def test_no_suggestion_for_an_archived_conversation_without_candidate(self):
        self.assertEqual(conversations.suggest_folders([archived("a", "/disparu/Seul")]), {})
        self.assertEqual(conversations.suggest_folders([archived("z", "")]), {})


@unittest.skipUnless(GTK, "GTK 4 et libadwaita absents")
class CloseSessionTest(unittest.TestCase):
    def setUp(self):
        from ccs_app.gui import sessions_page
        self.mod = sessions_page

    def fake(self):
        return SimpleNamespace(window=mock.Mock(), load_sessions=mock.Mock())

    def test_close_terminates_the_process_then_reloads(self):
        page, s = self.fake(), SimpleNamespace(pid=4242, proc_start="12345")
        with mock.patch.object(self.mod.sessions, "terminate", return_value=True) as term, \
                mock.patch.object(self.mod.GLib, "timeout_add",
                                  side_effect=lambda ms, fn: (fn(), 0)[1]) as later:
            self.mod.SessionsPage.close_session(page, s)
        term.assert_called_once_with(4242, "12345")
        page.window.toast.assert_called_once_with("Session fermée")
        self.assertEqual(later.call_args.args[0], 800)
        page.load_sessions.assert_called_once()

    def test_already_closed_session_is_reported(self):
        page = self.fake()
        with mock.patch.object(self.mod.sessions, "terminate", return_value=False), \
                mock.patch.object(self.mod.GLib, "timeout_add"):
            self.mod.SessionsPage.close_session(page, SimpleNamespace(pid=1, proc_start=None))
        page.window.toast.assert_called_once_with("Session déjà fermée")

    def read(self, settings, contexts):
        captured = {}
        page = SimpleNamespace(loading_sessions=False, sessions_again=False, sessions_loaded=None)
        found = [SimpleNamespace(pid=7, session_id="sid", cwd="/x")]
        with mock.patch.object(self.mod, "in_thread", side_effect=lambda work, done: captured.update(work=work)), \
                mock.patch.object(self.mod.sessions, "list_sessions", return_value=found), \
                mock.patch.object(self.mod.sessions, "conversation_usage", return_value=None), \
                mock.patch.object(self.mod.sessions, "conversation_title", return_value="t"), \
                mock.patch.object(self.mod.sessions, "transcript_path", return_value="/j/sid.jsonl"), \
                mock.patch.object(self.mod, "stamp", return_value=None), \
                mock.patch.object(self.mod, "load_associations", return_value=[]), \
                mock.patch.object(self.mod, "load_settings", return_value=settings), \
                mock.patch.object(self.mod.session_memory, "snapshot", return_value={7: "mem"}), \
                mock.patch.object(self.mod.context_alert, "contexts_for", return_value=contexts) as ctx:
            self.mod.SessionsPage.load_sessions(page)
            return captured["work"](), ctx

    def test_reading_computes_memory_and_contexts_in_the_worker(self):
        result, _ctx = self.read({"context_alert": {"enabled": True, "threshold_tokens": 99000}}, {7: "ctx"})
        self.assertEqual(result[5], ({7: "mem"}, {7: "ctx"}, 99000))

    def test_disabled_alert_gives_no_contexts_and_no_threshold(self):
        result, ctx = self.read({"context_alert": {"enabled": False}}, {7: "ctx"})
        ctx.assert_not_called()
        self.assertEqual(result[5], ({7: "mem"}, {}, None))


if __name__ == "__main__":
    unittest.main()
