"""Dialogue « Projets des serveurs » (page Sessions) : pour chaque serveur CCS appairé, ses
projets (nouveau chat, terminal) et ses conversations récentes (reprendre)."""

import os

from gi.repository import Adw, Gtk

from ..remote import engine as remote_engine
from ..remote import servers


class RemoteProjectsDialog(Adw.Dialog):
    def __init__(self, window, dispatch):
        super().__init__(title="Projets des serveurs", content_width=560, content_height=640)
        self.window = window
        self.dispatch = dispatch
        page = Adw.PreferencesPage()
        view = Adw.ToolbarView(content=page)
        view.add_top_bar(Adw.HeaderBar())
        self.set_child(view)
        items = servers.load()
        if not items:
            group = Adw.PreferencesGroup(title="Aucun serveur",
                                         description="Ajoute ton VPS dans les Réglages → Serveurs CCS.")
            page.add(group)
        for server in items:
            group = Adw.PreferencesGroup(title=server.name, description=server.url)
            loading = Adw.ActionRow(title="Chargement…")
            group.add(loading)
            page.add(group)
            conn = remote_engine.connection(server, dispatch)
            conn.call("projects.list", callback=lambda r, e, g=group, l=loading, s=server: self._fill(g, l, s, r, e))

    def _button(self, label, callback):
        b = Gtk.Button(label=label, valign=Gtk.Align.CENTER, css_classes=["flat"])
        b.connect("clicked", lambda _b: (callback(), self.close()))
        return b

    def _fill(self, group, loading, server, result, error):
        group.remove(loading)
        if error is not None:
            group.add(Adw.ActionRow(title="Serveur injoignable", subtitle=str(getattr(error, "message", error))))
            return
        terms = self.window.terminals
        for p in (result.get("entries") or [])[:30]:
            if not p.get("cwd") or not p.get("exists", True):
                continue
            row = Adw.ActionRow(title=p.get("name") or p["cwd"], subtitle=p["cwd"])
            row.add_suffix(self._button("Chat", lambda c=p["cwd"]: terms.open_remote_chat(server, c)))
            row.add_suffix(self._button("Terminal", lambda c=p["cwd"]: terms.open_remote_shell(server, c)))
            group.add(row)
        convs = [c for c in result.get("conversations") or [] if c.get("folder_exists", True)][:15]
        if convs:
            group.add(Adw.ActionRow(title="Conversations récentes", css_classes=["dim-label"]))
        for c in convs:
            title = c.get("title") or c.get("first_prompt") or "(sans titre)"
            row = Adw.ActionRow(title=title, subtitle=os.path.basename(c["cwd"]))
            row.add_suffix(self._button("Reprendre", lambda c=c, t=title: terms.open_remote_chat(
                server, c["cwd"], c["session_id"], t, c.get("path"))))
            group.add(row)
