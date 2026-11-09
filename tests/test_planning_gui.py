"""Onglet Planning : carte « Meilleur moment pour une grosse tâche ».

Widgets créés sans être affichés (affichage requis, sinon tests sautés). HOME isolé."""

import unittest
from datetime import datetime, timedelta, timezone

from .helpers import HomeTestCase

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gtk
    GTK = bool(Gtk.init_check())
except (ImportError, ValueError):
    GTK = False


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

    def test_duration_choices(self):
        page = self.page()
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


if __name__ == "__main__":
    unittest.main()
