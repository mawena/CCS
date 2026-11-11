"""Vue des tâches (onglet Planning) : widgets créés sans être affichés (affichage requis,
sinon tests sautés). HOME isolé."""

import json
import unittest
from datetime import datetime, timezone

from ccs_app import tasks
from tests.helpers import HomeTestCase

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gtk
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False

NOW = datetime(2026, 11, 12, 14, 0, tzinfo=timezone.utc)


class FakeWindow:
    def __init__(self):
        self.toasts = []

    def toast(self, text):
        self.toasts.append(text)


def labels(widget):
    out, child = [], widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Label):
            out.append(child.get_label())
        out += labels(child)
        child = child.get_next_sibling()
    return out


def rows(view):
    out, row = [], view.list.get_first_child()
    while row is not None:
        out.append(row)
        row = row.get_next_sibling()
    return out


@unittest.skipUnless(GTK, "affichage graphique requis")
class TasksViewTest(HomeTestCase):
    def view(self, **kw):
        from ccs_app.gui.tasks_view import TasksView
        self.window = FakeWindow()
        return TasksView(window=self.window, **kw)

    def test_empty_list_shows_a_hint(self):
        v = self.view()
        self.assertEqual(rows(v), [])
        self.assertTrue(v.empty.get_visible())
        self.assertFalse(v.detail.get_visible())

    def test_lists_tasks_newest_first_with_state(self):
        a = tasks.add("Première tâche", cwd=str(self.home))
        b = tasks.add("Seconde tâche", cwd=str(self.home))
        tasks.update(a.id, state="done", duration=61, cost=0.5)
        v = self.view()
        self.assertEqual([r.get_name() for r in rows(v)], [f"task-{b.id}", f"task-{a.id}"])
        self.assertFalse(v.empty.get_visible())
        first, second = rows(v)
        self.assertIn("En attente", first.get_subtitle())
        self.assertIn("Finie", second.get_subtitle())
        self.assertIn("1 min 01 s", second.get_subtitle())

    def test_refresh_picks_up_changes_from_the_service(self):
        v = self.view()
        tasks.add("Nouvelle", cwd=str(self.home))
        v.refresh()
        self.assertEqual(len(rows(v)), 1)

    def test_show_task_reads_the_journal_incrementally(self):
        t = tasks.add("Corrige", cwd=str(self.home))
        tasks.update(t.id, state="running", pid=4242)
        tasks.journal_dir().mkdir(parents=True)
        p = tasks.journal_path(t.id)
        p.write_text(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Première phrase"}]}}) + "\n")
        v = self.view()
        self.assertTrue(v.show_task(t.id))
        self.assertTrue(v.detail.get_visible())

        def text():
            b = v.log.get_buffer()
            return b.get_text(b.get_start_iter(), b.get_end_iter(), False)
        self.assertIn("Première phrase", text())
        self.assertTrue(v.cancel_btn.get_visible())
        self.assertFalse(v.delete_btn.get_visible())
        with open(p, "a") as f:
            f.write(json.dumps({"type": "result", "is_error": False, "result": "Fini"}) + "\n" + '{"type": "assi')
        v.refresh()
        self.assertEqual(text().count("Première phrase"), 1)
        self.assertIn("✓ Fini", text())
        self.assertNotIn("assi", text().split("✓ Fini")[1])      # ligne incomplète : pas encore lue

    def test_unknown_task_is_not_shown(self):
        v = self.view()
        self.assertFalse(v.show_task("99"))
        self.assertFalse(v.detail.get_visible())

    def test_cancel_then_delete(self):
        t = tasks.add("x", cwd=str(self.home))
        v = self.view()
        v.show_task(t.id)
        v.on_cancel()
        self.assertEqual(tasks.get(t.id).state, "cancelled")
        self.assertFalse(v.cancel_btn.get_visible())
        self.assertTrue(v.delete_btn.get_visible())
        v.on_delete()
        self.assertIsNone(tasks.get(t.id))
        self.assertFalse(v.detail.get_visible())
        self.assertIn(f"Tâche {t.id} supprimée", self.window.toasts)

    def test_resume_button_needs_a_callback_and_a_conversation(self):
        t = tasks.add("x", cwd=str(self.home))
        tasks.update(t.id, state="done", session_id="sess-1")
        v = self.view()
        v.show_task(t.id)
        self.assertFalse(v.resume_btn.get_visible())              # pas de rappel
        got = []
        v = self.view(on_resume=got.append)
        v.show_task(t.id)
        self.assertTrue(v.resume_btn.get_visible())
        v.on_resume_clicked()
        self.assertEqual([(x.id, x.session_id, x.cwd) for x in got], [(t.id, "sess-1", str(self.home))])
        tasks.update(t.id, session_id=None)
        v.refresh()
        self.assertFalse(v.resume_btn.get_visible())

    def test_add_task_reports_errors_as_toasts(self):
        v = self.view()
        self.assertIsNone(v.add_task({"message": " ", "cwd": str(self.home), "model": None,
                                      "rights": "lecture", "when": "quota"}))
        self.assertTrue(self.window.toasts[-1].startswith("Tâche non ajoutée"))
        t = v.add_task({"message": "ok", "cwd": str(self.home), "model": None, "rights": "lecture",
                        "when": "nuit"})
        self.assertEqual((t.when, len(rows(v))), ("nuit", 1))


@unittest.skipUnless(GTK, "affichage graphique requis")
class NewTaskDialogTest(HomeTestCase):
    def dialog(self):
        from ccs_app.gui.tasks_view import NewTaskDialog
        self.got = []
        return NewTaskDialog(self.got.append, str(self.home))

    def type(self, d, text):
        d.message.get_buffer().set_text(text)

    def test_add_needs_a_message(self):
        d = self.dialog()
        self.assertFalse(d.ok_btn.get_sensitive())
        self.type(d, "Fais ceci")
        self.assertTrue(d.ok_btn.get_sensitive())
        self.assertEqual(d.values(), {"message": "Fais ceci", "cwd": str(self.home), "model": None,
                                      "rights": "modifications", "when": "quota"})

    def test_all_rights_show_the_warning(self):
        d = self.dialog()
        self.assertFalse(d.danger_row.get_visible())
        d.rights_row.set_selected(2)
        self.assertEqual(d.rights(), "tout")
        self.assertTrue(d.danger_row.get_visible())
        self.assertIn("sans rien demander", d.danger_row.get_title())
        d.rights_row.set_selected(0)
        self.assertEqual(d.rights(), "lecture")
        self.assertFalse(d.danger_row.get_visible())

    def test_clock_time_is_validated(self):
        d = self.dialog()
        self.type(d, "x")
        d.when_row.set_selected(2)
        self.assertTrue(d.time_row.get_visible())
        self.assertFalse(d.ok_btn.get_sensitive())               # heure vide
        d.time_row.set_text("25:99")
        self.assertFalse(d.ok_btn.get_sensitive())
        d.time_row.set_text("7:05")
        self.assertTrue(d.ok_btn.get_sensitive())
        self.assertEqual(d.when(), "07:05")
        d.when_row.set_selected(1)
        self.assertEqual(d.when(), "nuit")
        self.assertFalse(d.time_row.get_visible())

    def test_add_hands_the_values_over(self):
        d = self.dialog()
        self.type(d, "Fais ceci")
        d.model_row.set_selected(1)
        d.on_add()
        self.assertEqual(self.got[0]["model"], "opus")
        self.assertEqual(self.got[0]["message"], "Fais ceci")

    def test_add_does_nothing_without_a_message(self):
        d = self.dialog()
        d.on_add()
        self.assertEqual(self.got, [])


if __name__ == "__main__":
    unittest.main()
