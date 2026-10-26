"""Onglet Analyse : où part l'usage (journaux locaux) et conseils."""

import time

from gi.repository import Adw, Gtk

from .. import core, transcripts
from .charts import HourBars
from .common import caption, clear, in_thread


class AnalysisPage(Gtk.ScrolledWindow):
    def __init__(self, window):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.window = window
        self.days = 7
        self.loaded = False
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                        margin_top=18, margin_bottom=18, margin_start=12, margin_end=12)
        toggles = Gtk.Box(css_classes=["linked"], halign=Gtk.Align.CENTER)
        first = None
        for days in (7, 30):
            b = Gtk.ToggleButton(label=f"{days} jours", active=first is None)
            if first:
                b.set_group(first)
            first = first or b
            b.connect("toggled", self.on_days, days)
            toggles.append(b)
        outer.append(toggles)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        outer.append(self.body)
        self.set_child(Adw.Clamp(maximum_size=760, child=outer))

    def on_days(self, button, days):
        if button.get_active():
            self.days = days
            self.load()

    def ensure_loaded(self):
        if not self.loaded:
            self.load()

    def load(self):
        self.loaded = True
        clear(self.body)
        self.body.append(Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER,
                                     width_request=32, height_request=32))
        days = self.days

        def work():
            from ..store import Store
            since = time.time() - days * 86400
            rows = transcripts.scan(core.paths().config_dir / "projects", since)
            periods = Store().active_periods(since, time.time())
            return transcripts.aggregate(rows, periods, days), len(rows)
        in_thread(work, self.show)

    def section(self, title, data, total):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                       css_classes=["card", "profile-card"])
        card.append(Gtk.Label(label=title, xalign=0, css_classes=["heading"]))
        for name, v in sorted(data.items(), key=lambda kv: -kv[1])[:8]:
            pct = 100 * v / total
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            head = Gtk.Box()
            head.append(Gtk.Label(label=name, xalign=0, hexpand=True, ellipsize=3))
            head.append(Gtk.Label(label=f"{pct:.0f} %  ·  {transcripts.fmt_tokens(v)}",
                                  css_classes=["pct", "dim-label"]))
            row.append(head)
            bar = Gtk.ProgressBar(fraction=pct / 100, css_classes=["ok"])
            row.append(bar)
            card.append(row)
        return card

    def show(self, result):
        report, count = result
        clear(self.body)
        if not count:
            self.body.append(Adw.StatusPage(icon_name="edit-find-symbolic",
                                            title=f"Aucune activité sur {self.days} jours"))
            return
        self.body.append(Gtk.Label(
            label=f"{transcripts.fmt_tokens(report.total)} tokens pondérés · {count} réponses",
            css_classes=["title-4"]))
        tips = transcripts.advice(report)
        if tips:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                           css_classes=["card", "profile-card"])
            card.append(Gtk.Label(label="Conseils", xalign=0, css_classes=["heading"]))
            for t in tips:
                card.append(Gtk.Label(label=f"• {t}", xalign=0, wrap=True))
            self.body.append(card)
        self.body.append(self.section("Par projet", report.by_project, report.total))
        self.body.append(self.section("Par modèle", report.by_model, report.total))
        hours = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                        css_classes=["card", "profile-card"])
        hours.append(Gtk.Label(label="Par heure", xalign=0, css_classes=["heading"]))
        bars = HourBars()
        bars.set_data(report.by_hour)
        hours.append(bars)
        self.body.append(hours)
        self.body.append(self.section("Par compte", report.by_account, report.total))
        self.body.append(caption("Tokens pondérés : entrée + écriture cache + sortie × 5 + "
                                 "lecture cache × 0,1. L'attribution aux comptes commence avec "
                                 "le service de collecte (« inconnu » avant)."))
