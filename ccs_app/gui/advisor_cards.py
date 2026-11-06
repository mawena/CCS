"""Cartes de conseils de l'onglet Analyse : conseiller de formule (calcul dans un fil)."""

from gi.repository import Gtk

from .. import advisor, costs
from .common import caption, clear, in_thread


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
