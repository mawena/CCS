"""Onglet Sessions : sessions Claude Code ouvertes, conversations récentes."""

import time

from gi.repository import Adw, GLib, Gtk

from .. import core, sessions, transcripts
from .common import caption, clear, in_thread

REFRESH_S = 15
STATE_CLASSES = {"busy": "warning", "waiting": "accent", "idle": "dim-label"}


def _duration(seconds):
    minutes = int(seconds // 60)
    return f"{minutes // 60} h {minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"


def _ago(ts):
    seconds = time.time() - ts
    if seconds >= 86400:
        days = int(seconds // 86400)
        return f"il y a {days} j" if days > 1 else "hier"
    return "il y a " + _duration(seconds)


class SessionsPage(Gtk.ScrolledWindow):
    def __init__(self, window):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.window = window
        self.visible_page = False
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                           margin_top=18, margin_bottom=18, margin_start=12, margin_end=12)
        self.set_child(Adw.Clamp(maximum_size=820, child=self.box))
        GLib.timeout_add_seconds(REFRESH_S, self._tick)

    def _tick(self):
        if self.visible_page:
            self.load()
        return True

    def load(self):
        def work():
            found = sessions.list_sessions()
            usage = {s.pid: sessions.conversation_usage(s) for s in found}
            projects = sessions.recent_projects(6)
            convs = {cwd: sessions.recent_conversations(cwd, 4) for cwd, _ in projects}
            return found, usage, projects, convs
        in_thread(work, self.show)

    # ---- rendu ---------------------------------------------------------------

    def show(self, result):
        found, usage, projects, convs = result
        clear(self.box)
        active = core.active_profile_name() or "compte non enregistré"
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, css_classes=["card", "best-card"])
        head.append(Gtk.Label(label=f"{len(found)} session(s) Claude Code ouverte(s)", xalign=0,
                              css_classes=["heading"]))
        head.append(caption(f"Toutes utilisent le compte actif ({active}) ; une bascule s'applique "
                            "à chacune à sa prochaine requête."))
        self.box.append(head)
        if not found:
            self.box.append(Adw.StatusPage(icon_name="utilities-terminal-symbolic",
                                           title="Aucune session ouverte"))
        for s in found:
            self.box.append(self.session_card(s, usage.get(s.pid)))

        if projects:
            self.box.append(Gtk.Label(label="Reprendre ou démarrer", xalign=0,
                                      css_classes=["title-4"], margin_top=8))
        for cwd, _mtime in projects:
            self.box.append(self.project_card(cwd, convs.get(cwd) or []))

    def session_card(self, s, u):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["card", "profile-card"])
        top = Gtk.Box(spacing=10)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        title = Gtk.Box(spacing=8)
        title.append(Gtk.Label(label=s.project, css_classes=["title-4"], xalign=0))
        title.append(Gtk.Label(label=sessions.state_label(s), valign=Gtk.Align.CENTER,
                               css_classes=["caption", STATE_CLASSES[s.state]]))
        info.append(title)
        where = "VS Code" if "vscode" in s.entrypoint else "terminal"
        info.append(caption(f"{s.name} · {where} · ouverte depuis {_duration(time.time() - s.started_at)} "
                            f"· pid {s.pid}"))
        if u and u.messages:
            info.append(caption(f"{u.model} · {transcripts.fmt_tokens(u.weighted)} tokens pondérés · "
                                f"{u.messages} réponses"))
        top.append(info)
        buttons = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        for label, icon, cb in (("Terminal ici", "utilities-terminal-symbolic",
                                 lambda *_: sessions.open_terminal(s.cwd, start_claude=False)),
                                ("Dossier", "folder-open-symbolic", lambda *_: sessions.open_folder(s.cwd))):
            b = Gtk.Button(icon_name=icon, tooltip_text=label, css_classes=["flat"])
            b.connect("clicked", cb)
            buttons.append(b)
        stop = Gtk.Button(icon_name="process-stop-symbolic", tooltip_text="Terminer la session…",
                          css_classes=["flat", "error"])
        stop.connect("clicked", lambda *_: self.confirm_terminate(s))
        buttons.append(stop)
        top.append(buttons)
        card.append(top)
        return card

    def project_card(self, cwd, convs):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card", "profile-card"])
        head = Gtk.Box(spacing=8)
        name = sessions.project_name(cwd)
        head.append(Gtk.Label(label=name, css_classes=["heading"], xalign=0, hexpand=True))
        new = Gtk.Button(label="Nouvelle session", css_classes=["pill"])
        new.connect("clicked", lambda *_: self.start(cwd))
        head.append(new)
        card.append(head)
        card.append(caption(cwd))
        for c in convs:
            row = Gtk.Box(spacing=8)
            row.append(Gtk.Label(label=c.title, xalign=0, hexpand=True, ellipsize=3))
            row.append(Gtk.Label(label=_ago(c.updated), css_classes=["dim-label", "caption"]))
            resume = Gtk.Button(label="Reprendre", css_classes=["flat"])
            resume.connect("clicked", lambda *_, sid=c.session_id: self.start(cwd, sid))
            row.append(resume)
            card.append(row)
        return card

    # ---- actions -------------------------------------------------------------

    def start(self, cwd, resume=None):
        sessions.open_terminal(cwd, resume)
        self.window.toast("Conversation reprise dans un nouveau terminal" if resume
                          else "Nouvelle session lancée dans un terminal")

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
                GLib.timeout_add(800, lambda: (self.load(), False)[1])
        d.connect("response", on_response)
        d.present(self.window)
