"""Onglet Sessions : sessions Claude Code ouvertes, conversations récentes."""

import os
import time

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from .. import attention, conversations, core, costs, sessions, terminal, transcripts
from .common import caption, clear, in_thread

REFRESH_S = 15
HIGHLIGHT_S = 12   # mise en évidence de la session désignée par une notification
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


def _stamp(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


class SessionsPage(Gtk.ScrolledWindow):
    def __init__(self, window):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.window = window
        self.visible_page = False
        self.last = None
        self.titles = {}
        self.highlighted = None      # (pid, identifiant, jusqu'à) : session d'une notification
        self.highlight_new = False   # premier rendu après la demande : prévenir si elle est fermée
        self.counting = False
        self.cost_loader = costs.Loader()
        self.known_costs = {}        # journal -> (empreinte, Cost) : affichés sans attendre
        self.cost_labels = {}        # journal -> [(libellé, texte sans le coût)]
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                           margin_top=18, margin_bottom=18, margin_start=12, margin_end=12)
        self.clamp = Adw.Clamp(maximum_size=820, child=self.box)
        self.set_child(self.clamp)

        # Menus « ⋮ » : sess.external((dossier, conversation)), sess.shell('dossier'),
        # sess.rename((dossier, conversation)), sess.preview((dossier, conversation)),
        # sess.new('dossier') (nouvelle session avec options).
        actions = Gio.SimpleActionGroup()
        for name, kind, handler in (
                ("external", "(ss)", lambda v: self.start(*v.unpack(), external=True)),
                ("shell", "s", lambda v: self.window.open_shell(v.get_string(), external=True)),
                ("rename", "(ss)", lambda v: self.rename(*v.unpack())),
                ("preview", "(ss)", lambda v: self.preview(*v.unpack())),
                ("new", "s", lambda v: self.window.new_session(v.get_string()))):
            a = Gio.SimpleAction.new(name, GLib.VariantType.new(kind))
            a.connect("activate", lambda _a, v, h=handler: h(v))
            actions.add_action(a)
        self.insert_action_group("sess", actions)
        GLib.timeout_add_seconds(REFRESH_S, self._tick)

    def _tick(self):
        if self.visible_page:
            self.load()
        else:
            self.count_waiting()  # badge de l'onglet : fiches de session seules, sans journaux
        return True

    def load(self):
        def work():
            found = sessions.list_sessions()
            usage = {s.pid: sessions.conversation_usage(s) for s in found}
            titles = {s.session_id: sessions.conversation_title(s.cwd, s.session_id) for s in found}
            projects = sessions.recent_projects(6)
            convs = {cwd: sessions.recent_conversations(cwd, 4) for cwd, _ in projects}
            journals = [sessions.transcript_path(s.cwd, s.session_id) for s in found if s.session_id]
            journals += [sessions.transcript_path(cwd, c.session_id) for cwd, group in convs.items()
                         for c in group]
            stamps = {str(p): _stamp(p) for p in journals}
            return found, usage, projects, convs, titles, stamps
        in_thread(work, self.show)

    def rerender(self):
        if self.last is not None:
            self.show(self.last)

    # ---- badge et mise en évidence ------------------------------------------------

    def count_waiting(self):
        if self.counting:
            return
        self.counting = True

        def done(found):
            self.counting = False
            self.set_badge(found)
        in_thread(sessions.list_sessions, done)

    def set_badge(self, found):
        """Nombre de sessions qui attendent une réponse sur l'onglet (point d'attention s'il
        n'est pas affiché)."""
        page = self.window.stack.get_page(self)
        if page is None:
            return
        n = attention.waiting_count(found)
        page.set_badge_number(n)
        page.set_needs_attention(n > 0 and not self.visible_page)

    def highlight(self, pid, session_id):
        self.highlighted = (pid, session_id, time.time() + HIGHLIGHT_S)
        self.highlight_new = True
        self.load()

    def highlight_target(self, found):
        if self.highlighted is None:
            return None
        pid, sid, until = self.highlighted
        if time.time() > until:
            self.highlighted = None
            return None
        target = attention.match_session(found, pid, sid)
        if target is None and self.highlight_new:
            self.highlighted = None
            self.window.toast("Cette session n'est plus ouverte")
        self.highlight_new = False
        return target

    def scroll_to(self, widget):
        ok, rect = widget.compute_bounds(self.clamp)
        if ok:
            self.get_vadjustment().set_value(max(0.0, rect.get_y() - 12))
        return False

    def default_folder(self):
        """Dossier proposé pour une nouvelle session : projet le plus récent."""
        if self.last is not None:
            found, _u, projects = self.last[:3]
            if projects:
                return projects[0][0]
            if found:
                return found[-1].cwd
        return str(core.paths().home)

    # ---- rendu ---------------------------------------------------------------

    def show(self, result):
        self.last = result
        found, usage, projects, convs, titles, stamps = result
        self.titles = {c.session_id: c.title for group in convs.values() for c in group}
        self.titles.update({sid: t for sid, t in titles.items() if t})  # titre seul, sans repli
        opened = {s.session_id for s in found if s.session_id}
        self.cost_labels = {}
        self.set_badge(found)
        target = self.highlight_target(found)
        clear(self.box)
        active = core.active_profile_name() or "compte non enregistré"
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, css_classes=["card", "best-card"])
        top = Gtk.Box(spacing=8)
        top.append(Gtk.Label(label=f"{len(found)} session(s) Claude Code ouverte(s)", xalign=0, hexpand=True,
                             css_classes=["heading"]))
        new = Gtk.Button(label="Nouvelle session…", css_classes=["pill"], valign=Gtk.Align.CENTER,
                         tooltip_text="Dossier, compte, modèle et permissions au choix")
        new.connect("clicked", lambda *_: self.window.new_session())
        top.append(new)
        head.append(top)
        head.append(caption(f"Toutes utilisent le compte actif ({active}) ; une bascule s'applique "
                            "à chacune à sa prochaine requête."))
        if not self.window.terminals.available:
            head.append(caption(terminal.VTE_HINT))
        self.box.append(head)
        if not found:
            self.box.append(Adw.StatusPage(icon_name="utilities-terminal-symbolic",
                                           title="Aucune session ouverte"))
        target_card = None
        for s in found:
            card = self.session_card(s, usage.get(s.pid), titles)
            if s is target:
                card.add_css_class("ccs-highlight")
                target_card = card
            self.box.append(card)

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
        if target_card is not None:
            GLib.timeout_add(60, self.scroll_to, target_card)
        self.load_costs(stamps)

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

    # ---- cartes ----------------------------------------------------------------------

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
            text = (f"{u.model} · {transcripts.fmt_tokens(u.weighted)} tokens pondérés · "
                    f"{u.messages} réponses")
            line = caption(text)
            info.append(line)
            if s.session_id:
                self.cost_label(line, text, sessions.transcript_path(s.cwd, s.session_id))
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
        if s.session_id:
            entries.append(("Aperçu…", "sess.preview", _pair(s.cwd, s.session_id)))
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
        menu = Gio.Menu()
        if embedded:
            item = Gio.MenuItem.new("Dans un terminal externe", None)
            item.set_action_and_target_value("sess.external", _pair(cwd))
            menu.append_item(item)
        item = Gio.MenuItem.new("Avec des options…", None)
        item.set_action_and_target_value("sess.new", GLib.Variant.new_string(cwd))
        menu.append_item(item)
        new = Adw.SplitButton(label="Nouvelle session", menu_model=menu, valign=Gtk.Align.CENTER,
                              tooltip_text="Nouvelle session dans l'application" if embedded
                              else "Nouvelle session dans un terminal")
        new.connect("clicked", lambda *_: self.start(cwd))
        head.append(new)
        card.append(head)
        card.append(caption(cwd))
        for c in convs:
            tab = self.window.terminals.find(session_id=c.session_id)
            row = Gtk.Box(spacing=8)
            row.append(Gtk.Label(label=c.title, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END))
            when = Gtk.Label(label=_ago(c.updated), css_classes=["dim-label", "caption"])
            self.cost_label(when, _ago(c.updated), sessions.transcript_path(cwd, c.session_id))
            row.append(when)
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
            entries = [("Aperçu…", "sess.preview", _pair(cwd, c.session_id))]
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

    def preview(self, cwd, session_id):
        path = sessions.transcript_path(cwd, session_id)

        def work():
            try:
                return conversations.from_journal(path, cwd)
            except OSError as e:
                return e

        def done(conv):
            if isinstance(conv, OSError):
                self.window.toast(f"Aperçu impossible : {conv.strerror or conv}")
            else:
                self.window.preview(conv)
        in_thread(work, done)

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
