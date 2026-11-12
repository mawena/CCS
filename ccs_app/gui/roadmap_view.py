"""La feuille de route d'un projet : phases, barres, cases à cocher cliquables.

Lit `ROADMAP.md` (voir `ccs_app/roadmap.py`), le suit sur le disque et le coche au clic en ne
changeant qu'un caractère. Toute lecture ou écriture de fichier passe par un fil.
"""

import weakref
from pathlib import Path

from gi.repository import Adw, Gio, GLib, Gtk

from .. import roadmap
from .common import in_thread

HIGHLIGHT_S = 20          # durée de la mise en valeur d'une case cochée par un autre
RELOAD_DELAY_MS = 150     # regroupe les rafales d'évènements du disque
OWN_WRITE_S = 2           # après un clic, les évènements du disque ne sont pas « externes »


def _version_key(version):
    return tuple(int(n) for n in "".join(c if c.isdigit() else " " for c in version).split())


def latest_version(rm):
    """Version la plus haute parmi les phases finies, sinon None."""
    found = [p.version for p in rm.phases if p.finished and p.version]
    try:
        return max(found, key=_version_key) if found else None
    except ValueError:
        return found[-1] if found else None


def gauge(done, total):
    """Barre de progression (`Gtk.LevelBar`) d'une phase."""
    bar = Gtk.LevelBar(min_value=0, max_value=max(total, 1), value=done,
                       valign=Gtk.Align.CENTER, width_request=90)
    bar.add_css_class("ccs-gauge")
    if total and done == total:
        bar.add_css_class("ccs-gauge-ok")
    return bar


