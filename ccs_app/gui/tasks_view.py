"""File de tâches Claude pour l'onglet Planning : liste, ajout, annulation, journal en direct.

`TasksView(on_resume=None, window=None)` est un `Gtk.Box` à placer dans l'onglet Planning :
- `on_resume(task)` : rappel fourni par l'application, appelé par « Reprendre dans un onglet »
  (la conversation `task.session_id` dans `task.cwd`) ; sans rappel, le bouton est caché ;
- `window` : objet avec `toast(texte)` (facultatif) ;
- `refresh()` relit les tâches (appelé toutes les 2 s tant que la vue est affichée, et par
  l'application quand elle le veut) ; `show_task(id)` sélectionne une tâche et ouvre son journal
  (clic sur la notification de fin).

`NewTaskDialog(on_ok, default_cwd=None)` renvoie à `on_ok` un dict (message, cwd, model, rights,
when) que la vue passe à `tasks.add`. Le dialogue n'écrit rien lui-même.
"""

import os

from gi.repository import Adw, Gio, GLib, GObject, Gtk, Pango

from .. import core, launch_options, task_runner, tasks
from .common import caption, clear, short_path

REFRESH_MS = 2000
LOG_LINES = 400

DANGER_TITLE = "Claude pourra tout faire sans rien demander"
DANGER_TEXT = ("« Tout » lance la tâche sans aucune vérification, sans personne devant l'écran : "
               "à réserver à un dossier jetable ou à une machine isolée.")
WHEN_CHOICES = (("Dès qu'il y a du quota", "quota"), ("Cette nuit (meilleur créneau)", "nuit"),
                ("À une heure précise…", "heure"))
RIGHTS_ORDER = ("lecture", "modifications", "tout")
RIGHTS_HELP = {"lecture": "Claude lit et analyse ; tout ce qui demande une permission est refusé.",
               "modifications": "Claude modifie les fichiers du dossier sans demander ; le reste est refusé.",
               "tout": DANGER_TEXT}
STATE_ICONS = {tasks.QUEUED: "alarm-symbolic", tasks.RUNNING: "media-playback-start-symbolic",
               tasks.WAITING: "media-playback-pause-symbolic", tasks.DONE: "emblem-ok-symbolic",
               tasks.FAILED: "dialog-error-symbolic", tasks.CANCELLED: "process-stop-symbolic"}


def row_subtitle(task):
    """Deuxième ligne d'une tâche : état, motif d'attente ou durée et coût, dossier."""
    parts = [tasks.STATE_LABELS[task.state]]
    if task.state in (tasks.QUEUED, tasks.WAITING):
        parts.append(task.note or tasks.when_text(task))
    else:
        extra = tasks.summary(task) or (task.error or "")
        if extra:
            parts.append(extra)
    parts.append(short_path(task.cwd))
    return " · ".join(parts)


