"""« Ouvertes maintenant » (onglet Sessions) : une carte par session Claude Code ouverte du
projet choisi (ou de tous) — état, consommation et coût de la conversation, onglet du
terminal intégré, terminal ici, dossier, aperçu, renommage, terminer.

Les entrées des menus « ⋮ » passent par les actions « sess.* » de la page
(sess.preview((dossier, conversation)), sess.shell('dossier'), sess.rename((dossier,
conversation))).

Mémoire (facultatif) : avec `memory` ({pid: session_memory.SessionMemory}), chaque carte montre sa
RAM et son inactivité, l'en-tête la RAM totale et un bandeau « N sessions inactives occupent X Go » ;
avec `on_close(session)` en plus, les sessions inactives ont un bouton « Fermer » (confirmation,
la conversation reste reprenable). Avec `contexts` ({pid: context_alert.Context}), un badge signale
le contexte lourd (au-delà de `heavy_tokens`, ou du seuil par défaut)."""

import os
import time

from gi.repository import Adw, GLib, Gtk, Pango

from .. import context_alert, core, costs, session_memory, sessions, transcripts
from ..session_hub import plural
from .common import caption, clear, menu_button

STATE_CLASSES = {"busy": "warning", "waiting": "accent", "idle": "dim-label"}


def duration(seconds):
    minutes = int(seconds // 60)
    return f"{minutes // 60} h {minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"


def pair(a, b=""):
    return GLib.Variant("(ss)", (a or "", b or ""))


def stamp(path):
    """Empreinte d'un journal (taille, date) : son coût n'est recalculé que s'il change."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


class SessionCards(Gtk.Box):
    def __init__(self, window, on_changed):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10, visible=False)
        self.window = window
        self.on_changed = on_changed     # relecture des sessions (après « Terminer »)
        self.menus = []
        self.memory, self.contexts, self.on_close = {}, {}, None
        self.heavy_tokens = context_alert.DEFAULTS["threshold_tokens"]
        self.cost_loader = costs.Loader()
        self.known_costs = {}            # journal -> (empreinte, Cost) : affichés sans attendre
        self.cost_labels = {}            # journal -> [(libellé, texte sans le coût)]

    def busy(self):
        """Un menu « ⋮ » est ouvert : ne pas redessiner sous la souris."""
        return any(m.get_active() for m in self.menus)

    def render(self, found, usage, titles, stamps, show_project, target=None, compact=False,
               memory=None, contexts=None, on_close=None, heavy_tokens=None):
        """Cartes des sessions `found` ; renvoie celle de `target` (mise en évidence) ou None."""
        self.memory = memory or {}
        self.contexts = contexts or {}
        self.on_close = on_close
        self.heavy_tokens = heavy_tokens or context_alert.DEFAULTS["threshold_tokens"]
        self.menus = []
        self.cost_labels = {}
        clear(self)
        self.set_visible(bool(found))
        if not found:
            self.cost_loader.cancel()
            return None
        head = Gtk.Box(spacing=8)
        head.append(Gtk.Label(label="Ouvertes maintenant", xalign=0, hexpand=True, css_classes=["title-4"]))
        waiting = sum(1 for s in found if s.state == "waiting")
        count = f"{len(found)} ouverte" + ("s" if len(found) > 1 else "")
        if waiting:
            count += f" · {waiting} " + ("attendent ta réponse" if waiting > 1 else "attend ta réponse")
        total = session_memory.summary(self.memory) if self.memory else None
        if total and total.total:
            count += f" · {session_memory.fmt_bytes(total.total)}"
        head.append(Gtk.Label(label=count, valign=Gtk.Align.BASELINE_CENTER, css_classes=["caption", "dim-label"]))
        self.append(head)
        banner = session_memory.banner_text(total) if total else None
        if banner:
            self.append(Adw.Banner(title=banner, revealed=True))
        active = core.active_profile_name() or "compte non enregistré"
        self.append(caption(f"Toutes utilisent le compte actif ({active}) ; une bascule s'applique à "
                            "chacune à sa prochaine requête."))
        target_card = None
        for s in found:
            card = self.card(s, usage.get(s.pid), titles, show_project, compact)
            if s is target:
                card.add_css_class("ccs-highlight")
                target_card = card
            self.append(card)
        self.load_costs(stamps)
        return target_card

    # ---- coûts -----------------------------------------------------------------------

    def cost_label(self, label, text, path):
        """Libellé qui recevra le coût de ce journal : tout de suite s'il est connu, sinon
        quand load_costs() l'aura calculé."""
        path = str(path)
        self.cost_labels.setdefault(path, []).append((label, text))
        known = self.known_costs.get(path)
        if known is not None:
            self.put_cost(label, text, known[1])

    @staticmethod
    def put_cost(label, text, cost):
        short = costs.format_short(cost)
        label.set_label(f"{text} · {short}" if short else text)
        if short:
            label.set_tooltip_text(f"Coût de la conversation (équivalent API) : {costs.format_cost(cost)}")

    def load_costs(self, stamps):
        self.known_costs = {p: v for p, v in self.known_costs.items() if p in self.cost_labels}
        stale = [(path, path) for path in self.cost_labels
                 if stamps.get(path) is not None and (self.known_costs.get(path) or (None,))[0] != stamps[path]]

        def done(path, cost):
            self.known_costs[path] = (stamps.get(path), cost)
            for label, text in self.cost_labels.get(path, ()):
                self.put_cost(label, text, cost)
        self.cost_loader.request(stale, done)

    # ---- carte -------------------------------------------------------------------------

    def card(self, s, u, titles, show_project, compact):
        tab = self.window.terminals.find(pid=s.pid)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["card", "profile-card"])
        top = Gtk.Box(spacing=10)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        title = Gtk.Box(spacing=8)
        name = titles.get(s.session_id) or s.name
        title.append(Gtk.Label(label=name, css_classes=["heading"], xalign=0, ellipsize=Pango.EllipsizeMode.END,
                               tooltip_text=name))
        state = sessions.state_label(s)
        title.append(Gtk.Label(label=state, valign=Gtk.Align.CENTER, ellipsize=Pango.EllipsizeMode.END,
                               tooltip_text=state, css_classes=["caption", STATE_CLASSES[s.state]]))
        info.append(title)
        where = "dans l'application" if tab else "VS Code" if "vscode" in s.entrypoint else "terminal"
        parts = ([s.project] if show_project else []) + [
            where, f"ouverte depuis {duration(time.time() - s.started_at)}", f"pid {s.pid}"]
        info.append(caption(" · ".join(parts)))
        mem = self.memory.get(s.pid)
        ctx = self.contexts.get(s.pid)
        if mem is not None:
            line = caption(session_memory.line_text(mem))
            line.set_tooltip_text("Mémoire de la session et de ses programmes (PSS) ; inactivité depuis "
                                  "la dernière activité")
            info.append(line)
        if ctx is not None and ctx.tokens >= self.heavy_tokens:
            cost = context_alert.message_cost(ctx)
            badge = Gtk.Label(label=context_alert.badge_text(ctx), xalign=0, halign=Gtk.Align.START,
                              css_classes=["caption", "warning"],
                              tooltip_text="Chaque message relit tout ce contexte"
                              + (f" (environ {costs.format_dollars(cost)})" if cost is not None else "")
                              + " : /compact ou une nouvelle session l'allège.")
            info.append(badge)
        if u and u.messages:
            text = (f"{u.model} · {transcripts.fmt_tokens(u.weighted)} tokens pondérés · "
                    f"{plural(u.messages, 'réponse')}")
            line = caption(text)
            info.append(line)
            if s.session_id:
                self.cost_label(line, text, sessions.transcript_path(s.cwd, s.session_id))
        top.append(info)
        card.append(top)

        buttons = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        if tab is not None:
            show = Gtk.Button(label="Afficher", css_classes=["suggested-action"], valign=Gtk.Align.CENTER,
                              tooltip_text="Aller à l'onglet de cette session dans l'application")
            show.connect("clicked", lambda *_: self.window.terminals.present(tab))
            buttons.append(show)
        here = "Terminal ici" if self.window.terminals.available else "Terminal ici (externe)"
        for label, icon, cb in ((here, "utilities-terminal-symbolic", lambda *_: self.window.open_shell(s.cwd)),
                                ("Ouvrir le dossier", "folder-open-symbolic",
                                 lambda *_: sessions.open_folder(s.cwd))):
            b = Gtk.Button(icon_name=icon, tooltip_text=label, css_classes=["flat"], valign=Gtk.Align.CENTER)
            b.connect("clicked", cb)
            buttons.append(b)
        entries = []
        if s.session_id:
            entries.append(("Aperçu…", "sess.preview", pair(s.cwd, s.session_id)))
        if self.window.terminals.available:
            entries.append(("Terminal externe ici", "sess.shell", GLib.Variant.new_string(s.cwd)))
        if s.session_id:
            entries.append(("Renommer…", "sess.rename", pair(s.cwd, s.session_id)))
        if entries:
            more = menu_button(entries)
            self.menus.append(more)
            buttons.append(more)
        if mem is not None and mem.idle and self.on_close is not None:
            close = Gtk.Button(label="Fermer", css_classes=["flat"], valign=Gtk.Align.CENTER,
                               tooltip_text=f"Libérer {session_memory.fmt_bytes(mem.ram)} : session inactive, "
                                            "la conversation reste reprenable")
            close.connect("clicked", lambda *_: self.confirm_close(s, mem))
            buttons.append(close)
        stop = Gtk.Button(icon_name="process-stop-symbolic", tooltip_text="Terminer la session…",
                          css_classes=["flat", "error"], valign=Gtk.Align.CENTER)
        stop.connect("clicked", lambda *_: self.confirm_terminate(s))
        buttons.append(stop)
        if compact:
            # Fenêtre étroite : les boutons passent sous le texte.
            buttons.set_halign(Gtk.Align.END)
            card.append(buttons)
        else:
            top.append(buttons)
        return card

    def confirm_close(self, s, mem):
        """« Fermer » une session inactive : confirmation, puis rappel de la page."""
        d = Adw.AlertDialog(heading=f"Fermer la session « {s.project} » ?",
                            body=f"Elle est inactive et occupe {session_memory.fmt_bytes(mem.ram)}. "
                                 "La conversation est enregistrée : tu pourras la reprendre.")
        d.add_response("cancel", "Annuler")
        d.add_response("close", "Fermer")
        d.set_response_appearance("close", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: self.on_close(s) if r == "close" else None)
        d.present(self.window)

    def confirm_terminate(self, s):
        d = Adw.AlertDialog(heading=f"Terminer la session « {s.project} » ?",
                            body="La conversation est enregistrée : tu pourras la reprendre. "
                                 "Un travail en cours sera interrompu.")
        d.add_response("cancel", "Annuler")
        d.add_response("stop", "Terminer")
        d.set_response_appearance("stop", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(_d, r):
            if r == "stop":
                ok = sessions.terminate(s.pid, s.proc_start)
                self.window.toast("Session terminée" if ok else "Session déjà fermée")
                GLib.timeout_add(800, lambda: (self.on_changed(), False)[1])
        d.connect("response", on_response)
        d.present(self.window)
