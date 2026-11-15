"""Détail d'un commit et affichage d'un diff dont on peut choisir les lignes."""

import time
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GObject, Gtk, Pango

from .. import git_repo
from ..conversations import ago
from .common import in_thread

MAX_LINES = 3000
CSS = b"""
.ccs-diff-line { font-family: monospace; padding: 0 6px; }
.ccs-diff-add { background: alpha(#2ec27e, 0.18); }
.ccs-diff-del { background: alpha(#e01b24, 0.16); }
.ccs-diff-hunk { background: alpha(#3584e4, 0.15); font-weight: bold; }
.ccs-diff-selected { background: alpha(#f5c211, 0.45); }
.ccs-diff-no { color: alpha(currentColor, 0.5); min-width: 3em; }
"""
_css_done = False


def _ensure_css():
    global _css_done
    if _css_done:
        return
    display = Gdk.Display.get_default()
    if display is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS, -1)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_done = True


class DiffLinesView(Gtk.Box):
    """Les blocs d'un fichier, ligne par ligne. Si `selectable` : clic = une ligne,
    Maj+clic = plage, clic sur l'en-tête d'un bloc = tout le bloc."""

    __gsignals__ = {"selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, fd, selectable=False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        _ensure_css()
        self.fd = fd
        self.selectable = selectable
        self._sel = set()
        self._anchor = None
        self._rows = {}           # (bloc, ligne) → widget
        if fd.binary:
            self.append(Gtk.Label(label="Fichier binaire", xalign=0, margin_start=8,
                                  margin_top=8))
            return
        shown = 0
        for hi, h in enumerate(fd.hunks):
            head = Gtk.Label(label=h.header, xalign=0, ellipsize=Pango.EllipsizeMode.END)
            head.add_css_class("ccs-diff-line")
            head.add_css_class("ccs-diff-hunk")
            self._clickable(head, lambda shift, hi=hi: self.click_header(hi))
            self.append(head)
            for li, l in enumerate(h.lines):
                if shown >= MAX_LINES:
                    self.append(Gtk.Label(label="… diff tronqué", xalign=0, margin_start=8))
                    return
                shown += 1
                row = Gtk.Box()
                row.add_css_class("ccs-diff-line")
                if l.kind == "+":
                    row.add_css_class("ccs-diff-add")
                elif l.kind == "-":
                    row.add_css_class("ccs-diff-del")
                for no in (l.old_no, l.new_no):
                    n = Gtk.Label(label="" if no is None else str(no), xalign=1)
                    n.add_css_class("ccs-diff-no")
                    row.append(n)
                row.append(Gtk.Label(label=f" {l.kind} {l.text}", xalign=0, hexpand=True))
                if l.kind != " ":
                    self._clickable(row, lambda shift, hi=hi, li=li: self.click_line(
                        hi, li, shift=shift))
                self._rows[(hi, li)] = row
                self.append(row)

    def _clickable(self, widget, action):
        if not self.selectable:
            return
        click = Gtk.GestureClick()

        def pressed(gesture, _n, _x, _y):
            state = gesture.get_current_event_state()
            action(bool(state & Gdk.ModifierType.SHIFT_MASK))
        click.connect("pressed", pressed)
        widget.add_controller(click)

    # ---- sélection ----------------------------------------------------------------------

    def _changed(self):
        return [(hi, li) for hi, h in enumerate(self.fd.hunks)
                for li, l in enumerate(h.lines) if l.kind != " "]

    def _paint(self):
        for key, row in self._rows.items():
            if key in self._sel:
                row.add_css_class("ccs-diff-selected")
            else:
                row.remove_css_class("ccs-diff-selected")
        self.emit("selection-changed")

    def click_line(self, hi, li, shift=False):
        if not self.selectable or self.fd.hunks[hi].lines[li].kind == " ":
            return
        key = (hi, li)
        if shift and self._anchor is not None:
            order = self._changed()
            a, b = order.index(self._anchor), order.index(key)
            self._sel = set(order[min(a, b):max(a, b) + 1])
        elif self._sel == {key}:
            self._sel = set()
            self._anchor = None
        else:
            self._sel = {key}
            self._anchor = key
        self._paint()

    def click_header(self, hi):
        if not self.selectable:
            return
        self._sel = {(hi, li) for li, l in enumerate(self.fd.hunks[hi].lines)
                     if l.kind != " "}
        self._anchor = None
        self._paint()

    def selected(self):
        return set(self._sel)


def _date(ts):
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M") + f" ({ago(ts, time.time())})"


class CommitView(Gtk.Box):
    """Sujet, corps, auteur, date, parents cliquables, fichiers et diff du fichier choisi."""

    __gsignals__ = {
        "commit-activated": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, repo, cid, git=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.repo = repo
        self.cid = cid
        self.git = git if git is not None else git_repo   # source distante : `remote.workspace`
        self._commit = None
        self._diffs = []
        self._parent_buttons = []
        self._loaded = False
        self.set_margin_top(6)
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.title = Gtk.Label(xalign=0, wrap=True, selectable=True, label="Chargement…")
        self.title.add_css_class("title-3")
        self.append(self.title)
        self.meta = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.meta.add_css_class("dim-label")
        self.append(self.meta)
        self.body = Gtk.Label(xalign=0, wrap=True, selectable=True, visible=False)
        self.append(self.body)
        self.parents_box = Gtk.Box(spacing=6)
        self.append(self.parents_box)
        self.files_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.files_list.add_css_class("boxed-list")
        self.files_list.connect("row-selected", self._on_row)
        scroll_files = Gtk.ScrolledWindow(min_content_height=80, max_content_height=160,
                                          propagate_natural_height=True)
        scroll_files.set_child(self.files_list)
        self.append(scroll_files)
        self.diff_holder = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self.append(self.diff_holder)
        in_thread(self._read, self._show)

    def _read(self):
        try:
            return self.git.show(self.repo, self.cid)
        except git_repo.GitError as e:
            return e

    def _show(self, result):
        self._loaded = True
        if isinstance(result, Exception):
            self.title.set_label("Commit introuvable")
            self.meta.set_label(getattr(result, "output", str(result)))
            return
        c, diffs = result
        self._commit, self._diffs = c, diffs
        self.title.set_label(c.subject)
        self.meta.set_label(f"{c.author} <{c.email}> · {_date(c.time)} · {c.id[:7]}")
        if c.body.strip():
            self.body.set_label(c.body.strip())
            self.body.set_visible(True)
        if c.parents:
            self.parents_box.append(Gtk.Label(label="Parents :"))
        for p in c.parents:
            b = Gtk.Button(label=p[:7])
            b.add_css_class("flat")
            b.connect("clicked", lambda _b, p=p: self.emit("commit-activated", p))
            self._parent_buttons.append(b)
            self.parents_box.append(b)
        for fd in diffs:
            added = sum(1 for h in fd.hunks for l in h.lines if l.kind == "+")
            removed = sum(1 for h in fd.hunks for l in h.lines if l.kind == "-")
            self.files_list.append(Gtk.Label(
                label=f"{fd.path}   +{added} −{removed}", xalign=0,
                margin_start=6, margin_end=6, margin_top=3, margin_bottom=3))
        first = self.files_list.get_row_at_index(0)
        if first is not None:
            self.files_list.select_row(first)

    def _on_row(self, _lb, row):
        if row is None:
            return
        self.diff_holder.set_child(DiffLinesView(self._diffs[row.get_index()],
                                                 selectable=False))

    # ---- accès pour les tests et la page ------------------------------------------------

    def loaded(self):
        return self._loaded

    def subject(self):
        return self._commit.subject if self._commit else ""

    def files(self):
        return [fd.path for fd in self._diffs]

    def click_parent(self, i):
        self._parent_buttons[i].emit("clicked")
