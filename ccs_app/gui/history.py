"""Onglet Historique : courbes par compte sur 24 h ou 7 jours, journal des bascules."""

import sqlite3
import time
from datetime import datetime

from gi.repository import Adw, Gtk

from .. import switch_log
from .charts import SESSION_RGB, WEEKLY_RGB, LineChart
from .common import caption, clear
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
        legend = Gtk.Box(spacing=16, halign=Gtk.Align.CENTER)
        legend.append(Gtk.Label(label="━ session", css_classes=["legend-session"]))
        legend.append(Gtk.Label(label="━ semaine", css_classes=["legend-weekly"]))
        legend.append(Gtk.Label(label="┅ rythme idéal de la semaine", css_classes=["dim-label"]))
        outer.append(legend)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        outer.append(self.list)

        head = Gtk.Box(spacing=8, margin_top=12)
        head.append(Gtk.Label(label="Journal des bascules", xalign=0, hexpand=True, css_classes=["title-4"]))
        head.append(toggle_group(switch_log.PERIODS, self.journal_days, self.on_journal_range))
        outer.append(head)
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
        if not accounts:
            self.list.append(Adw.StatusPage(icon_name="document-open-recent-symbolic",
                                            title="Pas encore d'historique"))
            return
        switches = store.events(t0, type="switch")
        for a in accounts:
            name = a["name"]
            session = [(ts, p) for ts, p, _ in store.samples(name, "session", t0)]
            weekly_raw = store.samples(name, "weekly_all", t0)
            weekly = [(ts, p) for ts, p, _ in weekly_raw]
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                           css_classes=["card", "profile-card"])
            card.append(Gtk.Label(label=name, xalign=0, css_classes=["title-4"]))
            if not session and not weekly:
                card.append(caption("Aucun relevé sur cette période."))
                self.list.append(card)
                continue
            chart = LineChart()
            markers = [(e.ts, f"→ {name}") for e in switches
                       if e.profile == name and e.detail.get("mode") in CHART_MODES]
            chart.set_data(t0, t1, [
                (session, SESSION_RGB, False, "session"),
                (weekly, WEEKLY_RGB, False, "semaine"),
                (ideal_weekly_series(weekly_raw), WEEKLY_RGB, True, "idéal"),
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
            self.journal.append(caption("Aucune bascule sur cette période."))
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
