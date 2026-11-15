"""Changements en cours d'un dépôt : indexer (fichier ou lignes), annuler, commiter."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GObject, Gtk

from .. import git_repo
from .common import in_thread
from .git_commit_view import DiffLinesView

_LETTERS = {"M": "modifié", "A": "ajouté", "D": "supprimé", "R": "renommé", "C": "copié",
            "T": "type changé", "?": "nouveau", "U": "conflit"}


def hscroll(child):
    """Rangée de boutons qui défile au lieu d'imposer sa largeur au panneau."""
    sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                            vscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True)
    sw.set_child(child)
    return sw


class ChangesView(Gtk.Box):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "error": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, repo, git=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.repo = repo
        self.git = git if git is not None else git_repo   # source distante : `remote.workspace`
        self._status = []
        self._busy = 0
        self._current = None          # (chemin, indexé) du fichier dont on voit le diff
        self._diff_view = None
        self._rebuilding = False
        self.set_margin_start(6)
        self.set_margin_end(6)
        self.set_margin_top(6)

        self.staged_list = self._new_list()
        self.unstaged_list = self._new_list()
        self.staged_list.connect("row-selected", lambda lb, r: self._on_row(lb, r, True))
        self.unstaged_list.connect("row-selected", lambda lb, r: self._on_row(lb, r, False))

        self.append(self._title("Indexé"))
        self.append(self._scroll(self.staged_list))
        head = Gtk.Box(spacing=6)
        head.append(self._title("Non indexé", hexpand=True))
        self.btn_all = Gtk.Button(label="Tout indexer")
        self.btn_all.connect("clicked", lambda _b: self.stage_all())
        head.append(self.btn_all)
        self.append(head)
        self.append(self._scroll(self.unstaged_list))

        bar = Gtk.Box(spacing=6)
        self.btn_stage_sel = Gtk.Button(label="Indexer la sélection", sensitive=False)
        self.btn_unstage_sel = Gtk.Button(label="Désindexer la sélection", sensitive=False)
        self.btn_discard_sel = Gtk.Button(label="Annuler la sélection", sensitive=False)
        self.btn_discard_sel.add_css_class("destructive-action")
        self.btn_stage_sel.connect("clicked", lambda _b: self.stage_selection())
        self.btn_unstage_sel.connect("clicked", lambda _b: self.unstage_selection())
        self.btn_discard_sel.connect("clicked", lambda _b: self.discard_selection())
        for b in (self.btn_stage_sel, self.btn_unstage_sel, self.btn_discard_sel):
            bar.append(b)
        self.btn_discard_sel.set_visible(self.can("discard_lines"))
        self.append(hscroll(bar))
        self.diff_holder = Gtk.ScrolledWindow(vexpand=True, hexpand=True,
                                              min_content_height=120)
        self.append(self.diff_holder)

        self.msg = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=4,
                                bottom_margin=4, left_margin=6, right_margin=6)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_message_key)
        self.msg.add_controller(keys)
        frame = Gtk.ScrolledWindow(min_content_height=70, max_content_height=140,
                                   propagate_natural_height=True)
        frame.add_css_class("card")
        frame.set_child(self.msg)
        self.append(frame)
        row = Gtk.Box(spacing=6)
        self.amend = Gtk.CheckButton(label="Modifier le dernier commit")
        self.amend.connect("toggled", self._on_amend)
        row.append(self.amend)
        row.append(Gtk.Box(hexpand=True))
        self.btn_propose = Gtk.Button(label="Proposer")
        self.btn_propose.connect("clicked", lambda _b: self.propose())
        row.append(self.btn_propose)
        self.btn_commit = Gtk.Button(label="Commit")
        self.btn_commit.add_css_class("suggested-action")
        self.btn_commit.connect("clicked", lambda _b: self.commit())
        row.append(self.btn_commit)
        self.append(hscroll(row))

    # ---- construction -------------------------------------------------------------------

    @staticmethod
    def _title(text, hexpand=False):
        lab = Gtk.Label(label=text, xalign=0, hexpand=hexpand)
        lab.add_css_class("heading")
        return lab

    @staticmethod
    def _new_list():
        lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        lb.add_css_class("boxed-list")
        return lb

    @staticmethod
    def _scroll(child):
        sw = Gtk.ScrolledWindow(min_content_height=48, max_content_height=170,
                                propagate_natural_height=True)
        sw.set_child(child)
        return sw

    def can(self, name):
        """La source sait-elle faire `name` (une session distante n'annule rien, n'ignore rien) ?"""
        return callable(getattr(self.git, name, None))

    # ---- travail en fil -----------------------------------------------------------------

    def busy(self):
        return self._busy > 0

    def _job(self, work, then=None, write=False):
        """`work()` hors de l'interface ; erreur git → signal « error » ; sinon `then`,
        et pour une écriture : signal « changed » puis rafraîchissement."""
        self._busy += 1

        def run():
            try:
                return work()
            except git_repo.GitError as e:
                return e

        def done(result):
            try:
                if isinstance(result, git_repo.GitError):
                    self.emit("error", result)
                    self.refresh()
                    return
                if then:
                    then(result)
                if write:
                    self.emit("changed")
                    self.refresh()
            finally:
                self._busy -= 1
        in_thread(run, done)

    def _confirm(self, heading, body, label, yes):
        """Demande confirmation (remplacé dans les tests)."""
        d = Adw.AlertDialog(heading=heading, body=body)
        d.add_response("cancel", "Annuler")
        d.add_response("ok", label)
        d.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: yes() if r == "ok" else None)
        d.present(self.get_root())

    # ---- état ---------------------------------------------------------------------------

    def refresh(self):
        self._job(lambda: self.git.status(self.repo), self._apply_status)

    def staged_files(self):
        return [s for s in self._status if s.staged not in (".", "?")]

    def unstaged_files(self):
        return [s for s in self._status if s.unstaged != "."]

    def _apply_status(self, status):
        self._status = status
        self._rebuilding = True
        try:
            self._fill(self.staged_list, self.staged_files(), True)
            self._fill(self.unstaged_list, self.unstaged_files(), False)
        finally:
            self._rebuilding = False
        cur = self._current
        if cur is not None:
            present = any(s.path == cur[0] for s in (
                self.staged_files() if cur[1] else self.unstaged_files()))
            if present:
                self.select_file(*cur, force=True)
            else:
                self._current = None
                self._show_diff(None, False)
        self.btn_all.set_sensitive(bool(self.unstaged_files()))

    def _fill(self, lb, files, staged):
        while (r := lb.get_row_at_index(0)) is not None:
            lb.remove(r)
        for fs in files:
            row = Gtk.ListBoxRow()
            row.path = fs.path
            box = Gtk.Box(spacing=8, margin_top=2, margin_bottom=2, margin_start=4,
                          margin_end=6)
            check = Gtk.CheckButton(active=staged)
            check.connect("toggled", lambda c, p=fs.path: self.set_staged(p, c.get_active()))
            box.append(check)
            letter = fs.staged if staged else fs.unstaged
            name = fs.path if not fs.orig_path else f"{fs.orig_path} → {fs.path}"
            box.append(Gtk.Label(label=name, xalign=0, hexpand=True, ellipsize=3))
            tag = Gtk.Label(label=_LETTERS.get(letter, letter))
            tag.add_css_class("dim-label")
            box.append(tag)
            row.set_child(box)
            if not (self.can("discard_file") or self.can("ignore")):
                lb.append(row)
                continue
            click = Gtk.GestureClick(button=3)
            click.connect("pressed", lambda g, _n, x, y, row=row, fs=fs:
                          self._context_menu(row, fs, x, y))
            row.add_controller(click)
            lb.append(row)

    def _context_menu(self, row, fs, x, y):
        pop = Gtk.Popover()
        pop.set_parent(row)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for label, action, need in (
                ("Annuler les modifications", lambda: self.discard_file(fs.path), "discard_file"),
                ("Ajouter au .gitignore", lambda: self.ignore_file(fs.path), "ignore")):
            if not self.can(need):
                continue
            b = Gtk.Button(label=label)
            b.add_css_class("flat")
            b.connect("clicked", lambda _b, a=action: (pop.popdown(), a()))
            box.append(b)
        pop.set_child(box)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        pop.set_pointing_to(rect)
        pop.popup()

    # ---- sélection d'un fichier et diff -------------------------------------------------

    def _on_row(self, lb, row, staged):
        if self._rebuilding or row is None:
            return
        self.select_file(row.path, staged)

    def select_file(self, path, staged, force=False):
        if self._current == (path, staged) and not force and self._diff_view is not None:
            return
        self._current = (path, staged)
        other = self.unstaged_list if staged else self.staged_list
        mine = self.staged_list if staged else self.unstaged_list
        self._rebuilding = True
        try:
            other.unselect_all()
            i = 0
            while (r := mine.get_row_at_index(i)) is not None:
                if r.path == path:
                    mine.select_row(r)
                i += 1
        finally:
            self._rebuilding = False
        self._job(lambda: self.git.diff(self.repo, path, staged),
                  lambda fd: self._show_diff(fd, staged))

    def _show_diff(self, fd, staged):
        if self._current is None or fd is None:
            self._diff_view = None
            self.diff_holder.set_child(None)
        else:
            if self._current[1] != staged:
                return          # réponse périmée
            self._diff_view = DiffLinesView(fd, selectable=True)
            self._diff_view.connect("selection-changed", lambda _v: self._update_buttons())
            self.diff_holder.set_child(self._diff_view)
        self._update_buttons()

    def diff_view(self):
        return self._diff_view

    def _update_buttons(self):
        has = self._diff_view is not None and bool(self._diff_view.selected())
        staged = bool(self._current and self._current[1])
        self.btn_stage_sel.set_sensitive(has and not staged)
        self.btn_discard_sel.set_sensitive(has and not staged)
        self.btn_unstage_sel.set_sensitive(has and staged)

    # ---- écritures ----------------------------------------------------------------------

    def set_staged(self, path, flag):
        if self._rebuilding:
            return
        fn = self.git.stage_file if flag else self.git.unstage_file
        self._job(lambda: fn(self.repo, path), write=True)

    def stage_all(self):
        paths = [s.path for s in self.unstaged_files()]
        self._job(lambda: [self.git.stage_file(self.repo, p) for p in paths], write=True)

    def _selection(self):
        if self._diff_view is None or not self._diff_view.selected():
            return None
        return self._diff_view.fd, self._diff_view.selected()

    def stage_selection(self):
        sel = self._selection()
        if sel:
            self._job(lambda: self.git.stage_lines(self.repo, *sel), write=True)

    def unstage_selection(self):
        sel = self._selection()
        if sel:
            self._job(lambda: self.git.unstage_lines(self.repo, *sel), write=True)

    def discard_selection(self):
        sel = self._selection()
        if sel and self.can("discard_lines"):
            self._confirm("Annuler la sélection ?",
                          "Les lignes choisies seront remises dans leur état du dernier commit. "
                          "C'est définitif.", "Annuler les lignes",
                          lambda: self._job(lambda: self.git.discard_lines(self.repo, *sel),
                                            write=True))

    def discard_file(self, path):
        fs = next((s for s in self._status if s.path == path), None)
        if fs is None or not self.can("discard_file"):
            return
        self._confirm(f"Annuler les modifications de {path} ?",
                      "Le fichier revient à son état du dernier commit. C'est définitif.",
                      "Annuler les modifications",
                      lambda: self._job(lambda: self.git.discard_file(self.repo, fs),
                                        write=True))

    def ignore_file(self, path):
        if self.can("ignore"):
            self._job(lambda: self.git.ignore(self.repo, path), write=True)

    # ---- message et commit --------------------------------------------------------------

    def message(self):
        buf = self.msg.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def set_message(self, text):
        self.msg.get_buffer().set_text(text)

    def set_amend(self, flag):
        self.amend.set_active(flag)

    def _on_amend(self, check):
        if check.get_active():
            self._job(lambda: self.git.last_message(self.repo), self.set_message)
        else:
            self.set_message("")

    def propose(self):
        self._job(lambda: self.git.propose_message(self.repo),
                  lambda text: text and self.set_message(text))

    def commit(self):
        message, amend = self.message(), self.amend.get_active()

        def after(_cid):
            self.set_message("")
            if self.amend.get_active():
                self.amend.set_active(False)
                self.set_message("")
        self._job(lambda: self.git.commit(self.repo, message, amend=amend), after, write=True)

    def on_message_key(self, _ctrl, keyval, _keycode, state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) \
                and state & Gdk.ModifierType.CONTROL_MASK:
            self.commit()
            return True
        return False
