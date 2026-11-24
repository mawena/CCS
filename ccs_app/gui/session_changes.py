"""Volet « Changements de la session » : fichiers modifiés par Claude depuis le début de la
conversation (d'après ses copies, voir `file_history`), annulation fichier par fichier, et points
de reprise (un par message de l'utilisateur) pour revenir en arrière."""

import os

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GObject, Gtk

from .. import file_history
from .common import in_thread


def _shown(text, limit=60):
    one = " ".join(text.split())
    return one if len(one) <= limit else one[:limit - 1] + "…"


def _hhmm(iso):
    return iso[11:16] if len(iso) >= 16 else ""


class ChangesPanel(Gtk.Box):
    __gsignals__ = {
        "show-diff": (GObject.SignalFlags.RUN_FIRST, None, (str, str, str)),
        "rewind-requested": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, transcript, session_id):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, vexpand=True,
                         hexpand=True)
        self.transcript = transcript
        self.session_id = session_id
        self._snaps = None
        self._changes = []
        self._points = []
        self._loaded = False
        self._unknown = False
        self._buttons = []
        self.set_margin_top(8)
        self.set_margin_start(10)
        self.set_margin_end(10)
        self.message = Gtk.Label(xalign=0, wrap=True, visible=False)
        self.message.add_css_class("dim-label")
        self.append(self.message)
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        scroll.set_child(self.content)
        self.append(scroll)

    # ---- lecture ------------------------------------------------------------------------

    def refresh(self):
        transcript, session = self.transcript, self.session_id

        def work():
            snaps = file_history.read(transcript)
            if snaps is None:
                return None, [], []
            return snaps, file_history.changes(snaps, session), file_history.user_messages(transcript)
        in_thread(work, self._show)

    def _show(self, result):
        self._loaded = True
        self._snaps, self._changes, self._points = result
        self._unknown = self._snaps is None
        self._buttons = []
        while (c := self.content.get_first_child()) is not None:
            self.content.remove(c)
        if self._unknown:
            self.message.set_label("Le format de l'historique des fichiers de Claude Code n'est "
                                   "pas reconnu : rien ne peut être annulé d'ici. Voir « ccs doctor ».")
            self.message.set_visible(True)
            return
        self.message.set_visible(False)
        self.content.append(self._title("Fichiers modifiés"))
        files = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        files.add_css_class("boxed-list")
        for ch in self._changes:
            files.append(self._file_row(ch))
        if not self._changes:
            files.append(Gtk.Label(label="Aucun fichier modifié depuis le début de la session.",
                                   margin_top=8, margin_bottom=8, xalign=0, margin_start=8))
        self.content.append(files)
        self.content.append(self._title("Revenir en arrière"))
        points = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        points.add_css_class("boxed-list")
        for pt in self._points:
            points.append(self._point_row(pt))
        if not self._points:
            points.append(Gtk.Label(label="Aucun message.", margin_top=8, margin_bottom=8,
                                    xalign=0, margin_start=8))
        self.content.append(points)

    @staticmethod
    def _title(text):
        lab = Gtk.Label(label=text, xalign=0)
        lab.add_css_class("heading")
        return lab

    def _file_row(self, ch):
        row = Adw.ActionRow(title=os.path.basename(ch.path), subtitle=ch.path)
        row.set_subtitle_lines(1)
        diff = Gtk.Button(label="Voir le diff", valign=Gtk.Align.CENTER)
        diff.connect("clicked", lambda _b, ch=ch: self.emit(
            "show-diff", ch.path, (ch.before or b"").decode("utf-8", "replace"),
            (ch.now or b"").decode("utf-8", "replace")))
        undo = Gtk.Button(label="Annuler ce fichier", valign=Gtk.Align.CENTER)
        undo.add_css_class("destructive-action")
        undo.connect("clicked", lambda _b, p=ch.path: self.undo_file(p))
        for b in (diff, undo):
            row.add_suffix(b)
            self._buttons.append(b)
        return row

    def _point_row(self, pt):
        row = Adw.ActionRow(title=_shown(pt.text), subtitle=_hhmm(pt.time))
        row.set_title_lines(1)
        back = Gtk.Button(label="Revenir à avant ce message", valign=Gtk.Align.CENTER)
        back.connect("clicked", lambda _b, mid=pt.message_id: self.emit("rewind-requested", mid))
        row.add_suffix(back)
        self._buttons.append(back)
        return row

    # ---- accès pour les tests et l'espace de session -------------------------------------

    def loaded(self):
        return self._loaded

    def unknown_format(self):
        return self._unknown

    def file_paths(self):
        return [c.path for c in self._changes]

    def checkpoints(self):
        return list(self._points)

    def has_actions(self):
        return bool(self._buttons)

    # ---- annulation ---------------------------------------------------------------------

    def _confirm(self, heading, body, label, yes):
        """Demande confirmation (remplacé dans les tests)."""
        d = Adw.AlertDialog(heading=heading, body=body)
        d.add_response("cancel", "Annuler")
        d.add_response("ok", label)
        d.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: yes() if r == "ok" else None)
        d.present(self.get_root())

    def undo_file(self, path):
        ch = next((c for c in self._changes if c.path == path), None)
        if ch is None:
            return
        what = "Le fichier sera supprimé (Claude l'a créé)." if ch.before is None else \
            "Le fichier reviendra à son état d'avant la session."

        def go():
            def work():
                file_history.apply([file_history.Step(ch.path, ch.before, False)])
            in_thread(work, lambda _r: (self.refresh(), self.emit("changed")))
        self._confirm(f"Annuler les changements de {os.path.basename(path)} ?", what + " C'est définitif.",
                      "Annuler ce fichier", go)
