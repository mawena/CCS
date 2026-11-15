"""Page Sessions, vue d'un serveur CCS appairé (VPS…) : chats en cours (rejoindre en direct),
projets (chat, terminal, retirer, ajouter) et conversations récentes (reprendre, supprimer),
corbeille. Remplace l'ancien dialogue « Projets des serveurs ». Un serveur injoignable n'empêche
rien d'autre : la vue le dit et réessaie."""

import os

from gi.repository import Adw, GLib, Gtk

from ..remote import engine as remote_engine
from ..remote.manage import RemoteOps, message
from . import manage_dialogs

REFRESH_S = 8                 # relecture des chats en cours tant que la vue est affichée
STATES = {"busy": "Claude travaille", "starting": "démarre", "permission": "attend une autorisation",
          "idle": "au repos", "stopped": "arrêté"}
STATE_LABELS = {"online": "Connecté", "reconnected": "Connecté", "offline": "Injoignable : reconnexion…",
                "auth": "Ce PC n'est plus autorisé : appaire-le de nouveau (Réglages → Serveurs CCS)"}


def chat_title(chat, convs):
    """Titre d'un chat en cours : celui de sa conversation si on la connaît, sinon le projet."""
    sid = chat.get("session_id")
    for c in convs:
        if sid and c.get("session_id") == sid:
            return c.get("title") or c.get("first_prompt") or os.path.basename(chat["cwd"])
    return os.path.basename((chat.get("cwd") or "").rstrip("/")) or chat.get("cwd") or "chat"


