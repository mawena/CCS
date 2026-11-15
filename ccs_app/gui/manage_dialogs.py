"""Fenêtres de gestion de la page Sessions, pour « Ce poste » comme pour un serveur :
ajouter un projet (dossier existant ou nouveau, `git init` en option), le retirer de la liste,
mettre une conversation à la corbeille (avec « Annuler ») et la corbeille elle-même.

`ops` : `remote.manage.LocalOps` ou `RemoteOps` (même interface `call(method, done, **params)`).
`notify(text, undo=None)` : toast de la fenêtre, avec un bouton « Annuler » si `undo` est donné."""

import os
import time

from gi.repository import Adw, GLib, Gtk

from ..remote.manage import message


def add_project(parent, ops, notify, on_done, where="ce poste"):
    """« Ajouter un projet » : dossier existant, ou nouveau dossier dans un parent (« ~ » accepté)."""
    dialog = Adw.AlertDialog(heading="Ajouter un projet",
                             body=f"Le projet apparaît dans la liste de {where} ; rien n'est déplacé.")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    existing = Gtk.CheckButton(label="Dossier existant", active=True)
    new = Gtk.CheckButton(label="Nouveau dossier", group=existing)
    modes = Gtk.Box(spacing=12)
    modes.append(existing)
    modes.append(new)
    box.append(modes)
    cwd = Gtk.Entry(placeholder_text="~/Work/mon-projet", hexpand=True)
    parent_entry = Gtk.Entry(text="~/Work", placeholder_text="Dossier parent")
    name = Gtk.Entry(placeholder_text="Nom du nouveau dossier")
    git = Gtk.CheckButton(label="Initialiser un dépôt git", active=True)
    new_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, visible=False)
    for w in (parent_entry, name, git):
        new_box.append(w)
    box.append(cwd)
    box.append(new_box)
    dialog.set_extra_child(box)
    dialog.add_response("cancel", "Annuler")
    dialog.add_response("add", "Ajouter")
    dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("add")

    def mode(*_):
        cwd.set_visible(existing.get_active())
        new_box.set_visible(new.get_active())
    existing.connect("toggled", mode)

    def done(result, error):
        if error is not None:
            notify(f"Ajout impossible : {message(error)}")
            return
        notify(f"Projet ajouté : {os.path.basename(result['cwd'].rstrip('/'))}")
        on_done(result["cwd"])

    def respond(_d, response):
        if response != "add":
            return
        if existing.get_active():
            path = cwd.get_text().strip()
            if path:
                ops.call("projects.add", done, cwd=path)
        elif name.get_text().strip():
            ops.call("projects.add", done, parent=parent_entry.get_text().strip(),
                     name=name.get_text().strip(), git=git.get_active())
    dialog.connect("response", respond)
    dialog.present(parent)
    return dialog


def remove_project(parent, ops, notify, cwd, title, on_done):
    """« Retirer de la liste » : le dossier et ses conversations restent."""
    dialog = Adw.AlertDialog(heading=f"Retirer « {title} » de la liste ?",
                             body="Le dossier et ses conversations restent ; le projet revient si une "
                                  "nouvelle conversation y démarre.")
    dialog.add_response("cancel", "Annuler")
    dialog.add_response("remove", "Retirer")
    dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)

    def done(_result, error):
        notify(f"Retrait impossible : {message(error)}" if error is not None else f"« {title} » retiré de la liste")
        if error is None:
            on_done()
    dialog.connect("response", lambda _d, r: r == "remove" and ops.call("projects.remove", done, cwd=cwd))
    dialog.present(parent)
    return dialog


def trash_conversation(parent, ops, notify, conv, on_done):
    """« Supprimer » : la conversation part à la corbeille de CCS (30 jours), « Annuler » juste
    après. `conv` : dict avec path, session_id, cwd, title."""
    title = conv.get("title") or "(sans titre)"
    dialog = Adw.AlertDialog(heading=f"Supprimer « {title} » ?",
                             body="Elle part à la corbeille de CCS : restaurable pendant 30 jours.")
    dialog.add_response("cancel", "Annuler")
    dialog.add_response("trash", "Supprimer")
    dialog.set_response_appearance("trash", Adw.ResponseAppearance.DESTRUCTIVE)

    def restored(_r, error):
        notify(f"Restauration impossible : {message(error)}" if error is not None else "Conversation restaurée")
        on_done()

    def done(result, error):
        if error is not None:
            notify(f"Suppression impossible : {message(error)}")
            return
        notify("Conversation mise à la corbeille",
               undo=lambda: ops.call("conversation.restore", restored, tid=result["tid"]))
        on_done()

    def respond(_d, response):
        if response == "trash":
            ops.call("conversation.trash", done, path=conv.get("path") or "", session_id=conv.get("session_id") or "",
                     cwd=conv.get("cwd") or "", title=title)
    dialog.connect("response", respond)
    dialog.present(parent)
    return dialog


class TrashDialog(Adw.Dialog):
    """Corbeille : conversations supprimées, « Restaurer » pendant 30 jours."""

    def __init__(self, ops, notify, on_done):
        super().__init__(title="Corbeille", content_width=520, content_height=520)
        self.ops, self.notify, self.on_done = ops, notify, on_done
        self.page = Adw.PreferencesPage()
        view = Adw.ToolbarView(content=self.page)
        view.add_top_bar(Adw.HeaderBar())
        self.set_child(view)
        self.group = None
        self.load()

    def load(self):
        if self.group is not None:
            self.page.remove(self.group)
        self.group = Adw.PreferencesGroup(title="Chargement…")
        self.page.add(self.group)
        self.ops.call("conversation.trash_list", self.fill)

    def fill(self, result, error):
        group = self.group
        if error is not None:
            group.set_title("Corbeille illisible")
            group.set_description(GLib.markup_escape_text(message(error)))
            return
        items = result.get("items") or []
        days = result.get("days") or 30
        group.set_title("Corbeille vide" if not items else "Conversations supprimées")
        group.set_description(f"Effacées pour de bon après {days} jours.")
        for it in items:
            when = time.strftime("%d/%m %H:%M", time.localtime(it.get("trashed_at") or 0))
            row = Adw.ActionRow(use_markup=False, title=it.get("title") or "(sans titre)",
                                subtitle=f"{os.path.basename((it.get('cwd') or '').rstrip('/'))} · supprimée le {when}")
            row.set_title_lines(1)
            b = Gtk.Button(label="Restaurer", valign=Gtk.Align.CENTER, css_classes=["flat"])
            b.connect("clicked", lambda _b, tid=it.get("tid"): self.restore(tid))
            row.add_suffix(b)
            group.add(row)

    def restore(self, tid):
        def done(_r, error):
            self.notify(f"Restauration impossible : {message(error)}" if error is not None
                        else "Conversation restaurée")
            self.on_done()
            self.load()
        self.ops.call("conversation.restore", done, tid=tid)
