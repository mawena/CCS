"""Cartes de conseils de l'onglet Analyse : bilan de la semaine et conseiller de formule
(calculs dans un fil)."""

from gi.repository import Gtk

from .. import advisor, costs, daemon, weekly_report
from .common import caption, clear, in_thread, load_state, now_utc


def _card(title):
    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["card", "profile-card"])
    head = Gtk.Box(spacing=6)
    head.append(Gtk.Label(label=title, xalign=0, hexpand=True, css_classes=["heading"]))
    card.append(head)
    return card, head


def _figure(value, label):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
    box.append(Gtk.Label(label=value, xalign=0, wrap=True, css_classes=["title-4"]))
    box.append(Gtk.Label(label=label, xalign=0, wrap=True, css_classes=["caption", "dim-label"]))
    return box


def _spinner():
    return Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER, width_request=24, height_request=24)


class AdvisorCard(Gtk.Box):
    """« Conseiller de formule » : formule conseillée, prix, équivalent API, raisonnement."""

    def __init__(self, compute=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.compute = compute or advisor.compute
        self.loading = False
        card, head = _card("Conseiller de formule")
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", css_classes=["flat"],
                             tooltip_text="Recalculer", valign=Gtk.Align.CENTER)
        refresh.connect("clicked", lambda _b: self.load())
        head.append(refresh)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.append(self.body)
        self.append(card)

    def load(self):
        if self.loading:
            return
        self.loading = True
        clear(self.body)
        self.body.append(_spinner())
        self.body.append(caption("Lecture des relevés et des journaux des dernières semaines…"))

        def work():
            try:
                return self.compute(), None
            except Exception as e:  # noqa: BLE001 — affiché dans la carte, jamais une fenêtre figée
                return None, str(e) or e.__class__.__name__
        in_thread(work, self.show)

    def show(self, result):
        self.loading = False
        advice, error = result
        clear(self.body)
        if error:
            self.body.append(caption(f"Calcul impossible : {error}", error=True))
            return
        self.body.append(Gtk.Label(label=advice.summary, xalign=0, wrap=True, css_classes=["title-3"]))
        figures = Gtk.Box(spacing=12, homogeneous=True)
        if advice.current is not None:
            figures.append(_figure(f"{advisor.money(advice.current.price)}/mois",
                                   f"payés aujourd'hui ({advice.current.label})"))
        if advice.recommended is not None:
            figures.append(_figure(f"{advisor.money(advice.recommended.price)}/mois",
                                   f"conseillés ({advice.recommended.label})"))
        if advice.api is not None and advice.api.reponses and advice.api_monthly is not None:
            sign = "≥" if advice.api.inconnu else "≈"
            figures.append(_figure(f"{sign} {costs.format_dollars(advice.api_monthly)}/mois",
                                   "au tarif de l'API (Claude Code, ce PC)"))
        if figures.get_first_child() is not None:
            self.body.append(figures)
        reasons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=4)
        for text in advice.reasons:
            reasons.append(Gtk.Label(label=f"• {text}", xalign=0, wrap=True, selectable=True))
        self.body.append(Gtk.Expander(label="Raisonnement", expanded=True, child=reasons))
        if advice.prices_stale:
            self.body.append(caption("Tarifs des formules à vérifier : ils datent de plus de "
                                     f"{advisor.PLAN_PRICES_MAX_AGE_DAYS} jours.", error=True))


def week_label(index, start, end):
    if index == 0:
        return f"Semaine en cours (depuis le {weekly_report._date(start)})"
    return f"Du {weekly_report._date(start)} au {weekly_report._date(end)}"


class WeeklyReportCard(Gtk.Box):
    """« Bilan de la semaine » avec choix de la semaine (la dernière terminée par défaut)."""

    def __init__(self, build=None, choices=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.build = build or weekly_report.build_report
        self.choices = choices or self._choices
        self.weeks = []
        self.generation = 0
        self.then = None
        card, head = _card("Bilan de la semaine")
        self.dropdown = Gtk.DropDown(model=Gtk.StringList(), valign=Gtk.Align.CENTER,
                                     tooltip_text="Semaine")
        self.filling = False
        self.dropdown.connect("notify::selected", lambda *_: self.on_selected())
        head.append(self.dropdown)
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", css_classes=["flat"],
                             tooltip_text="Recalculer", valign=Gtk.Align.CENTER)
        refresh.connect("clicked", lambda _b: self.load())
        head.append(refresh)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.append(self.body)
        self.append(card)

    @staticmethod
    def _choices():
        from ..settings import load_settings
        accounts = daemon.states_from_state(load_state())
        return weekly_report.week_choices(accounts, now_utc(), load_settings())

    def load(self, then=None):
        """`then()` est appelé une fois le bilan affiché (le conseiller profite ainsi des
        journaux déjà lus au lieu de les lire en même temps)."""
        self.then = then
        try:
            self.weeks = self.choices()
        except Exception as e:  # noqa: BLE001 — état ou réglages illisibles : message dans la carte
            clear(self.body)
            self.body.append(caption(f"Semaines introuvables : {e}", error=True))
            self._done()
            return
        model = Gtk.StringList()
        for i, (start, end) in enumerate(self.weeks):
            model.append(week_label(i, start, end))
        # Changer de modèle sélectionne la première semaine : pas de calcul pour elle.
        self.filling = True
        try:
            self.dropdown.set_model(model)
            self.dropdown.set_selected(1 if len(self.weeks) > 1 else 0)
        finally:
            self.filling = False
        self.show_week()

    def on_selected(self):
        if not self.filling:
            self.show_week()

    def show_week(self):
        index = self.dropdown.get_selected()
        if not 0 <= index < len(self.weeks):
            return
        start, end = self.weeks[index]
        self.generation += 1
        generation = self.generation
        clear(self.body)
        self.body.append(_spinner())

        def work():
            try:
                return self.build(start, end), None
            except Exception as e:  # noqa: BLE001
                return None, str(e) or e.__class__.__name__
        in_thread(work, lambda result: self.show(result, generation))

    def show(self, result, generation=None):
        if generation is not None and generation != self.generation:
            return  # une autre semaine a été choisie entre-temps
        report, error = result
        clear(self.body)
        if error:
            self.body.append(caption(f"Bilan impossible : {error}", error=True))
        else:
            for head, rows in weekly_report.sections(report):
                self.body.append(Gtk.Label(label=head, xalign=0, margin_top=6,
                                           css_classes=["caption-heading", "dim-label"]))
                for row in rows:
                    self.body.append(Gtk.Label(label=f"• {row}", xalign=0, wrap=True,
                                               selectable=True))
        self._done()

    def _done(self):
        then, self.then = getattr(self, "then", None), None
        if then is not None:
            then()
