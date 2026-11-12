"""Groupe « Budgets par projet » de l'onglet Analyse : calcul simulé, dossiers temporaires,
widgets créés sans être affichés (tests sautés sans GTK 4 / libadwaita / affichage)."""

import unittest
from datetime import datetime, timezone
from unittest import mock

from ccs_app import budget
from tests.helpers import HomeTestCase

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


@unittest.skipUnless(GTK, "GTK 4, libadwaita ou affichage absents")
class BudgetGroupTest(HomeTestCase):
    @classmethod
    def setUpClass(cls):
        Adw.init()

    def setUp(self):
        super().setUp()
        from ccs_app.gui import budget_view
        self.mod = budget_view
        self.app = self.home / "Work" / "App"
        self.app.mkdir(parents=True)
        self.toasts = []
        self.result = None
        p = mock.patch.object(budget_view.GLib, "idle_add", side_effect=lambda f, *a: f(*a))
        p.start()
        self.addCleanup(p.stop)

    def compute(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def group(self):
        return self.mod.BudgetGroup(toast=self.toasts.append, compute=self.compute, run=lambda f: f())

    def status(self, *rows):
        return budget.Status(NOW, NOW, tuple(rows), sum(r.spent for r in rows))

    def test_empty_state(self):
        self.result = self.status()
        g = self.group()
        g.refresh()
        self.assertTrue(g.empty.get_visible())
        self.assertEqual(g.empty.get_title(), "Aucun budget défini")
        self.assertEqual(g.rows, {})

    def test_rows_with_progress_and_levels(self):
        a, b = str(self.app), str(self.home / "Autre")
        self.result = self.status(budget.Row(a, 10.0, 12.0, 120.0, 0.6), budget.Row(b, 10.0, 8.5, 85.0, 0.4))
        g = self.group()
        g.refresh()
        self.assertFalse(g.empty.get_visible())
        self.assertEqual(set(g.rows), {a, b})
        over, warn = g.rows[a], g.rows[b]
        self.assertEqual(over.bar.get_fraction(), 1.0)
        self.assertTrue(over.bar.has_css_class("error"))
        self.assertTrue(warn.bar.has_css_class("warning"))
        self.assertAlmostEqual(warn.bar.get_fraction(), 0.85)
        self.assertIn("85 %", warn.get_subtitle())
        self.assertIn("40 %", warn.get_subtitle())
        g.refresh()                                  # un second affichage remplace, ne duplique pas
        self.assertEqual(len(g._shown), 2)

    def test_error_is_shown_in_the_group(self):
        self.result = OSError("journaux illisibles")
        g = self.group()
        g.refresh()
        self.assertEqual(g.empty.get_title(), "Calcul impossible")
        self.assertIn("illisibles", g.empty.get_subtitle())

    def test_set_amount_and_remove_write_the_store(self):
        self.result = self.status()
        g = self.group()
        self.assertTrue(g.set_amount(str(self.app), 25.0))
        self.assertEqual(budget.load(), {str(self.app): 25.0})
        self.assertTrue(g.remove_budget(str(self.app)))
        self.assertEqual(budget.load(), {})
        self.assertFalse(g.set_amount(str(self.app), -1))
        self.assertTrue(self.toasts)

    def test_stale_result_is_ignored(self):
        self.result = self.status()
        g = self.group()
        g._generation = 5
        g._show(4, self.status(budget.Row("/x", 1.0, 0.5, 50.0, 1.0)), None)
        self.assertEqual(g.rows, {})

    def test_core_fr(self):
        self.assertEqual(self.mod.core_fr(25.0), "25")
        self.assertEqual(self.mod.core_fr(12.5), "12,5")


if __name__ == "__main__":
    unittest.main()