class RemoteMachineView(Gtk.Box):
    def __init__(self, window, server, dispatch):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window, self.server = window, server
        self.conn = remote_engine.connection(server, dispatch)
        self.ops = RemoteOps(self.conn)
        self.convs, self.chats, self.projects = [], [], []
        self._timer = None

        head = Gtk.Box(spacing=8, margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        titles.append(Gtk.Label(label=server.name, xalign=0, css_classes=["title-2"]))
        self.status = Gtk.Label(xalign=0, css_classes=["caption", "dim-label"])
        titles.append(self.status)
        head.append(titles)
        for icon, tip, fn in (("view-refresh-symbolic", "Actualiser", self.refresh),
                              ("user-trash-symbolic", "Corbeille du serveur", self.open_trash),
                              ("list-add-symbolic", "Ajouter un projet sur le serveur", self.add_project)):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip, valign=Gtk.Align.CENTER, css_classes=["flat"])
            b.connect("clicked", lambda _b, f=fn: f())
            head.append(b)
        self.append(head)
        self.page = Adw.PreferencesPage(vexpand=True)
        self.append(self.page)
        self.groups = []
        self.conn.listeners.add(self.on_state)
        self.on_state(self.conn.state)
        self.connect("map", lambda *_: self.start())
        self.connect("unmap", lambda *_: self.stop())

    # ---- relectures ----------------------------------------------------------------------

    def start(self):
        self.refresh()
        if self._timer is None:
            self._timer = GLib.timeout_add_seconds(REFRESH_S, self._tick)

    def stop(self):
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _tick(self):
        self.conn.call("chat.list", callback=self.chats_loaded)
        return True

    def on_state(self, state):
        self.status.set_label(f"{self.server.url} · {STATE_LABELS.get(state, state)}")
        if state == "reconnected" and self.get_mapped():
            self.refresh()

    def refresh(self):
        self.conn.call("projects.list", callback=self.projects_loaded)

    def projects_loaded(self, result, error):
        if error is not None:
            self.render(error)
            return
        self.projects = [p for p in result.get("entries") or [] if p.get("cwd") and p.get("exists", True)]
        self.convs = [c for c in result.get("conversations") or [] if c.get("folder_exists", True)]
        self.conn.call("chat.list", callback=self.chats_loaded)

    def chats_loaded(self, result, error):
        chats = [] if error is not None else (result.get("chats") or [])
        signature = [(c["chat_id"], c.get("state"), c.get("session_id")) for c in chats]
        if error is None and signature == getattr(self, "_sig", None) and self.groups:
            return
        self._sig = signature
        self.chats = chats
        self.render(error)

    # ---- affichage -------------------------------------------------------------------------

    def notify(self, text, undo=None):
        self.window.toast(text, undo=undo)

    def group(self, title, description=None):
        g = Adw.PreferencesGroup(title=GLib.markup_escape_text(title),
                                 description=GLib.markup_escape_text(description) if description else None)
        self.page.add(g)
        self.groups.append(g)
        return g

    def button(self, label, fn, tip=None, css="flat"):
        b = Gtk.Button(label=label, valign=Gtk.Align.CENTER, css_classes=[css], tooltip_text=tip)
        b.connect("clicked", lambda _b: fn())
        return b

    def render(self, error=None):
        for g in self.groups:
            self.page.remove(g)
        self.groups = []
        if error is not None:
            g = self.group("Serveur injoignable", message(error))
            g.add(Adw.ActionRow(use_markup=False, title="Nouvel essai à la reconnexion, ou avec « Actualiser »."))
            return
        live = [c for c in self.chats if c.get("state") != "stopped"]
        if live:
            g = self.group("En cours", "Chats ouverts sur le serveur (téléphone, web, autre PC)")
            for c in live:
                title = chat_title(c, self.convs)
                row = Adw.ActionRow(use_markup=False, title=title, subtitle=f"{os.path.basename(c['cwd'].rstrip('/'))} · "
                                    f"{STATES.get(c.get('state'), c.get('state') or '')}")
                row.set_title_lines(1)
                row.add_suffix(self.button("Rejoindre", lambda c=c, t=title: self.join(c, t),
                                           "Suivre et piloter ce chat en direct", "suggested-action"))
                g.add(row)
        g = self.group("Projets")
        if not self.projects:
            g.add(Adw.ActionRow(use_markup=False, title="Aucun projet : « + » pour en ajouter un."))
        for p in self.projects[:40]:
            name = p.get("name") or os.path.basename(p["cwd"].rstrip("/"))
            row = Adw.ActionRow(use_markup=False, title=name, subtitle=p["cwd"])
            row.add_suffix(self.button("Chat", lambda c=p["cwd"]: self.terms.open_remote_chat(self.server, c)))
            row.add_suffix(self.button("Terminal", lambda c=p["cwd"]: self.terms.open_remote_shell(self.server, c)))
            rm = Gtk.Button(icon_name="list-remove-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                            tooltip_text="Retirer de la liste (rien n'est effacé)")
            rm.connect("clicked", lambda _b, c=p["cwd"], n=name: manage_dialogs.remove_project(
                self, self.ops, self.notify, c, n, self.refresh))
            row.add_suffix(rm)
            g.add(row)
        convs = self.convs[:25]
        if convs:
            g = self.group("Conversations récentes")
            for c in convs:
                title = c.get("title") or c.get("first_prompt") or "(sans titre)"
                row = Adw.ActionRow(use_markup=False, title=title, subtitle=os.path.basename(c["cwd"].rstrip("/")))
                row.set_title_lines(1)
                row.add_suffix(self.button("Reprendre", lambda c=c, t=title: self.terms.open_remote_chat(
                    self.server, c["cwd"], c["session_id"], t, c.get("path"))))
                rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                                tooltip_text="Supprimer (corbeille, 30 jours)")
                rm.connect("clicked", lambda _b, c=c, t=title: manage_dialogs.trash_conversation(
                    self, self.ops, self.notify, {**c, "title": t}, self.refresh))
                row.add_suffix(rm)
                g.add(row)

    # ---- actions ---------------------------------------------------------------------------

    @property
    def terms(self):
        return self.window.terminals

    def joined_tab(self, chat_id):
        for tab in self.terms.tabs():
            eng = getattr(tab, "engine", None)
            if getattr(tab, "remote", None) == self.server.name and getattr(eng, "chat_id", None) == chat_id:
                return tab
        return None

    def join(self, chat, title):
        """Rejoindre un chat en cours : son onglet s'il est déjà ouvert, sinon un nouvel onglet
        branché sur ce chat (fil rejoué puis suivi en direct)."""
        tab = self.joined_tab(chat["chat_id"])
        if tab is not None:
            self.terms.present(tab)
            return
        self.terms.open_remote_chat(self.server, chat["cwd"], chat.get("session_id"), title,
                                    chat.get("path") if chat.get("history_before") else None,
                                    chat_id=chat["chat_id"])

    def add_project(self):
        manage_dialogs.add_project(self, self.ops, self.notify, lambda _cwd: self.refresh(),
                                   where=f"« {self.server.name} »")

    def open_trash(self):
        manage_dialogs.TrashDialog(self.ops, self.notify, self.refresh).present(self)
