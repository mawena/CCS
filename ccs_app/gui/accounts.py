"""Onglet Comptes : meilleur compte, capacité, cartes avec prévisions."""

import shutil
import time

from gi.repository import Adw, Gio, GLib, Gtk

from .. import core, daemon, pause
from ..forecast import weekly_forecast_text
from .charts import Sparkline
from .common import (account_rgb, ask_name, bar_for, big_number, caption, card_box, clear, empty_state,
                     now_utc, parse_ts, run_ccs_async, sync_accounts)

DAY_S = 86400


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


def pause_box(window, now, offer=True):
    """Ligne « en pause jusqu'à … · Reprendre », ou bouton « Mettre en pause » (si `offer`)."""
    st = pause.pause_state(now)
    if st is None and not offer:
        return None
    row = Gtk.Box(spacing=12)
    if st is not None:
        row.append(Gtk.Label(label=f"⏸ Bascule automatique et orchestrateur en pause "
                                   f"{pause.label(st, now)}",
                             xalign=0, hexpand=True, wrap=True, css_classes=["warning"]))
        resume = Gtk.Button(label="Reprendre", css_classes=["pill"], valign=Gtk.Align.CENTER)
        resume.connect("clicked", lambda *_: set_pause(window, "reprendre"))
        row.append(resume)
        return row
    row.append(caption("Garder la main un moment : suspend la bascule automatique et "
                       "l'orchestrateur, sans changer les réglages."))
    row.get_last_child().set_hexpand(True)
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
    row.append(Gtk.MenuButton(label="Mettre en pause", popover=popover, valign=Gtk.Align.CENTER,
                              tooltip_text="Suspend la bascule automatique et l'orchestrateur"))
    return row


class AccountsPage(Gtk.ScrolledWindow):
    def __init__(self, window):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.window = window
        self.banner = Adw.Banner(button_label="Enregistrer")
        self.banner.connect("button-clicked", lambda *_: ask_name(
            window, "Enregistrer le compte connecté", "Nom du profil…", "Enregistrer",
            lambda n: run_ccs_async(window, ["save", n])))
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                            margin_top=18, margin_bottom=18, margin_start=12, margin_end=12)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(self.banner)
        body.append(Adw.Clamp(maximum_size=680, child=self.list))
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
        for a in accounts:
            self.list.append(self.card(a, store, now))

    def summary_card(self, state):
        best = state.get("best")
        card = card_box(6, account=best["name"] if best else None)
        row = Gtk.Box(spacing=12)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        if best:
            text.append(Gtk.Label(label=f"Meilleur compte maintenant : {best['name']}",
                                  xalign=0, css_classes=["heading"]))
            text.append(caption(best["reason"]))
        else:
            text.append(Gtk.Label(label="Aucun compte disponible pour l'instant",
                                  xalign=0, css_classes=["heading"]))
        cap = state.get("capacity") or 0
        text.append(caption(f"Capacité restante : {core.fr(cap)} session{'s' if cap >= 2 else ''} "
                            f"complète{'s' if cap >= 2 else ''} tous comptes confondus"))
        decision = (state.get("auto_switch") or {}).get("decision") or {}
        if decision.get("action") == "exhausted":
            text.append(caption(f"⚠ {decision['reason']}", error=True))
        cap_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER,
                          tooltip_text="Sessions complètes encore disponibles, tous comptes confondus")
        cap_box.append(big_number(core.fr(cap)))
        cap_box.append(caption("sessions" if cap >= 2 else "session"))
        row.append(cap_box)
        row.append(text)
        if not daemon.state_fresh(state):
            text.append(caption(f"⚠ Données anciennes ({core.fmt_time(state.get('updated_at'))}) — "
                                "actualise avant de choisir un compte", error=True))
        elif best and best["name"] != state.get("active"):
            use = Gtk.Button(label="Utiliser", css_classes=["suggested-action", "pill"],
                             valign=Gtk.Align.CENTER)
            use.connect("clicked", lambda *_: self.window.switch(best["name"]))
            row.append(use)
        card.append(row)
        card.append(pause_box(self.window, now_utc()))
        return card

    def card(self, a, store, now):
        card = card_box(12, account=a["name"])
        top = Gtk.Box(spacing=10)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        title = Gtk.Box(spacing=8)
        title.append(Gtk.Label(label=a["name"], css_classes=["title-3"], xalign=0))
        title.append(Gtk.Label(label=(a.get("plan") or "?").upper(), css_classes=["badge", "plan"],
                               valign=Gtk.Align.CENTER))
        if a["active"]:
            title.append(Gtk.Label(label="ACTIF", css_classes=["badge", "active"],
                                   valign=Gtk.Align.CENTER))
        info.append(title)
        sub = a.get("email", "") + (f"  ·  {a['org']}" if a.get("org") else "")
        info.append(Gtk.Label(label=sub, css_classes=["dim-label", "caption"], xalign=0, ellipsize=3))
        top.append(info)
        if not a["active"]:
            use = Gtk.Button(label="Utiliser", css_classes=["pill"], valign=Gtk.Align.CENTER)
            use.connect("clicked", lambda *_: self.window.switch(a["name"]))
            top.append(use)
        menu = Gio.Menu()
        menu.append("Renommer…", f"win.rename::{a['name']}")
        menu.append("Supprimer…", f"win.delete::{a['name']}")
        top.append(Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu,
                                  css_classes=["flat"], valign=Gtk.Align.CENTER))
        card.append(top)

        for lim in a.get("limits") or []:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            head = Gtk.Box()
            head.append(Gtk.Label(label=lim["label"], hexpand=True, xalign=0))
            head.append(Gtk.Label(label=f"{lim['percent']:.0f} %",
                                  css_classes=["ccs-big-number", "small"]))
            row.append(head)
            row.append(bar_for(lim["percent"]))
            reset = parse_ts(lim.get("resets_at"))
            if reset:
                row.append(caption(core.fmt_reset(reset, now)))
            card.append(row)

        for text in (forecast_text(a.get("forecast"), now), pace_text(a.get("pace"))):
            if text:
                card.append(Gtk.Label(label=text, xalign=0, wrap=True))
        week = weekly_forecast_text(a.get("weekly_forecast"), now)
        if week:
            label = Gtk.Label(label=week, xalign=0, wrap=True)
            if (a.get("weekly_forecast") or {}).get("verdict") == "limit":
                label.add_css_class("warning")
            card.append(label)

        t1 = time.time()
        samples = [(ts, p) for ts, p, _ in store.samples(a["name"], "session", t1 - DAY_S)]
        if len(samples) >= 2:
            spark = Sparkline()
            spark.set_data(t1 - DAY_S, t1, samples, rgb=account_rgb(a["name"]))
            card.append(caption("Session sur 24 h"))
            card.append(spark)

        if a.get("error"):
            stale = f" — données de {core.fmt_time(a['fetched_at'])}" if a.get("limits") else ""
            card.append(caption(f"⚠ {a['error']}{stale}", error=True))
        elif a.get("fetched_at"):
            card.append(caption(f"Mis à jour à {core.fmt_time(a['fetched_at'])}"))
        return card


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
