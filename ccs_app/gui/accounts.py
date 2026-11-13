"""Onglet Comptes : meilleur compte, capacité, cartes avec prévisions."""

import json
import re
import shutil
import time

from gi.repository import Adw, Gio, GLib, Gtk

from .. import core, daemon, pause
from ..forecast import weekly_forecast_text
from .charts import Sparkline
from .common import (PAGE_WIDTH, account_rgb, ask_name, bar_for, big_number, caption, card_box, clear,
                     empty_state, now_utc, parse_ts, run_ccs_async, sync_accounts, tag_account)

DAY_S = 86400
CARD_MIN_W = 300            # largeur minimale d'une carte : 3 par ligne dans une fenêtre large
MAIN_KINDS = ("session", "weekly_all")   # jauges toujours visibles ; les autres sont dans « Détails »
PAUSE_TIP = ("Garder la main un moment : suspend la bascule automatique et l'orchestrateur, "
             "sans changer les réglages.")


def forecast_text(fc, now):
    if not fc or fc.get("verdict") in (None, "unknown"):
        return None
    rate = fc.get("rate_per_min") or 0
    if fc["verdict"] == "limit":
        eta = parse_ts(fc.get("eta"))
        mins = fc.get("minutes_before_reset")
        tail = f", {mins:.0f} min avant la réinitialisation" if mins else ""
        return f"⏱ Limite estimée vers {eta.astimezone():%H:%M}{tail}" if eta else None
    if fc["verdict"] == "ok":
        return f"✓ Tient jusqu'à la réinitialisation au rythme actuel ({rate * 60:.0f} %/h)"
    return "Usage stable en ce moment"


def pace_text(pace):
    if not pace:
        return None
    margin = pace["margin"]
    days = pace["days_left"]
    head = (f"Semaine : {margin:.0f} pts de marge sur le rythme" if margin >= 0
            else f"Semaine : {-margin:.0f} pts d'avance sur le rythme")
    return f"{head} · budget {pace['per_day_budget']:.0f} %/jour ({core.fr(days)} j restants)"


def set_pause(window, choice):
    """Pose ou lève la pause, réveille le service et rafraîchit l'affichage."""
    st = pause.apply(choice)
    daemon.request_refresh()
    window.toast("Pause levée : la bascule automatique et l'orchestrateur reprennent" if st is None
                 else f"Bascule automatique et orchestrateur en pause {pause.label(st, now_utc())}")
    GLib.idle_add(lambda: (window.reload(), False)[1])


def pause_button(window, now):
    """Bouton « Pause » (menu des durées) ; l'explication est dans l'info-bulle."""
    popover = Gtk.Popover()
    items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    for choice, text in pause.choices(now):
        b = Gtk.Button(label=text, css_classes=["flat"])
        b.get_child().set_xalign(0)

        def clicked(_b, c=choice):
            popover.popdown()
            set_pause(window, c)
        b.connect("clicked", clicked)
        items.append(b)
    popover.set_child(items)
    return Gtk.MenuButton(child=Adw.ButtonContent(icon_name="media-playback-pause-symbolic", label="Pause"),
                          popover=popover, valign=Gtk.Align.CENTER, css_classes=["flat"],
                          tooltip_text=PAUSE_TIP)


def pause_box(window, now, offer=True):
    """Ligne « en pause jusqu'à … · Reprendre » ; sans pause, le bouton « Pause » (si `offer`)."""
    st = pause.pause_state(now)
    if st is None:
        return pause_button(window, now) if offer else None
    row = Gtk.Box(spacing=12)
    row.append(Gtk.Label(label=f"⏸ Bascule automatique et orchestrateur en pause "
                               f"{pause.label(st, now)}",
                         xalign=0, hexpand=True, wrap=True, css_classes=["warning"]))
    resume = Gtk.Button(label="Reprendre", css_classes=["pill"], valign=Gtk.Align.CENTER)
    resume.connect("clicked", lambda *_: set_pause(window, "reprendre"))
    row.append(resume)
    return row


ERROR_MAX = 160
_HTTP_RE = re.compile(r"^HTTP (\d{3})\s*:?\s*(.*)$", re.S)


