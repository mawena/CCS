"""Liste des messages du chat : bulles, cartes d'outils, autorisations, tâches, historique."""

import unittest

from tests.helpers import gui_ready

GTK = gui_ready()

if GTK:
    from gi.repository import GLib, Gtk
    from ccs_app import chat_protocol as proto
    from ccs_app import preview
    from ccs_app.gui.chat_messages import MessageList, PermissionCard, TodosCard, edit_info


def pump(ms=50):
    ctx = GLib.MainContext.default()
    end = GLib.get_monotonic_time() + ms * 1000
    while GLib.get_monotonic_time() < end:
        while ctx.iteration(False):
            pass


def descendants(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from descendants(child)
        child = child.get_next_sibling()


def labels(widget):
    return [w.get_label() for w in descendants(widget) if isinstance(w, Gtk.Label)]


@unittest.skipUnless(GTK, "tests graphiques : CCS_GUI_TESTS=1 avec xvfb-run")
class MessageListTest(unittest.TestCase):
    def test_user_bubble_and_streamed_answer(self):
        ml = MessageList()
        ml.add_user("Bonjour", ())
        ml.start_assistant("m1")
        ml.append_delta("m1", "Salut ")
        ml.append_delta("m1", "**toi**")
        ml.finish_assistant("m1", "Salut **toi**")
        pump()
        self.assertEqual(ml.built_count, 2)
        self.assertIn("Bonjour", labels(ml.box))
        self.assertTrue(any("toi" in (t or "") for t in labels(ml.box)))

    def test_text_after_a_tool_goes_in_a_new_bubble(self):
        ml = MessageList()
        ml.finish_assistant("m1", "Avant")
        ml.add_tool(proto.ToolUse("t1", "Bash", {"command": "ls"}))
        ml.append_delta("m1", "Après")
        ml.finish_assistant("m1", "Après")
        self.assertEqual(ml.built_count, 3)

    def test_tool_card_result_and_diff_signal(self):
        seen = []
        ml = MessageList(on_diff=lambda *a: seen.append(a))
        card = ml.add_tool(proto.ToolUse("t1", "Edit", {
            "file_path": "/p/a.py", "old_string": "a\nb\n", "new_string": "a\nc\nd\n"}))
        self.assertTrue(card.running)
        self.assertEqual(card.edit[3:], (2, 1))                  # +2 −1
        self.assertIn("+2", labels(card))
        ml.set_tool_result(proto.ToolResult("t1", "ok", False))
        self.assertFalse(card.running)
        self.assertTrue(card.has_css_class("done"))
        card.main.emit("clicked")
        self.assertEqual(seen, [("/p/a.py", "a\nb\n", "a\nc\nd\n")])

    def test_failed_tool_is_marked_and_opened(self):
        ml = MessageList()
        card = ml.add_tool(proto.ToolUse("t1", "Bash", {"command": "false"}))
        ml.set_tool_result(proto.ToolResult("t1", "boom", True))
        self.assertTrue(card.has_css_class("error"))
        self.assertTrue(card.revealer.get_reveal_child())
        self.assertIn("boom", labels(card))

    def test_write_counts_lines_and_multiedit(self):
        self.assertEqual(edit_info("Write", {"file_path": "/x", "content": "1\n2\n3"})[3:], (3, 0))
        info = edit_info("MultiEdit", {"file_path": "/x", "edits": [
            {"old_string": "a", "new_string": "b"}, {"old_string": "c", "new_string": "c\nd"}]})
        self.assertEqual(info[3:], (2, 1))
        self.assertIsNone(edit_info("Read", {"file_path": "/x"}))

    def test_permission_card_answers(self):
        ml = MessageList()
        got = []
        req = proto.PermissionRequest("r1", "Bash", "Bash", {"command": "touch x"},
                                      [{"type": "addRules"}], "Crée un fichier", None)
        card = ml.add_permission(req, lambda *a: got.append(a))
        self.assertIn("touch x", labels(card))
        self.assertTrue(card.always.get_visible())
        card.reason.set_text("non merci")
        card.deny.emit("clicked")
        card.allow.emit("clicked")                              # déjà répondu : sans effet
        self.assertEqual(got, [("r1", "deny", "non merci")])
        self.assertTrue(card.answered)

    def test_permission_card_without_rules_has_no_always(self):
        card = PermissionCard(proto.PermissionRequest("r", "Bash", "Bash", {"command": "ls"}), lambda *a: None)
        self.assertFalse(card.always.get_visible())

    def test_todos_card_updates(self):
        ml = MessageList()
        ml.set_todos(proto.Todos((("Lire", "completed"), ("Écrire", "in_progress"), ("Tester", "pending"))))
        card = ml._todos
        self.assertIsInstance(card, TodosCard)
        self.assertIn("Tâches · 1/3", labels(card))
        ml.set_todos(proto.Todos((("Lire", "completed"), ("Écrire", "completed"), ("Tester", "completed"))))
        self.assertIs(ml._todos, card)
        self.assertIn("Tâches · 3/3", labels(card))
        self.assertEqual(ml.built_count, 1)

    def test_notice_with_action(self):
        ml = MessageList()
        done = []
        w = ml.add_notice("Erreur", "error", action=("Relancer", lambda: done.append(1)))
        self.assertTrue(w.has_css_class("error"))
        next(b for b in descendants(w) if isinstance(b, Gtk.Button)).emit("clicked")
        self.assertEqual(done, [1])

    def test_busy_row_follows_state(self):
        ml = MessageList()
        ml.set_busy(True, "Claude travaille…")
        self.assertTrue(ml.busy_row.get_visible())
        ml.add_user("x", ())
        self.assertIs(ml.box.get_last_child(), ml.busy_row)     # la roue reste en bas
        ml.set_busy(False)
        self.assertFalse(ml.busy_row.get_visible())

    def test_thousand_messages_build_lazily(self):
        history = []
        for i in range(500):
            history.append(preview.Message(preview.USER, f"question {i}"))
            history.append(preview.Message(preview.ASSISTANT, f"réponse {i}"))
        ml = MessageList()
        ml.load_history(history)
        self.assertEqual(len(history), 1000)
        self.assertLess(ml.built_count, 200)
        self.assertLess(ml.row_count(), 200)
        ml._load_more()                                         # défilement vers le haut
        self.assertEqual(ml.built_count, 100)
        self.assertIs(ml.box.get_last_child(), ml.busy_row)

    def test_history_with_tools_and_new_messages_after(self):
        ml = MessageList()
        ml.load_history([
            preview.Message(preview.USER, "fais ça"),
            preview.Message(preview.TOOL, "", tool=preview.ToolCall("Read", "a.py", "t1", "contenu", False)),
            preview.Message(preview.ASSISTANT, "fait"),
        ])
        self.assertEqual(ml.built_count, 3)
        ml.add_user("merci", ())
        pump()
        texts = labels(ml.box)
        self.assertLess(texts.index("fait"), texts.index("merci"))


if __name__ == "__main__":
    unittest.main()
