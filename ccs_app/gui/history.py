"""Partie Historique de l'onglet Analyse : courbes par compte sur 24 h ou 7 jours, journal des bascules."""

import sqlite3
import time
from datetime import datetime

from gi.repository import Adw, Gdk, Gtk

from .. import switch_log
from .charts import LineChart
from .common import account_rgb, caption, card_box, clear, empty_state, sync_accounts, tag_account
from .geometry import ideal_weekly_series

RANGES = {"24 h": 86400, "7 jours": 7 * 86400}
# Bascules marquées sur les courbes (le premier relevé du service n'en est pas une).
CHART_MODES = ("auto", "manual", "anticipee", "blocage")
JOURNAL_PAGE = 100
KIND_ICONS = {
    "auto": "emblem-synchronizing-symbolic",
    "anticipee": "alarm-symbolic",
    "blocage": "dialog-warning-symbolic",
    "manuelle": "input-mouse-symbolic",
    "initial": "media-playback-start-symbolic",
    "echec": "dialog-error-symbolic",
    "limite": "action-unavailable-symbolic",
    "fenetre": "weather-clear-symbolic",
}
KIND_CLASSES = {"echec": "error", "limite": "warning", "blocage": "warning"}


def hex_color(rgb):
    return "#" + "".join(f"{round(c * 255):02x}" for c in rgb)


# Légende des courbes : la couleur est celle du compte (titre de chaque carte), la session en
# trait plein, la semaine en trait plus clair : un seul libellé qui se replie. Espaces
# insécables dans chaque élément, cadratin entre eux : la ligne ne se coupe qu'entre deux.
NBSP, EM_SPACE = chr(0x00A0), chr(0x2003)


def _legend_item(text, attrs):
    return f"<span {attrs}>{text.replace(' ', NBSP)}</span>"


LEGEND = EM_SPACE.join((
    _legend_item("━ session", "weight='bold'"),
    _legend_item("━ semaine", "weight='bold' alpha='55%'"),
    _legend_item("┅ rythme idéal de la semaine", "alpha='55%'")))


def toggle_group(choices, active, on_toggled):
    """Boutons liés exclusifs : [(libellé, valeur)] ; `on_toggled(valeur)` au choix."""
    box = Gtk.Box(css_classes=["linked"], halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
    first = None
    for label, value in choices:
        b = Gtk.ToggleButton(label=label, active=value == active)
        if first:
            b.set_group(first)
        first = first or b
        b.connect("toggled", lambda btn, v=value: btn.get_active() and on_toggled(v))
        box.append(b)
    return box


class ReflowLayout(Gtk.LayoutManager):
    """Éléments sur une ligne (les suivants à droite, le premier prend le reste), ou les uns
    sous les autres quand la largeur manque ; halign et valign de chacun respectés."""

    def __init__(self, spacing=8, row_spacing=6):
        super().__init__()
        self.spacing, self.row_spacing = spacing, row_spacing

    @staticmethod
    def items(widget):
        out, child = [], widget.get_first_child()
        while child is not None:
            if child.should_layout():
                out.append(child)
            child = child.get_next_sibling()
        return out

    def one_line(self, widget, width):
        """Les éléments tiennent côte à côte dans `width` (-1 : largeur libre)."""
        items = self.items(widget)
        need = sum(w.measure(Gtk.Orientation.HORIZONTAL, -1)[1] for w in items)
        return width < 0 or width >= need + self.spacing * max(0, len(items) - 1)

    def do_get_request_mode(self, _widget):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, widget, orientation, for_size):
        items = self.items(widget)
        if not items:
            return 0, 0, -1, -1
        if orientation == Gtk.Orientation.HORIZONTAL:
            sizes = [w.measure(orientation, -1)[:2] for w in items]
            gaps = self.spacing * (len(items) - 1)
            return max(s[0] for s in sizes), sum(s[1] for s in sizes) + gaps, -1, -1
        if self.one_line(widget, for_size):
            sizes = [w.measure(orientation, -1)[:2] for w in items]
            return max(s[0] for s in sizes), max(s[1] for s in sizes), -1, -1
        sizes = [w.measure(orientation, for_size)[:2] for w in items]
        gaps = self.row_spacing * (len(items) - 1)
        return sum(s[0] for s in sizes) + gaps, sum(s[1] for s in sizes) + gaps, -1, -1

    def do_allocate(self, widget, width, height, _baseline):
        items = self.items(widget)
        if not items:
            return
        if self.one_line(widget, width):
            # Les suivants à leur largeur naturelle, à droite ; le premier prend le reste.
            x = width
            for w in reversed(items[1:]):
                nat = w.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
                x -= nat
                place(w, x, 0, nat, height)
                x -= self.spacing
            place(items[0], 0, 0, x, height)
            return
        y = 0
        for w in items:
            h = w.measure(Gtk.Orientation.VERTICAL, width)[1]
            place(w, 0, y, width, h)
            y += h + self.row_spacing


def place(widget, x, y, width, height):
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = x, y, max(0, width), max(0, height)
    widget.size_allocate(rect, -1)


class Reflow(Gtk.Box):
    """Titre et boutons sur une ligne, ou les boutons sous le titre en fenêtre étroite : la
    largeur minimale est celle du plus large, pas leur somme. Un Gtk.Box (qui libère seul
    ses enfants) disposé par `ReflowLayout` ; parcours au clavier standard, contrairement à
    un Gtk.FlowBox, qui piège la touche Tab dès qu'un élément n'est pas focalisable."""

    def __init__(self, *items, spacing=8, row_spacing=6, **props):
        super().__init__(**props)
        for w in items:
            self.append(w)
        self.layout = ReflowLayout(spacing, row_spacing)
        self.set_layout_manager(self.layout)

    @property
    def items(self):
        return tuple(ReflowLayout.items(self))

    def one_line(self, width):
        return self.layout.one_line(self, width)


