"""Section Planning de l'Accueil : carte « Meilleur moment pour une grosse tâche ».

Widgets créés sans être affichés (affichage requis, sinon tests sautés). HOME isolé."""

import unittest
from datetime import datetime, timedelta, timezone

from .helpers import HomeTestCase

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gtk
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False


class FakeWindow:
    def __init__(self):
        self.toasts, self.opened = [], []

    def open_claude(self, cwd, resume=None, title=None, external=False):
        self.opened.append((cwd, resume))
        return "integre"

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


def walk_all(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from walk_all(child)
        child = child.get_next_sibling()


def toggles(widget):
    out, child = [], widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.ToggleButton):
            out.append(child)
        out += toggles(child)
        child = child.get_next_sibling()
    return out


def state():
    now = datetime.now(timezone.utc)
    return {"updated_at": now.timestamp(), "orchestrator": {"enabled": False, "plan": []},
            "accounts": [{"name": "perso", "error": None, "fetched_at": now.timestamp(),
                          "limits": [{"kind": "session", "label": "Session", "percent": 100,
                                      "resets_at": (now + timedelta(hours=4)).isoformat()},
                                     {"kind": "weekly_all", "label": "Semaine", "percent": 10,
                                      "resets_at": (now + timedelta(days=3)).isoformat()}]}]}


@unittest.skipUnless(GTK, "affichage graphique requis")
class MomentCardTest(HomeTestCase):
    def page(self):
        from ccs_app.gui.planning import PlanningPage
        page = PlanningPage(FakeWindow())
        page.render(state())
        return page

    def test_card_is_shown_with_advice(self):
        text = "\n".join(labels(self.page().box))
        self.assertIn("Meilleur moment pour une grosse tâche", text)
        self.assertIn("Meilleur départ", text)

    def test_moment_card_folded_by_default_and_kept_open(self):
        from gi.repository import Gtk as G
        page = self.page()
        exp = [w for w in walk_all(page.box) if isinstance(w, G.Expander)]
        self.assertEqual(len(exp), 1)
        self.assertFalse(exp[0].get_expanded())
        exp[0].set_expanded(True)
        page.render(state())                      # nouveau rendu (état relu) : reste ouverte
        exp = [w for w in walk_all(page.box) if isinstance(w, G.Expander)]
        self.assertTrue(exp[0].get_expanded())

    def test_duration_choices(self):
        page = self.page()
        page.moment_open = True                   # contenu de la carte repliable visible
        page.render(state())
        buttons = [b for b in toggles(page.box) if b.get_label().endswith(" h")]
        self.assertEqual([b.get_label() for b in buttons], ["1 h", "2 h", "3 h", "4 h", "6 h", "8 h"])
        self.assertTrue(buttons[2].get_active())
        buttons[4].set_active(True)
        self.assertEqual(page.moment_hours, 6)
        active = [b.get_label() for b in toggles(page.box) if b.get_label().endswith(" h")
                  and b.get_active()]
        self.assertEqual(active, ["6 h"])

    def test_no_account(self):
        from ccs_app.gui.planning import PlanningPage
        page = PlanningPage(FakeWindow())
        page.render({"accounts": []})
        self.assertNotIn("Meilleur moment pour une grosse tâche", "\n".join(labels(page.box)))


@unittest.skipUnless(GTK, "affichage graphique requis")
class TasksViewTest(HomeTestCase):
    def test_one_instance_survives_every_render(self):
        from ccs_app.gui.planning import PlanningPage
        from ccs_app.gui.tasks_view import TasksView
        page = PlanningPage(FakeWindow())
        view = page.tasks_view
        for st in (state(), state(), {"accounts": []}, state()):
            page.render(st)
            self.assertIs(view.get_parent(), page.box)
            found, child = [], page.box.get_first_child()
            while child is not None:
                found += [child] if isinstance(child, TasksView) else []
                child = child.get_next_sibling()
            self.assertEqual(found, [view])

    def test_selection_is_kept_across_renders(self):
        from ccs_app import tasks
        from ccs_app.gui.planning import PlanningPage
        task = tasks.add("lire le dossier", cwd=str(self.home))
        page = PlanningPage(FakeWindow())
        page.render(state())
        self.assertTrue(page.tasks_view.show_task(task.id))
        page.render(state())
        self.assertEqual(page.tasks_view.selected, task.id)

    def test_resume_opens_the_conversation_in_a_tab(self):
        from types import SimpleNamespace
        from ccs_app.gui.planning import PlanningPage
        window = FakeWindow()
        page = PlanningPage(window)
        page.tasks_view.on_resume(SimpleNamespace(cwd="/tmp/projet", session_id="abc-123"))
        self.assertEqual(window.opened, [("/tmp/projet", "abc-123")])


if __name__ == "__main__":
    unittest.main()