class NewTaskDialog(Adw.Dialog):
    """Dialogue « Nouvelle tâche » : message, dossier, modèle, droits, moment."""

    def __init__(self, on_ok, default_cwd=None):
        super().__init__(title="Nouvelle tâche", content_width=520, content_height=680)
        self.on_ok = on_ok
        self.folder = os.path.abspath(os.path.expanduser(default_cwd or str(core.paths().home)))

        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        cancel = Gtk.Button(label="Annuler")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)
        self.ok_btn = Gtk.Button(label="Ajouter", css_classes=["suggested-action"])
        self.ok_btn.connect("clicked", self.on_add)
        header.pack_end(self.ok_btn)

        page = Adw.PreferencesPage()
        what = Adw.PreferencesGroup(title="Tâche", description="Claude l'exécutera sans fenêtre, "
                                    "avec le compte actif, et te préviendra à la fin.")
        self.message = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8,
                                    left_margin=10, right_margin=10, accepts_tab=False)
        self.message.get_buffer().connect("changed", lambda *_: self.update())
        frame = Gtk.ScrolledWindow(min_content_height=120, css_classes=["card"],
                                   hscrollbar_policy=Gtk.PolicyType.NEVER)
        frame.set_child(self.message)
        what.add(frame)
        self.folder_row = Adw.ActionRow(title="Dossier", subtitle=short_path(self.folder))
        choose = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                            tooltip_text="Choisir un autre dossier…")
        choose.connect("clicked", self.on_choose_folder)
        self.folder_row.add_suffix(choose)
        what.add(self.folder_row)
        page.add(what)

        how = Adw.PreferencesGroup(title="Options de Claude Code")
        self.model_row = Adw.ComboRow(title="Modèle", model=Gtk.StringList.new(
            [label for label, _v in launch_options.MODELS]))
        how.add(self.model_row)
        self.rights_row = Adw.ComboRow(title="Droits", model=Gtk.StringList.new(
            [tasks.RIGHTS_LABELS[r] for r in RIGHTS_ORDER]))
        self.rights_row.set_selected(RIGHTS_ORDER.index(tasks.DEFAULT_RIGHTS))
        self.rights_row.connect("notify::selected", lambda *_: self.update())
        how.add(self.rights_row)
        self.danger_row = Adw.ActionRow(title=DANGER_TITLE, subtitle=DANGER_TEXT, subtitle_lines=0)
        self.danger_row.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic", css_classes=["error"]))
        how.add(self.danger_row)
        page.add(how)

        when = Adw.PreferencesGroup(title="Moment")
        self.when_row = Adw.ComboRow(title="Quand", model=Gtk.StringList.new([l for l, _v in WHEN_CHOICES]))
        self.when_row.connect("notify::selected", lambda *_: self.update())
        when.add(self.when_row)
        self.time_row = Adw.EntryRow(title="Heure (HH:MM)", text="")
        self.time_row.connect("changed", lambda *_: self.update())
        when.add(self.time_row)
        page.add(when)

        view = Adw.ToolbarView(content=page)
        view.add_top_bar(header)
        self.set_child(view)
        self.set_default_widget(self.ok_btn)
        self.update()

    # ---- valeurs ---------------------------------------------------------------------

    def text(self):
        buf = self.message.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()

    def rights(self):
        i = self.rights_row.get_selected()
        return RIGHTS_ORDER[i] if 0 <= i < len(RIGHTS_ORDER) else tasks.DEFAULT_RIGHTS

    def model(self):
        i = self.model_row.get_selected()
        return launch_options.MODELS[i][1] if 0 <= i < len(launch_options.MODELS) else None

    def when(self):
        """`quota`, `nuit` ou `HH:MM` ; None si l'heure saisie est invalide."""
        i = self.when_row.get_selected()
        kind = WHEN_CHOICES[i][1] if 0 <= i < len(WHEN_CHOICES) else "quota"
        if kind != "heure":
            return kind
        try:
            return tasks.normalize_when(self.time_row.get_text())
        except ValueError:
            return None

    def values(self):
        return {"message": self.text(), "cwd": self.folder, "model": self.model(),
                "rights": self.rights(), "when": self.when()}

    def update(self):
        self.danger_row.set_visible(self.rights() == "tout")
        timed = WHEN_CHOICES[self.when_row.get_selected()][1] == "heure"
        self.time_row.set_visible(timed)
        when = self.when()
        bad_time = timed and when in (None, "quota", "nuit")
        self.time_row.set_css_classes(["error"] if timed and self.time_row.get_text() and bad_time else [])
        self.ok_btn.set_sensitive(bool(self.text()) and os.path.isdir(self.folder) and not bad_time)

    # ---- actions ---------------------------------------------------------------------

    def on_choose_folder(self, *_):
        dialog = Gtk.FileDialog(title="Dossier de la tâche", accept_label="Choisir", modal=True)
        if os.path.isdir(self.folder):
            dialog.set_initial_folder(Gio.File.new_for_path(self.folder))

        def done(d, result):
            try:
                chosen = d.select_folder_finish(result)
            except GLib.Error:
                return
            if chosen is not None and chosen.get_path():
                self.folder = chosen.get_path()
                self.folder_row.set_subtitle(short_path(self.folder))
                self.update()
        dialog.select_folder(self.get_root(), None, done)

    def on_add(self, *_):
        if not self.ok_btn.get_sensitive():
            return
        values = self.values()
        self.close()
        self.on_ok(values)