def friendly_error(raw):
    """Erreur d'usage d'un compte dite en clair (jamais le JSON brut de l'API) ; le texte
    d'origine reste en info-bulle."""
    text = " ".join(str(raw or "").split())
    m = _HTTP_RE.match(text)
    if m:
        code, rest = int(m.group(1)), m.group(2)
        if code == 401 or "authentication_error" in rest:
            return "Connexion refusée par Anthropic : reconnecte ce compte (menu ⋮ du compte)."
        if code == 403:
            return "Accès refusé par Anthropic pour ce compte."
        if code == 429:
            return "Trop de demandes à Anthropic pour l'instant : nouvel essai automatique plus tard."
        if code >= 500:
            return f"Anthropic ne répond pas (erreur {code}) : nouvel essai automatique plus tard."
        message = None
        try:
            data = json.loads(rest)
            err = data.get("error") if isinstance(data, dict) else None
            message = (err or {}).get("message") if isinstance(err, dict) else None
        except ValueError:
            pass
        text = f"Erreur {code} : {message}" if message else f"Erreur {code} de l'API d'Anthropic."
    return text if len(text) <= ERROR_MAX else text[:ERROR_MAX - 1].rstrip() + "…"


def status_of(a, now):
    """(texte, classe) : la chose la plus importante à savoir sur un compte, en une ligne ;
    None s'il n'y a rien à signaler. Ordre : erreur, limite de session proche, limite de la
    semaine prévue, puis « tient »."""
    if a.get("error"):
        stale = f" (données de {core.fmt_time(a['fetched_at'])})" if a.get("limits") else ""
        return f"⚠ {friendly_error(a['error'])}{stale}", "error"
    fc = a.get("forecast") or {}
    wf = a.get("weekly_forecast") or {}
    if fc.get("verdict") == "limit" and (text := forecast_text(fc, now)):
        return text, "warning"
    if wf.get("verdict") == "limit" and (text := weekly_forecast_text(wf, now)):
        return text, "warning"
    if fc.get("verdict") == "ok" and (text := forecast_text(fc, now)):
        return text, "success"
    return None


