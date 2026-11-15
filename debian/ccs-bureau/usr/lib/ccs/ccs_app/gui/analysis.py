"""Onglet Analyse : où part l'usage (journaux locaux) et conseils."""

import time

from gi.repository import Adw, Gtk

from .. import core, transcripts
from .advisor_cards import AdvisorCard, MonthlyReportCard, WeeklyReportCard
from .budget_view import BudgetGroup
from .charts import HourBars
from .common import (account_rgb, big_number, caption, card_box, clear, empty_state, in_thread,
                     sync_accounts, tag_account)


class AnalysisPage(Gtk.ScrolledWindow):
    def __init__(self, window):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.window = window
        self.days = 7
        self.loaded = False
        self.profiles = set()
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                        margin_top=18, margin_bottom=18, margin_start=12, margin_end=12)
        # Conseils calculés sur leurs propres périodes (relevés et journaux), dans un fil.
        self.weekly = WeeklyReportCard()
        outer.append(self.weekly)
        self.advisor = AdvisorCard()
        outer.append(self.advisor)
        self.monthly = MonthlyReportCard()
        outer.append(self.monthly)
        # Budgets par projet : calculés dans un fil par le groupe lui-même.
        self.budgets = BudgetGroup(toast=window.toast, parent=window)
        outer.append(self.budgets)
        toggles = Gtk.Box(css_classes=["linked"], halign=Gtk.Align.CENTER)
        first = None
        self.days_buttons = {}
        for days in (7, 30):
            b = Gtk.ToggleButton(label=f"{days} jours", active=first is None)
            self.days_buttons[days] = b
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
        self.budgets.refresh()
        if not self.loaded:
            self.load()
            # Lectures en chaîne : chaque carte profite des journaux déjà en cache.
            self.weekly.load(then=lambda: self.advisor.load(then=self.monthly.load))

    def load(self):
        self.loaded = True
        clear(self.body)
        self.body.append(Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER,
                                     width_request=32, height_request=32))
        days = self.days

        self.profiles = {p.name for p in core.list_profiles()}
        sync_accounts(self.profiles)

        def work():
            from ..store import Store
            since = time.time() - days * 86400
            rows = transcripts.scan(core.paths().config_dir / "projects", since)
            periods = Store().active_periods(since, time.time())
            return transcripts.aggregate(rows, periods, days), len(rows)
        in_thread(work, self.show)

    def section(self, title, data, total, accounts=False):
        card = card_box(8)
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
            if accounts and name in self.profiles:
                tag_account(row, name)      # la barre prend la couleur du compte
            row.append(bar)
            card.append(row)
        return card

    def show(self, result):
        report, count = result
        clear(self.body)
        if not count:
            longer = (lambda: self.days_buttons[30].set_active(True)) if self.days < 30 else None
            self.body.append(empty_state("edit-find-symbolic", f"Aucune activité sur {self.days} jours",
                                         "Les journaux de Claude Code de cette période sont vides.",
                                         "Voir 30 jours", longer))
            return
        head = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        head.append(big_number(transcripts.fmt_tokens(report.total)))
        head.append(Gtk.Label(label=f"tokens pondérés · {count} réponses", valign=Gtk.Align.END,
                              css_classes=["title-4"], margin_bottom=6))
        self.body.append(head)
        tips = transcripts.advice(report)
        if tips:
            card = card_box(8)
            card.append(Gtk.Label(label="Conseils", xalign=0, css_classes=["heading"]))
            for t in tips:
                card.append(Gtk.Label(label=f"• {t}", xalign=0, wrap=True))
            self.body.append(card)
        self.body.append(self.section("Par projet", report.by_project, report.total))
        self.body.append(self.section("Par modèle", report.by_model, report.total))
        hours = card_box(8)
        hours.append(Gtk.Label(label="Par heure", xalign=0, css_classes=["heading"]))
        bars = HourBars()
        bars.set_data(report.by_hour)
        hours.append(bars)
        self.body.append(hours)
        self.body.append(self.section("Par compte", report.by_account, report.total, accounts=True))
        self.body.append(caption("Tokens pondérés : entrée + écriture cache + sortie × 5 + "
                                 "lecture cache × 0,1. L'attribution aux comptes commence avec "
                                 "le service de collecte (« inconnu » avant)."))
