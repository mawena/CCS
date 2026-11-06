"""Onglet Sessions : sessions Claude Code ouvertes, conversations récentes."""

import time

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from .. import core, sessions, terminal, transcripts
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


def _pair(a, b=""):
    return GLib.Variant("(ss)", (a or "", b or ""))


class SessionsPage(Gtk.ScrolledWindow):
    def __init__(self, window):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.window = window
        self.visible_page = False
        self.last = None
        self.titles = {}
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                           margin_top=18, margin_bottom=18, margin_start=12, margin_end=12)
        self.set_child(Adw.Clamp(maximum_size=820, child=self.box))

        # Menus « ⋮ » : sess.external((dossier, conversation)), sess.shell('dossier'),
        # sess.rename((dossier, conversation)).
        actions = Gio.SimpleActionGroup()
        for name, kind, handler in (
                ("external", "(ss)", lambda v: self.start(*v.unpack(), external=True)),
                ("shell", "s", lambda v: self.window.open_shell(v.get_string(), external=True)),
                ("rename", "(ss)", lambda v: self.rename(*v.unpack()))):
            a = Gio.SimpleAction.new(name, GLib.VariantType.new(kind))
            a.connect("activate", lambda _a, v, h=handler: h(v))
            actions.add_action(a)
        self.insert_action_group("sess", actions)
        GLib.timeout_add_seconds(REFRESH_S, self._tick)

    def _tick(self):
        if self.visible_page:
            self.load()
        return True

    def load(self):
        def work():
            found = sessions.list_sessions()
            usage = {s.pid: sessions.conversation_usage(s) for s in found}
            titles = {s.session_id: sessions.conversation_title(s.cwd, s.session_id) for s in found}
            projects = sessions.recent_projects(6)
            convs = {cwd: sessions.recent_conversations(cwd, 4) for cwd, _ in projects}
            return found, usage, projects, convs, titles
        in_thread(work, self.show)

    def rerender(self):
        if self.last is not None:
            self.show(self.last)

    # ---- rendu ---------------------------------------------------------------

    def show(self, result):
        self.last = result
        found, usage, projects, convs, titles = result
        self.titles = {c.session_id: c.title for group in convs.values() for c in group}
        self.titles.update({sid: t for sid, t in titles.items() if t})  # titre seul, sans repli
        opened = {s.session_id for s in found if s.session_id}
        clear(self.box)
        active = core.active_profile_name() or "compte non enregistré"
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, css_classes=["card", "best-card"])
        head.append(Gtk.Label(label=f"{len(found)} session(s) Claude Code ouverte(s)", xalign=0,
                              css_classes=["heading"]))
        head.append(caption(f"Toutes utilisent le compte actif ({active}) ; une bascule s'applique "
                            "à chacune à sa prochaine requête."))
        if not self.window.terminals.available:
            head.append(caption(terminal.VTE_HINT))
        self.box.append(head)
        if not found:
            self.box.append(Adw.StatusPage(icon_name="utilities-terminal-symbolic",
                                           title="Aucune session ouverte"))
        for s in found:
            self.box.append(self.session_card(s, usage.get(s.pid), titles))

        if projects:
            title = Gtk.Box(spacing=8, margin_top=8)
            title.append(Gtk.Label(label="Reprendre ou démarrer", xalign=0, hexpand=True,
                                   css_classes=["title-4"]))
            history = Gtk.Button(label="Tout l'historique", css_classes=["flat"], valign=Gtk.Align.CENTER)
            history.connect("clicked", lambda *_: self.window.stack.set_visible_child_name("conversations"))
            title.append(history)
            self.box.append(title)
        for cwd, _mtime in projects:
            self.box.append(self.project_card(cwd, convs.get(cwd) or [], opened))

    def menu_button(self, entries):
        menu = Gio.Menu()
        for label, action, target in entries:
            item = Gio.MenuItem.new(label, None)
            item.set_action_and_target_value(action, target)
            menu.append_item(item)
        return Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu, css_classes=["flat"],
                              valign=Gtk.Align.CENTER, tooltip_text="Autres actions")

    def session_card(self, s, u, titles):
        tab = self.window.terminals.find(pid=s.pid)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["card", "profile-card"])
        top = Gtk.Box(spacing=10)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        title = Gtk.Box(spacing=8)
        title.append(Gtk.Label(label=s.project, css_classes=["title-4"], xalign=0))
        title.append(Gtk.Label(label=sessions.state_label(s), valign=Gtk.Align.CENTER,
                               css_classes=["caption", STATE_CLASSES[s.state]]))
        info.append(title)
        where = "dans l'application" if tab else "VS Code" if "vscode" in s.entrypoint else "terminal"
        name = titles.get(s.session_id) or s.name
        info.append(caption(f"{name} · {where} · ouverte depuis {_duration(time.time() - s.started_at)} "
                            f"· pid {s.pid}"))
        if u and u.messages:
            info.append(caption(f"{u.model} · {transcripts.fmt_tokens(u.weighted)} tokens pondérés · "
                                f"{u.messages} réponses"))
        top.append(info)
        buttons = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        if tab is not None:
            show = Gtk.Button(label="Afficher", css_classes=["suggested-action"], valign=Gtk.Align.CENTER,
                              tooltip_text="Aller à l'onglet de cette session")
            show.connect("clicked", lambda *_: self.window.terminals.present(tab))
            buttons.append(show)
        here = "Terminal ici" if self.window.terminals.available else "Terminal ici (externe)"
        for label, icon, cb in ((here, "utilities-terminal-symbolic", lambda *_: self.window.open_shell(s.cwd)),
                                ("Dossier", "folder-open-symbolic", lambda *_: sessions.open_folder(s.cwd))):
            b = Gtk.Button(icon_name=icon, tooltip_text=label, css_classes=["flat"])
            b.connect("clicked", cb)
            buttons.append(b)
        entries = []
        if self.window.terminals.available:
            entries.append(("Terminal externe ici", "sess.shell", GLib.Variant.new_string(s.cwd)))
        if s.session_id:
            entries.append(("Renommer…", "sess.rename", _pair(s.cwd, s.session_id)))
        if entries:
            buttons.append(self.menu_button(entries))
        stop = Gtk.Button(icon_name="process-stop-symbolic", tooltip_text="Terminer la session…",
                          css_classes=["flat", "error"])
        stop.connect("clicked", lambda *_: self.confirm_terminate(s))
        buttons.append(stop)
        top.append(buttons)
        card.append(top)
        return card

    def project_card(self, cwd, convs, opened):
        embedded = self.window.terminals.available
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card", "profile-card"])
        head = Gtk.Box(spacing=8)
        name = sessions.project_name(cwd)
        head.append(Gtk.Label(label=name, css_classes=["heading"], xalign=0, hexpand=True))
        if embedded:
            menu = Gio.Menu()
            item = Gio.MenuItem.new("Dans un terminal externe", None)
            item.set_action_and_target_value("sess.external", _pair(cwd))
            menu.append_item(item)
            new = Adw.SplitButton(label="Nouvelle session", menu_model=menu, valign=Gtk.Align.CENTER,
                                  tooltip_text="Nouvelle session dans l'application")
        else:
            new = Gtk.Button(label="Nouvelle session", css_classes=["pill"],
                             tooltip_text="Nouvelle session dans un terminal")
        new.connect("clicked", lambda *_: self.start(cwd))
        head.append(new)
        card.append(head)
        card.append(caption(cwd))
        for c in convs:
            tab = self.window.terminals.find(session_id=c.session_id)
            row = Gtk.Box(spacing=8)
            row.append(Gtk.Label(label=c.title, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END))
            row.append(Gtk.Label(label=_ago(c.updated), css_classes=["dim-label", "caption"]))
            if tab is not None:
                show = Gtk.Button(label="Afficher", css_classes=["flat"],
                                  tooltip_text="Ouverte dans l'application : aller à son onglet")
                show.connect("clicked", lambda *_, t=tab: self.window.terminals.present(t))
                row.append(show)
            else:
                elsewhere = c.session_id in opened
                resume = Gtk.Button(label="Reprendre", css_classes=["flat"], sensitive=not elsewhere,
                                    tooltip_text="Déjà ouverte dans une session Claude Code" if elsewhere
                                    else "Reprendre dans l'application" if embedded
                                    else "Reprendre dans un terminal")
                resume.connect("clicked", lambda *_, sid=c.session_id, t=c.title: self.start(cwd, sid, t))
                row.append(resume)
            entries = []
            if embedded and tab is None and c.session_id not in opened:
                entries.append(("Reprendre dans un terminal externe", "sess.external", _pair(cwd, c.session_id)))
            entries.append(("Renommer…", "sess.rename", _pair(cwd, c.session_id)))
            row.append(self.menu_button(entries))
            card.append(row)
        return card

    # ---- actions -------------------------------------------------------------

    def start(self, cwd, resume=None, title=None, external=False):
        where = self.window.open_claude(cwd, resume or None, title, external)
        if where == "externe":
            self.window.toast("Conversation reprise dans un nouveau terminal" if resume
                              else "Nouvelle session lancée dans un terminal")

    def rename(self, cwd, session_id):
        current = self.titles.get(session_id) or sessions.conversation_title(cwd, session_id) or ""
        self.window.rename_conversation(session_id, cwd=cwd, current=current)

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
