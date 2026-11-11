"""Fenêtre étroite : l'onglet Historique tient dans 360 px (légende et en-tête du journal
qui passent à la ligne), le filtre d'origine des Sessions s'abrège sans changer la liste.

Widgets créés sans être affichés (affichage requis, sinon tests sautés) ; HOME isolé."""

import time
import unittest
from datetime import datetime, timezone

from .helpers import HomeTestCase

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False

WINDOW_MIN = 360   # largeur minimale de la fenêtre (Window.set_size_request)


def walk(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from walk(child)
        child = child.get_next_sibling()


def min_width(widget):
    return widget.measure(Gtk.Orientation.HORIZONTAL, -1)[0]


class Lim:
    def __init__(self, kind, percent, resets):
        self.kind, self.percent = kind, percent
        self.resets_at = datetime.fromtimestamp(resets, timezone.utc)


@unittest.skipUnless(GTK, "GTK 4, libadwaita ou affichage absents")
class HistoryWidthTest(HomeTestCase):
    @classmethod
    def setUpClass(cls):
        Adw.init()

    def setUp(self):
        super().setUp()
        from ccs_app.gui import history
        from ccs_app.store import Store
        self.mod = history
        self.db = Store()
        self.addCleanup(self.db.close)
        now = time.time()
        for name in ("perso", "pro"):
            for i in range(12):
                t = now - 6 * 3600 + i * 1800
                self.db.add_samples(t, name, [Lim("session", 5.0 * i, now + 3600),
                                              Lim("weekly_all", 30 + i, now + 3 * 86400)])
        self.db.add_event(now - 7200, "switch", "pro", {"mode": "auto", "from": "perso",
                                                        "reason": "perso à 98 % → pro (au repos)"})
        self.db.add_event(now - 3600, "switch", "perso", {"mode": "manual", "from": "pro"})
        self.state = {"accounts": [{"name": "perso"}, {"name": "pro"}]}

    def page(self):
        """Page dans une fenêtre jamais affichée, détruite à la fin du test."""
        page = self.mod.HistoryPage(window=None)
        page.render(self.state, self.db)
        win = Gtk.Window(child=page)
        self.addCleanup(win.destroy)
        return page

    def test_fits_the_narrow_window(self):
        page = self.page()
        self.assertTrue(list(walk(page.journal)), "journal rempli")
        self.assertLessEqual(min_width(page), WINDOW_MIN)

    def test_legend_wraps_between_items_only(self):
        legend = self.page().legend
        self.assertTrue(legend.get_wrap())
        items = legend.get_text().replace(self.mod.NBSP, " ").split(self.mod.EM_SPACE)
        self.assertEqual(items, ["━ session", "━ semaine", "┅ rythme idéal de la semaine"])
        narrow, wide = legend.measure(Gtk.Orientation.HORIZONTAL, -1)[:2]
        self.assertLess(narrow, wide)
        one_line = legend.measure(Gtk.Orientation.VERTICAL, wide)[0]
        self.assertGreater(legend.measure(Gtk.Orientation.VERTICAL, narrow)[0], one_line)
        # Le plus long élément reste entier : la coupure tombe entre deux éléments.
        probe = Gtk.Label(label="┅ rythme idéal de la semaine")
        self.assertGreaterEqual(narrow, min_width(probe))

    def test_legend_colors_follow_the_curves(self):
        from ccs_app.gui.charts import SESSION_RGB, WEEKLY_RGB
        self.assertIn(self.mod.hex_color(SESSION_RGB), self.mod.LEGEND)
        self.assertIn(self.mod.hex_color(WEEKLY_RGB), self.mod.LEGEND)
        self.assertEqual(self.mod.hex_color((1.0, 0.5, 0.0)), "#ff8000")

    def test_journal_head_wraps(self):
        head = self.page().journal_head
        title, periods = head.items
        self.assertEqual(title.get_label(), "Journal des bascules")
        lo, nat = head.measure(Gtk.Orientation.HORIZONTAL, -1)[:2]
        self.assertEqual(lo, max(min_width(title), min_width(periods)))  # pas la somme des deux
        self.assertGreater(nat, min_width(title) + min_width(periods))
        one_line = head.measure(Gtk.Orientation.VERTICAL, nat)[0]
        two_lines = head.measure(Gtk.Orientation.VERTICAL, lo)[0]
        self.assertGreater(two_lines, one_line)
        self.assertTrue(head.one_line(nat))
        self.assertFalse(head.one_line(lo))

    def test_reflow_layout(self):
        """Côte à côte : titre à gauche, périodes à droite ; étroit : périodes sous le titre."""
        from ccs_app import switch_log
        title = Gtk.Label(label="Journal des bascules", halign=Gtk.Align.START, css_classes=["title-4"])
        periods = self.mod.toggle_group(switch_log.PERIODS, 7, lambda _v: None)
        periods.set_halign(Gtk.Align.END)
        head = self.mod.Reflow(title, periods)
        win = Gtk.Window(child=head)  # jamais affichée
        self.addCleanup(win.destroy)
        nat = head.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
        for width in (nat + 100, max(min_width(title), min_width(periods))):
            height = head.measure(Gtk.Orientation.VERTICAL, width)[0]
            head.size_allocate(self.rect(width, height), -1)
            t, p = title.compute_bounds(head)[1], periods.compute_bounds(head)[1]
            self.assertEqual(t.get_x(), 0, width)
            self.assertAlmostEqual(p.get_x() + p.get_width(), width, delta=1)  # aligné à droite
            if width > nat:
                self.assertLess(t.get_x() + t.get_width(), p.get_x())
            else:
                self.assertGreaterEqual(p.get_y(), t.get_y() + t.get_height())

    @staticmethod
    def rect(width, height):
        from gi.repository import Gdk
        r = Gdk.Rectangle()
        r.x, r.y, r.width, r.height = 0, 0, width, height
        return r

    def test_period_buttons_still_switch_the_journal(self):
        page = self.page()
        buttons = [b for b in walk(page.journal_head) if isinstance(b, Gtk.ToggleButton)]
        self.assertEqual([b.get_label() for b in buttons], ["7 jours", "30 jours", "Tout"])
        self.assertTrue(all(b.get_focusable() for b in buttons))
        self.assertFalse(page.journal_head.get_focusable())  # Tab passe par les boutons
        buttons[2].set_active(True)
        self.assertIsNone(page.journal_days)
        buttons[1].set_active(True)
        self.assertEqual(page.journal_days, 30)


@unittest.skipUnless(GTK, "GTK 4, libadwaita ou affichage absents")
class OriginFilterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Adw.init()

    def drop(self, short):
        """Liste déroulante dans une fenêtre jamais affichée (les libellés se lient une fois
        le widget rattaché à une fenêtre)."""
        from ccs_app.gui.common import string_factory
        from ccs_app.gui.sessions_page import ORIGIN_CHOICES
        model = Gtk.StringList.new([label for label, _ in ORIGIN_CHOICES])
        drop = Gtk.DropDown(model=model, factory=string_factory(True, short),
                            list_factory=string_factory(False))
        win = Gtk.Window(child=drop)
        self.addCleanup(win.destroy)
        return drop

    @staticmethod
    def labels(widget):
        return [w.get_label() for w in walk(widget) if isinstance(w, Gtk.Label) and w.get_child_visible()]

    def button(self, drop):
        return self.labels(drop.get_first_child())

    def listed(self, drop):
        pop = next(w for w in walk(drop) if isinstance(w, Gtk.Popover))
        return self.labels(next(w for w in walk(pop) if isinstance(w, Gtk.ListView)))

    def test_short_label_in_the_button(self):
        from ccs_app.gui.sessions_page import ORIGIN_SHORT
        drop = self.drop(ORIGIN_SHORT)
        self.assertEqual(self.button(drop), ["Toutes"])
        self.assertEqual(self.listed(drop), ["Toutes les origines", "VS Code", "Terminal"])
        drop.set_selected(2)
        self.assertEqual(self.button(drop), ["Terminal"])
        self.assertEqual(drop.get_selected_item().get_string(), "Terminal")

    def test_full_label_without_short_labels(self):
        self.assertEqual(self.button(self.drop(None)), ["Toutes les origines"])


if __name__ == "__main__":
    unittest.main()