def gauge(lim, now):
    """Jauge d'une limite : nom et pourcentage, barre, moment de la recharge."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    head = Gtk.Box(spacing=8)
    head.append(Gtk.Label(label=lim["label"], hexpand=True, xalign=0, ellipsize=3,
                          css_classes=["ccs-gauge-label"]))
    head.append(Gtk.Label(label=f"{lim['percent']:.0f} %", css_classes=["ccs-big-number", "small"]))
    box.append(head)
    box.append(bar_for(lim["percent"]))
    reset = parse_ts(lim.get("resets_at"))
    if reset:
        box.append(caption(core.fmt_reset(reset, now)))
    return box


def narrow_labels(widget, chars=16):
    """Borne la largeur « naturelle » des libellés qui passent à la ligne ou s'abrègent : la
    grille (Gtk.FlowBox) compte ses colonnes sur cette largeur ; sans borne, une longue phrase
    met chaque carte seule sur sa ligne. Les libellés gardent toute la largeur allouée."""
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Label) and (child.get_wrap() or child.get_ellipsize() != 0):
            child.set_max_width_chars(chars)
        narrow_labels(child, chars)
        child = child.get_next_sibling()


class AccountsPage(Gtk.ScrolledWindow):
    def __init__(self, window):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.window = window
        self.expanded = set()          # comptes dont les détails sont ouverts (gardé d'un rendu à l'autre)
        self.banner = Adw.Banner(button_label="Enregistrer")
        self.banner.connect("button-clicked", lambda *_: ask_name(
            window, "Enregistrer le compte connecté", "Nom du profil…", "Enregistrer",
            lambda n: run_ccs_async(window, ["save", n])))
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                            margin_top=10, margin_bottom=6, margin_start=12, margin_end=12)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(self.banner)
        body.append(Adw.Clamp(maximum_size=PAGE_WIDTH, tightening_threshold=PAGE_WIDTH, child=self.list))
        self.set_child(body)

    # ---- rendu ---------------------------------------------------------------

    def render(self, state, store):
        clear(self.list)
        now = now_utc()
        acc = core.live_account()
        accounts = state.get("accounts") or []
        unsaved = core.live_logged_in() and acc and not any(a["active"] for a in accounts)
        self.banner.set_title(
            f"Le compte connecté ({acc.get('emailAddress')}) n'est enregistré dans aucun profil"
            if unsaved else "")
        self.banner.set_revealed(bool(unsaved))

        sync_accounts(a["name"] for a in accounts)
        if not accounts:
            save = None
            if core.live_logged_in() and acc:
                def save():
                    ask_name(self.window, "Enregistrer le compte connecté", "Nom du profil…",
                             "Enregistrer", lambda n: run_ccs_async(self.window, ["save", n]))
            page = empty_state("system-users-symbolic", "Aucun profil",
                               "Enregistre le compte connecté, puis ajoute tes autres comptes avec +.",
                               "Enregistrer le compte connecté", save)
            page.set_vexpand(True)
            self.list.append(page)
            return
        self.list.append(self.summary_card(state))
        # Les comptes côte à côte (jusqu'à 3 par ligne) : on les compare d'un coup d'œil.
        self.grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                column_spacing=14, row_spacing=14, min_children_per_line=1,
                                max_children_per_line=min(3, len(accounts)),
                                activate_on_single_click=False, css_classes=["ccs-accounts-grid"])
        for a in accounts:
            card = self.card(a, store, now)
            narrow_labels(card)
            self.grid.append(card)
            self.grid.get_last_child().set_focusable(False)
        self.list.append(self.grid)

    def summary_card(self, state):
        """En bref : sessions encore disponibles, meilleur compte (et « Utiliser »), pause."""
        best = state.get("best")
        card = card_box(8, account=best["name"] if best else None)
        row = Gtk.Box(spacing=14)
        cap = state.get("capacity") or 0
        cap_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER,
                          tooltip_text="Sessions complètes de 5 h encore disponibles, tous comptes confondus")
        cap_box.append(big_number(core.fr(cap)))
        cap_box.append(caption("sessions dispo." if cap >= 2 else "session dispo."))
        row.append(cap_box)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
        if best:
            # Un seul libellé qui passe à la ligne (fenêtre étroite), nom à la couleur du compte.
            r, g, b = (round(v * 255) for v in account_rgb(best["name"]))
            name = GLib.markup_escape_text(best["name"])
            text.append(Gtk.Label(label=f'Meilleur compte maintenant : <span foreground="#{r:02x}{g:02x}{b:02x}">'
                                        f'{name}</span>', use_markup=True, xalign=0, wrap=True,
                                  css_classes=["heading"]))
            text.append(caption(best["reason"]))
        else:
            text.append(Gtk.Label(label="Aucun compte disponible pour l'instant", xalign=0, wrap=True,
                                  css_classes=["heading"]))
        decision = (state.get("auto_switch") or {}).get("decision") or {}
        if decision.get("action") == "exhausted":
            text.append(caption(f"⚠ {decision['reason']}", error=True))
        row.append(text)
        if not daemon.state_fresh(state):
            text.append(caption(f"⚠ Données anciennes ({core.fmt_time(state.get('updated_at'))}) — "
                                "actualise avant de choisir un compte", error=True))
        elif best and best["name"] != state.get("active"):
            use = Gtk.Button(label=f"Utiliser {best['name']}", css_classes=["suggested-action", "pill"],
                             valign=Gtk.Align.CENTER)
            use.connect("clicked", lambda *_: self.window.switch(best["name"]))
            row.append(use)
        paused = pause_box(self.window, now_utc())
        if isinstance(paused, Gtk.MenuButton):
            row.append(paused)
            card.append(row)
        else:
            card.append(row)
            card.append(paused)
        return card

    def card(self, a, store, now):
        """Carte compacte : nom, deux jauges (session, semaine), une ligne d'état ; le reste
        (autres limites, rythme, courbe 24 h, heure du relevé) dans « Détails »."""
        name = a["name"]
        card = card_box(10, account=name)
        card.set_size_request(CARD_MIN_W, -1)
        top = Gtk.Box(spacing=8)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        title = Gtk.Box(spacing=6)
        title.append(tag_account(Gtk.Label(label=name, css_classes=["title-3"], xalign=0, ellipsize=3,
                                           tooltip_text=name), name))
        title.append(Gtk.Label(label=(a.get("plan") or "?").upper(), css_classes=["badge", "plan"],
                               valign=Gtk.Align.CENTER))
        if a["active"]:
            title.append(Gtk.Label(label="ACTIF", css_classes=["badge", "active"], valign=Gtk.Align.CENTER))
        info.append(title)
        sub = a.get("email", "") + (f"  ·  {a['org']}" if a.get("org") else "")
        info.append(Gtk.Label(label=sub, css_classes=["dim-label", "caption"], xalign=0, ellipsize=3,
                              tooltip_text=sub))
        top.append(info)
        if not a["active"]:
            use = Gtk.Button(label="Utiliser", valign=Gtk.Align.CENTER,
                             tooltip_text=f"Basculer sur le compte {name}")
            use.connect("clicked", lambda *_: self.window.switch(name))
            top.append(use)
        menu = Gio.Menu()
        menu.append("Renommer…", f"win.rename::{name}")
        menu.append("Supprimer…", f"win.delete::{name}")
        top.append(Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu,
                                  css_classes=["flat"], valign=Gtk.Align.CENTER))
        card.append(top)

        limits = a.get("limits") or []
        main = [lim for lim in limits if lim["kind"] in MAIN_KINDS] or limits[:2]
        for lim in main:
            card.append(gauge(lim, now))
        if not limits and not a.get("error"):
            card.append(caption("Pas encore de relevé pour ce compte."))
        status = status_of(a, now)
        if status:
            label = Gtk.Label(label=status[0], xalign=0, wrap=True, css_classes=[status[1]])
            if a.get("error"):
                label.set_tooltip_text(str(a["error"]))
            card.append(label)
        details = self.details(a, [lim for lim in limits if lim not in main], store, now, status)
        if details is not None:
            exp = Gtk.Expander(label="Détails", expanded=name in self.expanded, child=details,
                               css_classes=["ccs-details"])
            exp.connect("notify::expanded", lambda e, _p: (self.expanded.add(name) if e.get_expanded()
                                                           else self.expanded.discard(name)))
            card.append(exp)
        return card

    def details(self, a, others, store, now, status):
        """Contenu de « Détails » : autres limites, prévisions et rythme, courbe 24 h, relevé."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=6)
        for lim in others:
            box.append(gauge(lim, now))
        shown = status[0] if status else None
        for text in (forecast_text(a.get("forecast"), now), pace_text(a.get("pace")),
                     weekly_forecast_text(a.get("weekly_forecast"), now)):
            if text and text != shown:
                box.append(Gtk.Label(label=text, xalign=0, wrap=True, css_classes=["caption"]))
        t1 = time.time()
        samples = [(ts, p) for ts, p, _ in store.samples(a["name"], "session", t1 - DAY_S)]
        if len(samples) >= 2:
            spark = Sparkline()
            spark.set_data(t1 - DAY_S, t1, samples, rgb=account_rgb(a["name"]))
            box.append(caption("Session sur 24 h"))
            box.append(spark)
        if a.get("fetched_at") and not a.get("error"):
            box.append(caption(f"Relevé à {core.fmt_time(a['fetched_at'])}"))
        return box if box.get_first_child() is not None else None


def add_account(window, name):
    term = shutil.which("gnome-terminal")
    if not term:
        window.toast(f"Lance « ccs add {name} » dans un terminal")
        return
    script = (f"{GLib.shell_quote(core.ccs_bin())} add {GLib.shell_quote(name)}; echo; "
              'read -rp "Appuie sur Entrée pour fermer…"')
    proc = Gio.Subprocess.new([term, "--wait", "--title", "Ajouter un compte Claude",
                               "--", "bash", "-c", script], Gio.SubprocessFlags.NONE)
    proc.wait_async(None, lambda *_: window.refresh())