class RoadmapView(Gtk.Box):
    """`RoadmapView(cwd, on_ask_create=None)`."""

    def __init__(self, cwd, on_ask_create=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, vexpand=True, hexpand=True)
        self.cwd = str(cwd)
        self.on_ask_create = on_ask_create
        self.path = None                 # ROADMAP.md trouvé, ou None
        self.roadmap = None              # dernière feuille lue, ou None
        self.loaded = False
        self.phase_rows = []             # [(Phase, Adw.ExpanderRow)]
        self.task_rows = {}              # numéro de ligne -> ligne de la tâche
        self.header_title = self.header_info = self.ask_button = None
        self.last_toast = None
        self._expanded = {}              # titre de phase -> dépliée ou non
        self._highlight = {}             # numéro de ligne -> texte de la tâche allumée
        self._own_write = False
        self._reload_id = 0
        self._loading = False
        self._again = False
        self._monitor = None
        self._monitored = None

        self.toasts = Adw.ToastOverlay(vexpand=True, hexpand=True)
        self.append(self.toasts)
        self.reload()

    # ---- chargement ---------------------------------------------------------------

    def reload(self):
        """Relit la feuille de route dans un fil, puis met l'affichage à jour."""
        if self._loading:
            self._again = True
            return
        self._loading = True

        def work():
            path = roadmap.find(self.cwd)
            rm = None
            if path is not None:
                try:
                    rm = roadmap.parse(path.read_text(encoding="utf-8", errors="replace"), path)
                except OSError:
                    path = None
            return path, rm

        in_thread(work, self._loaded)

    def _loaded(self, result):
        self._loading = False
        path, rm = result
        before = self.roadmap
        self.path, self.roadmap, self.loaded = path, rm, True
        if before is not None and rm is not None and not self._own_write:
            for task in roadmap.newly_done(before, rm):
                self._highlight[task.line] = task.text
                GLib.timeout_add_seconds(HIGHLIGHT_S, self._unlight, task.line, task.text)
        self._highlight = {n: t for n, t in self._highlight.items()
                           if rm is not None and any(x.line == n and x.text == t and x.done
                                                     for p in rm.phases for x in p.tasks)}
        self._watch()
        self._build()
        if self._again:
            self._again = False
            self.reload()

    def _unlight(self, line, text):
        if self._highlight.get(line) == text:
            del self._highlight[line]
            row = self.task_rows.get(line)
            if row is not None:
                row.remove_css_class("ccs-just-done")
        return False

    # ---- suivi du disque ------------------------------------------------------------

    def _watch(self):
        folder = self.path.parent if self.path else Path(self.cwd)
        if self._monitored == folder:
            return
        self.close()
        try:
            monitor = Gio.File.new_for_path(str(folder)).monitor_directory(
                Gio.FileMonitorFlags.WATCH_MOVES, None)
        except GLib.Error:
            return
        ref = weakref.ref(self)

        def changed(_m, file, other, _event):
            view = ref()
            if view is None:
                return
            names = {f.get_basename() for f in (file, other) if f is not None}
            if roadmap.FILENAME in names:
                view._schedule_reload()

        monitor.connect("changed", changed)
        self._monitor, self._monitored = monitor, folder

    def _schedule_reload(self):
        if self._reload_id:
            GLib.source_remove(self._reload_id)
        ref = weakref.ref(self)

        def fire():
            view = ref()
            if view is not None:
                view._reload_id = 0
                view.reload()
            return False

        self._reload_id = GLib.timeout_add(RELOAD_DELAY_MS, fire)

    def close(self):
        """Arrête le suivi du fichier."""
        if self._monitor is not None:
            self._monitor.cancel()
        self._monitor = self._monitored = None
        if self._reload_id:
            GLib.source_remove(self._reload_id)
            self._reload_id = 0

    # ---- affichage ------------------------------------------------------------------

    def toast(self, text):
        self.last_toast = text
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

    def _build(self):
        for phase, row in self.phase_rows:
            self._expanded[phase.title] = row.get_expanded()
        self.phase_rows, self.task_rows = [], {}
        self.header_title = self.header_info = self.ask_button = None
        self.toasts.set_child(self._empty() if self.roadmap is None else self._content())

    def _empty(self):
        page = Adw.StatusPage(icon_name="view-list-symbolic", vexpand=True,
                              title="Pas de feuille de route",
                              description="Ce dossier n'a pas de ROADMAP.md.")
        if self.on_ask_create is not None:
            button = Gtk.Button(label="Demander à Claude d'en créer une", halign=Gtk.Align.CENTER,
                                css_classes=["suggested-action", "pill"])
            button.connect("clicked", lambda _b: self.on_ask_create())
            page.set_child(button)
            self.ask_button = button
        return page

    def _content(self):
        rm = self.roadmap
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        finished = sum(1 for p in rm.phases if p.finished)
        name = rm.title or (self.path.parent.name if self.path else "Projet")
        self.header_title = Gtk.Label(label=name, xalign=0, wrap=True, css_classes=["title-3"])
        version = latest_version(rm)
        plural = "phase finie" if finished <= 1 else "phases finies"
        parts = ([f"version {version}"] if version else []) + \
                [f"{finished} {plural} sur {len(rm.phases)}"]
        self.header_info = Gtk.Label(label=" · ".join(parts), xalign=0,
                                     css_classes=["ccs-subtle", "dim-label"])
        box.append(self.header_title)
        box.append(self.header_info)
        listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        for phase in rm.phases:
            listbox.append(self._phase_row(phase))
        box.append(listbox)
        return Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER, child=box)

    def _phase_row(self, phase):
        row = Adw.ExpanderRow(title=GLib.markup_escape_text(phase.title))
        row.set_expanded(self._expanded.get(phase.title, not phase.finished))
        row.add_suffix(gauge(phase.done_count, phase.total))
        row.add_suffix(Gtk.Label(label=f"{phase.done_count}/{phase.total}",
                                 css_classes=["ccs-count"]))
        for task in phase.tasks:
            row.add_row(self._task_row(task))
        self.phase_rows.append((phase, row))
        return row

    def _task_row(self, task):
        row = Adw.ActionRow(title=GLib.markup_escape_text(task.text), title_lines=0)
        check = Gtk.CheckButton(active=task.done, valign=Gtk.Align.CENTER)
        row.add_prefix(check)
        if task.depth:
            check.set_margin_start(16 * task.depth)
        check.connect("toggled", self._clicked, task)
        row.set_activatable_widget(check)
        if self._highlight.get(task.line) == task.text:
            row.add_css_class("ccs-just-done")
        row.check = check
        self.task_rows[task.line] = row
        return row

    # ---- clic sur une case ----------------------------------------------------------

    def _clicked(self, _check, task):
        if self.path is None:
            return
        path = self.path
        self._own_write = True
        GLib.timeout_add_seconds(OWN_WRITE_S, self._own_done)

        def finish(ok):
            if not ok:
                self.toast("La feuille de route a changé, relue")
            self.reload()

        in_thread(lambda: roadmap.toggle(path, task.line, task.text), finish)

    def _own_done(self):
        self._own_write = False
        return False