class TasksView(Gtk.Box):
    def __init__(self, on_resume=None, window=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["ccs-card"])
        self.on_resume = on_resume
        self.window = window
        self.selected = None
        self.log_pos = 0
        self.timer = 0
        self.tasks = []

        head = Gtk.Box(spacing=8, tooltip_text="Des messages que Claude traite sans fenêtre, quand il y a "
                       "du quota ou de nuit, avec le compte actif. Une seule tâche à la fois, jamais "
                       "pendant une pause.")
        head.append(Gtk.Label(label="Tâches Claude", xalign=0, css_classes=["heading"]))
        # Sans tâche : une ligne, pas un grand écran vide (l'Accueil reste court).
        self.empty = caption("Aucune tâche en attente. « + » ou « ccs tache ajouter \"…\" » en ajoute une, "
                             "traitée sans fenêtre quand il y a du quota.")
        self.empty.set_hexpand(True)
        head.append(self.empty)
        filler = Gtk.Box(hexpand=True)
        head.append(filler)
        self.empty.bind_property("visible", filler, "visible", GObject.BindingFlags.SYNC_CREATE
                                 | GObject.BindingFlags.INVERT_BOOLEAN)
        self.add_btn = Gtk.Button(icon_name="list-add-symbolic", css_classes=["flat"], tooltip_text="Nouvelle tâche…",
                                  valign=Gtk.Align.CENTER)
        self.add_btn.connect("clicked", self.on_new)
        head.append(self.add_btn)
        self.append(head)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"], visible=False)
        self.append(self.list)

        self.detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, visible=False)
        bar = Gtk.Box(spacing=6)
        self.detail_title = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                                      css_classes=["heading"])
        bar.append(self.detail_title)
        self.resume_btn = Gtk.Button(label="Reprendre dans un onglet")
        self.resume_btn.connect("clicked", self.on_resume_clicked)
        bar.append(self.resume_btn)
        self.cancel_btn = Gtk.Button(label="Annuler la tâche", css_classes=["destructive-action"])
        self.cancel_btn.connect("clicked", self.on_cancel)
        bar.append(self.cancel_btn)
        self.delete_btn = Gtk.Button(label="Supprimer")
        self.delete_btn.connect("clicked", self.on_delete)
        bar.append(self.delete_btn)
        close = Gtk.Button(icon_name="window-close-symbolic", css_classes=["flat"], tooltip_text="Fermer le journal")
        close.connect("clicked", lambda *_: self.show_task(None))
        bar.append(close)
        self.detail.append(bar)
        self.log = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=6, bottom_margin=6,
                                left_margin=8, right_margin=8)
        scroll = Gtk.ScrolledWindow(min_content_height=220, max_content_height=360, propagate_natural_height=True,
                                    css_classes=["card"], hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(self.log)
        self.log_scroll = scroll
        self.detail.append(scroll)
        self.append(self.detail)

        self.connect("map", lambda *_: self.start_timer())
        self.connect("unmap", lambda *_: self.stop_timer())
        self.refresh()

    # ---- rafraîchissement --------------------------------------------------------------

    def start_timer(self):
        self.refresh()
        if not self.timer:
            self.timer = GLib.timeout_add(REFRESH_MS, self.tick)

    def stop_timer(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0

    def tick(self):
        self.refresh()
        return True

    def toast(self, text):
        if self.window is not None and hasattr(self.window, "toast"):
            self.window.toast(text)

    def refresh(self):
        try:
            current = tasks.all()
        except OSError:
            current = []
        if [t.to_dict() for t in current] != [t.to_dict() for t in self.tasks]:
            self.tasks = current
            self.render()
        self.update_detail()

    def render(self):
        clear(self.list)
        self.empty.set_visible(not self.tasks)
        self.list.set_visible(bool(self.tasks))   # liste vide : pas de cadre vide
        for t in reversed(self.tasks):
            row = Adw.ActionRow(title=GLib.markup_escape_text(" ".join(t.message.split())[:90]),
                                subtitle=GLib.markup_escape_text(row_subtitle(t)), activatable=True,
                                title_lines=1, subtitle_lines=2)
            row.set_name(f"task-{t.id}")
            row.add_prefix(Gtk.Image(icon_name=STATE_ICONS.get(t.state, "alarm-symbolic")))
            if t.id == self.selected:
                row.add_css_class("ccs-highlight")
            row.connect("activated", lambda _r, tid=t.id: self.show_task(tid))
            self.list.append(row)

    # ---- détail et journal --------------------------------------------------------------

    def task(self, task_id):
        return next((t for t in self.tasks if t.id == task_id), None)

    def show_task(self, task_id):
        """Sélectionne la tâche et affiche son journal (None : ferme le journal)."""
        if task_id is not None and self.task(str(task_id)) is None:
            self.refresh()
            if self.task(str(task_id)) is None:
                return False
        self.selected = None if task_id is None else str(task_id)
        self.log_pos = 0
        self.log.get_buffer().set_text("")
        self.render()
        self.update_detail()
        return True

    def update_detail(self):
        t = self.task(self.selected) if self.selected else None
        if t is None:
            self.selected = None
            self.detail.set_visible(False)
            return
        self.detail.set_visible(True)
        self.detail_title.set_label(f"Tâche {t.id} · {tasks.STATE_LABELS[t.state]}")
        self.cancel_btn.set_visible(t.state in tasks.ACTIVE)
        self.delete_btn.set_visible(t.state in tasks.FINISHED)
        self.resume_btn.set_visible(self.on_resume is not None and bool(t.session_id)
                                    and t.state in (tasks.DONE, tasks.FAILED, tasks.CANCELLED))
        self.read_log(t)

    def read_log(self, task):
        """Ajoute au journal affiché les lignes complètes écrites depuis la dernière lecture."""
        try:
            with open(tasks.journal_path(task.id), "rb") as f:
                f.seek(self.log_pos)
                data = f.read()
        except OSError:
            return
        cut = data.rfind(b"\n") + 1
        if not cut:
            return
        self.log_pos += cut
        lines = [task_runner.readable(raw.decode("utf-8", "replace")) for raw in data[:cut].splitlines()]
        text = "\n".join(x for x in lines if x)
        if not text:
            return
        buf = self.log.get_buffer()
        buf.insert(buf.get_end_iter(), text + "\n")
        extra = buf.get_line_count() - LOG_LINES
        if extra > 0:
            buf.delete(buf.get_start_iter(), buf.get_iter_at_line(extra))
        adj = self.log_scroll.get_vadjustment()
        GLib.idle_add(lambda: (adj.set_value(adj.get_upper() - adj.get_page_size()), False)[1])

    # ---- actions -----------------------------------------------------------------------

    def on_new(self, *_):
        default = self.task(self.selected).cwd if self.selected and self.task(self.selected) else None
        NewTaskDialog(self.add_task, default).present(self.get_root())

    def add_task(self, values):
        try:
            t = tasks.add(**values)
        except (ValueError, OSError) as e:
            self.toast(f"Tâche non ajoutée : {e}")
            return None
        self.toast(f"Tâche {t.id} ajoutée")
        self.refresh()
        return t

    def on_cancel(self, *_):
        if not self.selected:
            return
        try:
            tasks.cancel(self.selected)
        except (ValueError, OSError) as e:
            self.toast(str(e))
        self.refresh()

    def on_delete(self, *_):
        if not self.selected:
            return
        tid = self.selected
        try:
            tasks.remove(tid)
        except (ValueError, OSError) as e:
            self.toast(str(e))
            return
        self.selected = None
        self.refresh()
        self.toast(f"Tâche {tid} supprimée")

    def on_resume_clicked(self, *_):
        t = self.task(self.selected) if self.selected else None
        if t is not None and t.session_id and self.on_resume is not None:
            self.on_resume(t)
