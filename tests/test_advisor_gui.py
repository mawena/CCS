"""Cartes « Bilan de la semaine » et « Conseiller de formule » (GTK, affichage requis).

Lancées seulement avec CCS_GUI_TESTS=1 (sous Xvfb, jamais sur le bureau réel)."""

import copy
import os
import unittest
from datetime import datetime, timedelta, timezone

GTK = False
if os.environ.get("CCS_GUI_TESTS") == "1":
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, GLib, Gtk
        GTK = Gtk.init_check() if hasattr(Gtk, "init_check") else True
    except (ImportError, ValueError):
        GTK = False

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def texts(widget):
    out = []
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Label):
            out.append(child.get_label())
        out += texts(child)
        child = child.get_next_sibling()
    return out


def spin(until, timeout=5.0):
    ctx = GLib.MainContext.default()
    deadline = GLib.get_monotonic_time() + int(timeout * 1e6)
    while not until() and GLib.get_monotonic_time() < deadline:
        ctx.iteration(False)


@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class CardsTest(unittest.TestCase):
    def setUp(self):
        Adw.init()

    def advice(self):
        from ccs_app import advisor
        from ccs_app.settings import DEFAULTS
        from tests.test_advisor import AnalyzeTest
        s = copy.deepcopy(DEFAULTS)
        s["advisor"]["weeks"] = 2
        return advisor.analyze(AnalyzeTest().two_pro(), {"perso": "pro", "boulot": "pro"}, NOW, s)

    def test_advisor_card(self):
        from ccs_app.gui.advisor_cards import AdvisorCard
        card = AdvisorCard(compute=self.advice)
        card.load()
        spin(lambda: not card.loading)
        shown = texts(card)
        self.assertIn("Conseil : 2 Pro — 40 $/mois", shown)
        self.assertIn("40 $/mois", shown)
        self.assertTrue(any(t.startswith("• Relevés analysés") for t in shown))

    def test_advisor_card_error(self):
        from ccs_app.gui.advisor_cards import AdvisorCard

        def boom():
            raise OSError("illisible")
        card = AdvisorCard(compute=boom)
        card.load()
        spin(lambda: not card.loading)
        self.assertIn("Calcul impossible : illisible", texts(card))

    def test_weekly_card_defaults_to_the_last_complete_week(self):
        from ccs_app import weekly_report
        from ccs_app.gui.advisor_cards import WeeklyReportCard
        anchor = NOW - timedelta(days=1)
        weeks = [(anchor, NOW), (anchor - timedelta(days=7), anchor),
                 (anchor - timedelta(days=14), anchor - timedelta(days=7))]
        built, done = [], []

        def build(start, end):
            built.append((start, end))
            return weekly_report.WeekReport(start, end)
        card = WeeklyReportCard(build=build, choices=lambda: weeks)
        card.load(then=lambda: done.append(True))
        spin(lambda: done)
        self.assertEqual(built, [weeks[1]])
        self.assertEqual(card.dropdown.get_model().get_n_items(), 3)
        self.assertTrue(card.dropdown.get_model().get_string(0).startswith("Semaine en cours"))
        self.assertIn("Bascules et alertes", texts(card))
        card.dropdown.set_selected(2)
        spin(lambda: len(built) == 2 and any("Aucune bascule" in t for t in texts(card)))
        self.assertEqual(built[-1], weeks[2])


if __name__ == "__main__":
    unittest.main()
