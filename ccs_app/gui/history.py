"""Onglet Historique : courbes par compte sur 24 h ou 7 jours."""

import time

from gi.repository import Adw, Gtk

from .charts import SESSION_RGB, WEEKLY_RGB, LineChart
from .common import caption, clear
from .geometry import ideal_weekly_series

RANGES = {"24 h": 86400, "7 jours": 7 * 86400}


class HistoryPage(Gtk.ScrolledWindow):
    def __init__(self, window):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.window = window
        self.span = RANGES["24 h"]
        self.last = None
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                        margin_top=18, margin_bottom=18, margin_start=12, margin_end=12)
        toggles = Gtk.Box(css_classes=["linked"], halign=Gtk.Align.CENTER)
        first = None
        for label, span in RANGES.items():
            b = Gtk.ToggleButton(label=label, active=first is None)
            if first:
                b.set_group(first)
            first = first or b
            b.connect("toggled", self.on_range, span)
            toggles.append(b)
        outer.append(toggles)
        legend = Gtk.Box(spacing=16, halign=Gtk.Align.CENTER)
        legend.append(Gtk.Label(label="━ session", css_classes=["legend-session"]))
        legend.append(Gtk.Label(label="━ semaine", css_classes=["legend-weekly"]))
        legend.append(Gtk.Label(label="┅ rythme idéal de la semaine", css_classes=["dim-label"]))
        outer.append(legend)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        outer.append(self.list)
        self.set_child(Adw.Clamp(maximum_size=760, child=outer))

    def on_range(self, button, span):
        if button.get_active():
            self.span = span
            if self.last:
                self.render(*self.last)

    def render(self, state, store):
        self.last = (state, store)
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
                       if e.profile == name and e.detail.get("mode") in ("auto", "manual")]
            chart.set_data(t0, t1, [
                (session, SESSION_RGB, False, "session"),
                (weekly, WEEKLY_RGB, False, "semaine"),
                (ideal_weekly_series(weekly_raw), WEEKLY_RGB, True, "idéal"),
            ], markers)
            card.append(chart)
            self.list.append(card)