def journal_row(entry):
    row = Adw.ActionRow(title=entry.title, subtitle=entry.reason, use_markup=False,
                        title_lines=1, tooltip_text=entry.detail or None)
    icon = Gtk.Image(icon_name=KIND_ICONS.get(entry.kind, "emblem-synchronizing-symbolic"),
                     valign=Gtk.Align.CENTER)
    css = KIND_CLASSES.get(entry.kind) or (None if entry.ok else "error")
    if css:
        icon.add_css_class(css)
    row.add_prefix(icon)
    row.add_suffix(Gtk.Label(label=f"{datetime.fromtimestamp(entry.ts):%H:%M}", valign=Gtk.Align.CENTER,
                             css_classes=["dim-label", "numeric"]))
    return row


class HistoryPage(Gtk.ScrolledWindow):
    def __init__(self, window):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.window = window
        self.span = RANGES["24 h"]
        self.last = None
        self.journal_days = switch_log.PERIODS[0][1]
        self.journal_limit = JOURNAL_PAGE
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                        margin_top=18, margin_bottom=18, margin_start=12, margin_end=12)
        outer.append(toggle_group(((label, span) for label, span in RANGES.items()), self.span,
                                  self.on_range))
        # Légende sur une ligne ; en fenêtre étroite, le rythme idéal passe en dessous.
        self.legend = Gtk.Label(label=LEGEND, use_markup=True, wrap=True, xalign=0.5,
                                justify=Gtk.Justification.CENTER)
        outer.append(self.legend)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        outer.append(self.list)

        # Titre et périodes du journal sur une ligne, ou sur deux en fenêtre étroite.
        periods = toggle_group(switch_log.PERIODS, self.journal_days, self.on_journal_range)
        periods.set_halign(Gtk.Align.END)
        self.journal_head = Reflow(
            Gtk.Label(label="Journal des bascules", xalign=0, halign=Gtk.Align.START, css_classes=["title-4"]),
            periods, margin_top=12)
        outer.append(self.journal_head)
        self.journal = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.append(self.journal)
        self.set_child(Adw.Clamp(maximum_size=760, child=outer))

    def on_range(self, span):
        self.span = span
        if self.last:
            self.render(*self.last)

    def on_journal_range(self, days):
        self.journal_days = days
        self.journal_limit = JOURNAL_PAGE
        if self.last:
            self.render_journal(self.last[1])

    def render(self, state, store):
        self.last = (state, store)
        self.render_charts(state, store)
        self.render_journal(store)

    def render_charts(self, state, store):
        clear(self.list)
        t1 = time.time()
        t0 = t1 - self.span
        accounts = state.get("accounts") or []
        sync_accounts(a["name"] for a in accounts)
        if not accounts:
            refresh = getattr(self.window, "refresh", None)
            self.list.append(empty_state(
                "document-open-recent-symbolic", "Pas encore d'historique",
                "Les courbes apparaissent après les premiers relevés des comptes.",
                "Actualiser", refresh))
            return
        switches = store.events(t0, type="switch")
        for a in accounts:
            name = a["name"]
            session = [(ts, p) for ts, p, _ in store.samples(name, "session", t0)]
            weekly_raw = store.samples(name, "weekly_all", t0)
            weekly = [(ts, p) for ts, p, _ in weekly_raw]
            card = card_box(8, account=name)
            card.append(tag_account(Gtk.Label(label=name, xalign=0, css_classes=["title-4"]), name))
            if not session and not weekly:
                card.append(caption("Aucun relevé sur cette période."))
                self.list.append(card)
                continue
            chart = LineChart()
            markers = [(e.ts, f"→ {name}") for e in switches
                       if e.profile == name and e.detail.get("mode") in CHART_MODES]
            color = account_rgb(name)
            light = (*color, 0.55)     # la semaine : même couleur, plus claire
            chart.set_data(t0, t1, [
                (session, color, False, "session"),
                (weekly, light, False, "semaine"),
                (ideal_weekly_series(weekly_raw), light, True, "idéal"),
            ], markers)
            card.append(chart)
            self.list.append(card)

    # ---- journal des bascules ----------------------------------------------------------

    def render_journal(self, store):
        clear(self.journal)
        now = time.time()
        try:
            entries = switch_log.load(store, self.journal_days, now)
        except (OSError, sqlite3.Error) as e:
            self.journal.append(caption(f"Journal illisible : {e}", error=True))
            return
        if not entries:
            self.journal.append(empty_state("emblem-synchronizing-symbolic",
                                            "Aucune bascule sur cette période", compact=True))
            return
        shown = entries[:self.journal_limit]
        for label, group in switch_log.group_by_day(shown, now):
            self.journal.append(Gtk.Label(label=label, xalign=0, css_classes=["heading"], margin_top=4))
            listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
            for entry in group:
                listbox.append(journal_row(entry))
            self.journal.append(listbox)
        rest = len(entries) - len(shown)
        if rest > 0:
            more = Gtk.Button(label=f"Afficher {min(JOURNAL_PAGE, rest)} de plus", css_classes=["pill"],
                              halign=Gtk.Align.CENTER, margin_top=6)
            more.connect("clicked", self.on_more_journal)
            self.journal.append(more)

    def on_more_journal(self, *_):
        self.journal_limit += JOURNAL_PAGE
        if self.last:
            self.render_journal(self.last[1])
