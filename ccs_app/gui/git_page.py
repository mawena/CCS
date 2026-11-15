"""Page Git du panneau de gauche : branche, changements, graphe, git flow, fetch, pull, push.

Dispositions (réglage `git.layout`) :
- **A** : changements puis graphe compact dans la page ; un commit s'ouvre dans la zone de droite ;
- **B** : changements seuls dans la page ; l'onglet « Historique » de la zone de droite porte
  le graphe en cartes et le détail du commit ;
- **C** : comme A avec le graphe en cartes ; `SessionWorkspace` élargit le panneau de gauche.
"""

import os
import time
import weakref

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from .. import git_repo, settings
from .common import in_thread
from .git_changes import ChangesView, hscroll
from .git_commit_view import CommitView
from .git_graph_view import GraphView

RELOAD_DELAY_MS = 300
TICK_S = 30
WATCHED_IN_GIT = {"HEAD", "index", "packed-refs", "ORIG_HEAD", "MERGE_HEAD"}
FLOW_LABELS = {"feature": "feature", "release": "release", "hotfix": "hotfix"}


def _saved_layout():
    try:
        return settings.load_settings()["git"]["layout"]
    except Exception:  # noqa: BLE001 — réglages illisibles : disposition par défaut
        return "A"


def _save_layout(layout):
    try:
        s = settings.load_settings()
        s["git"]["layout"] = layout
        settings.save_settings(s)
    except Exception:  # noqa: BLE001 — réglage non gardé : sans conséquence
        pass


def _fetch_minutes():
    try:
        return int(settings.load_settings()["git"]["fetch_minutes"])
    except Exception:  # noqa: BLE001
        return 5


class GitPage(Gtk.Box):
    """`GitPage(cwd, open_in_editor, on_layout, git=None)`. `git` : la source (le module
    `git_repo` par défaut ; `RemoteGit` pour une session distante : pas de suivi du disque, pas
    de git flow, rafraîchie par la minuterie)."""

    def __init__(self, cwd, open_in_editor, on_layout, git=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, vexpand=True, hexpand=True)
        self.root = os.fspath(cwd)
        self.git = git if git is not None else git_repo
        self.remote = bool(getattr(self.git, "remote", False))
        self._open_in_editor = open_in_editor
        self._on_layout = on_layout
        self._layout = _saved_layout() if _saved_layout() in ("A", "B", "C") else "A"
        self._error = None
        self._monitors = []
        self._reload_id = 0
        self._last_fetch = time.monotonic()
        self._flow_ok = None
        self._is_repo = None
        self._busy_ops = 0
        self._closed = False

        self.banner = Adw.Banner(revealed=False, button_label="Détails")
        self.banner.connect("button-clicked", lambda _b: self._show_details())
        self.append(self.banner)
        self.append(hscroll(self._build_header()))

        self.stack = Gtk.Stack(vexpand=True, hexpand=True)
        self.empty = Adw.StatusPage(icon_name="folder-symbolic", title="Pas un dépôt git")
        self.stack.add_named(self.empty, "empty")

        self.changes = ChangesView(self.root, git=self.git)
        self.changes.connect("error", lambda _c, e: self.show_error(e))
        self.changes.connect("changed", lambda _c: self._schedule_reload())
        self.graph = GraphView("cards" if self._layout == "C" else "compact", git=self.git)
        self.graph.connect("commit-activated", lambda _g, cid: self.open_commit(cid))
        self.graph.set_size_request(-1, 160)
        self.split = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL, wide_handle=True,
                               vexpand=True, hexpand=True, shrink_start_child=False,
                               shrink_end_child=False)
        self.split.set_start_child(self.changes)
        self.split.set_end_child(self.graph)
        self.stack.add_named(self.split, "main")
        self.stack.set_visible_child_name("main")
        self.append(self.stack)
        self._apply_layout_widgets()

        ref = weakref.ref(self)

        def tick():
            page = ref()
            return page._tick() if page is not None and not page._closed else False
        self._timer = GLib.timeout_add_seconds(TICK_S, tick)
        self.connect("destroy", lambda *_: self.close())
        self.refresh(full=True)
        self._watch()

    # ---- en-tête ------------------------------------------------------------------------

    def _build_header(self):
        box = Gtk.Box(spacing=4, margin_top=4, margin_bottom=4, margin_start=6, margin_end=6)
        self.branch_btn = Gtk.MenuButton(label="…", direction=Gtk.ArrowType.DOWN)
        self.branch_btn.set_popover(self._flow_popover())
        box.append(self.branch_btn)
        self.sync_label = Gtk.Label(label="")
        self.sync_label.add_css_class("dim-label")
        box.append(self.sync_label)
        box.append(Gtk.Box(hexpand=True))
        for icon, tip, fn in (("view-refresh-symbolic", "Rafraîchir", self.refresh),
                              ("folder-download-symbolic", "Fetch", self.fetch),
                              ("go-down-symbolic", "Pull", self.pull)):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip)
            b.add_css_class("flat")
            b.connect("clicked", lambda _b, fn=fn: fn())
            box.append(b)
        self.push_btn = Gtk.Button(icon_name="go-up-symbolic", tooltip_text="Push")
        self.push_btn.add_css_class("flat")
        self.push_btn.connect("clicked", lambda _b: self.push())
        box.append(self.push_btn)
        more = Gtk.MenuButton(icon_name="pan-down-symbolic", tooltip_text="Autres envois")
        pop = Gtk.Popover()
        force = Gtk.Button(label="Push forcé…")
        force.add_css_class("flat")
        force.connect("clicked", lambda _b: (pop.popdown(), self.push(force=True)))
        pop.set_child(force)
        more.set_popover(pop)
        more.add_css_class("flat")
        box.append(more)
        self.layout_buttons = {}
        group = Gtk.Box()
        group.add_css_class("linked")
        first = None
        for name in ("A", "B", "C"):
            t = Gtk.ToggleButton(label=name, tooltip_text=f"Disposition {name}")
            if first is None:
                first = t
            else:
                t.set_group(first)
            t.set_active(name == self._layout)
            t.connect("toggled", lambda b, n=name: b.get_active() and self.set_layout(n))
            self.layout_buttons[name] = t
            group.append(t)
        box.append(group)
        return box

    def _flow_popover(self):
        pop = Gtk.Popover()
        self._flow_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        pop.set_child(self._flow_box)
        return pop

    def _fill_flow_menu(self, branch_name):
        while (c := self._flow_box.get_first_child()) is not None:
            self._flow_box.remove(c)
        ok = bool(self._flow_ok)
        reason = None if ok else getattr(self.git, "FLOW_UNAVAILABLE", "git flow n'est pas installé")
        for kind in git_repo.FLOW_KINDS:
            start = Gtk.Button(label=f"Démarrer une {kind}…" if kind != "hotfix"
                               else "Démarrer un hotfix…")
            start.add_css_class("flat")
            start.set_sensitive(ok)
            start.set_tooltip_text(reason)
            start.connect("clicked", lambda _b, k=kind: self._flow_start(k))
            self._flow_box.append(start)
            current = bool(branch_name) and branch_name.startswith(kind + "/")
            finish = Gtk.Button(label=f"Finir la {kind}" if kind != "hotfix" else "Finir le hotfix")
            finish.add_css_class("flat")
            finish.set_sensitive(ok and current)
            finish.set_tooltip_text(reason or (None if current else
                                               f"La branche courante n'est pas une {kind}"))
            finish.connect("clicked", lambda _b, k=kind, n=branch_name: self._flow_finish(k, n))
            self._flow_box.append(finish)

    # ---- disposition --------------------------------------------------------------------

    def layout(self):
        return self._layout

    def set_layout(self, layout):
        if layout not in ("A", "B", "C") or layout == self._layout:
            return
        self._layout = layout
        _save_layout(layout)
        btn = self.layout_buttons.get(layout)
        if btn is not None and not btn.get_active():
            btn.set_active(True)
        self._apply_layout_widgets()
        self._on_layout(layout)
        if layout == "B":
            self.open_history()

    def _apply_layout_widgets(self):
        self.graph.set_visible(self._layout != "B")
        self.graph.set_density("cards" if self._layout == "C" else "compact")

    # ---- ouverture dans la zone de droite -----------------------------------------------

    def open_commit(self, cid):
        view = CommitView(self.root, cid, git=self.git)
        view.connect("commit-activated", lambda _v, parent: self.open_commit(parent))
        self._open_in_editor(f"commit:{cid}", f"Commit {cid[:7]}", view)

    def open_history(self):
        graph = GraphView("cards", git=self.git)
        graph.load(self.root)
        detail = Gtk.Box(vexpand=True, hexpand=True)
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, wide_handle=True,
                          shrink_start_child=False, shrink_end_child=False)

        def show(_g, cid):
            view = CommitView(self.root, cid, git=self.git)
            view.connect("commit-activated", lambda _v, parent: (graph.select(parent),
                                                                 show(None, parent)))
            while (c := detail.get_first_child()) is not None:
                detail.remove(c)
            detail.append(view)
        graph.connect("commit-activated", show)
        graph.set_size_request(260, -1)
        paned.set_start_child(graph)
        paned.set_end_child(detail)
        self._open_in_editor("git:historique", "Historique", paned)

    # ---- état affiché -------------------------------------------------------------------

    def empty_shown(self):
        return self.stack.get_visible_child_name() == "empty"

    def set_root(self, cwd):
        cwd = os.fspath(cwd)
        if cwd == self.root:
            return
        self.root = cwd
        self.changes.repo = cwd
        self._watch()
        self.refresh(full=True)

    def refresh(self, full=False):
        root, git = self.root, self.git

        def work():
            forget = getattr(git, "forget", None)
            if forget is not None:
                forget(root)        # source distante : l'état gardé n'est pas réutilisé ici
            if not git.is_repo(root):
                return None
            try:
                br = git.branch(root)
            except git_repo.GitError:
                br = None
            return br, (git.flow_available() if self._flow_ok is None else self._flow_ok)

        def done(res):
            if self._closed or root != self.root:
                return
            if res is None:
                self._is_repo = False
                self.empty.set_title("Pas un dépôt git")
                self.empty.set_description("Ce dossier n'est pas un dépôt git.")
                self.stack.set_visible_child_name("empty")
                return
            br, flow_ok = res
            self._is_repo = True
            self._flow_ok = flow_ok
            self.stack.set_visible_child_name("main")
            name = br.name if br and br.name else "HEAD détachée"
            self.branch_btn.set_label(name)
            self.sync_label.set_label(
                f"↑{br.ahead} ↓{br.behind}" if br and br.upstream else "")
            self._fill_flow_menu(br.name if br else None)
            self.changes.refresh()
            self.graph.load(root, keep=not full)
        in_thread(work, done)

    # ---- erreurs ------------------------------------------------------------------------

    def show_error(self, err):
        self._error = err
        self.banner.set_title(str(err))
        self.banner.set_revealed(True)

    def error_details(self):
        e = self._error
        if e is None:
            return ""
        return f"{getattr(e, 'command', '')}\n\n{getattr(e, 'output', str(e))}".strip()

    def _show_details(self):
        text = Gtk.Label(label=self.error_details(), selectable=True, wrap=True, xalign=0)
        d = Adw.AlertDialog(heading="Détails de l'erreur", extra_child=text)
        d.add_response("close", "Fermer")
        d.connect("response", lambda *_: self.banner.set_revealed(False))
        d.present(self.get_root())

    # ---- commandes distantes et git flow ------------------------------------------------

    def _op(self, work, label=None):
        self.banner.set_revealed(False)
        self._busy_ops += 1

        def run():
            try:
                work()
                return None
            except git_repo.GitError as e:
                return e

        def done(err):
            self._busy_ops -= 1
            if self._closed:
                return
            if err is not None:
                self.show_error(err)
            self.refresh()
        in_thread(run, done)

    def fetch(self):
        self._last_fetch = time.monotonic()
        root = self.root
        self._op(lambda: self.git.fetch(root))

    def pull(self):
        root = self.root
        self._op(lambda: self.git.pull(root, prompt=True))

    def push(self, force=False):
        root = self.root
        if force:
            d = Adw.AlertDialog(
                heading="Push forcé ?",
                body="Le dépôt distant sera écrasé par ta branche (avec garde-fou : refusé si "
                     "quelqu'un a poussé entre-temps).")
            d.add_response("cancel", "Annuler")
            d.add_response("ok", "Pousser de force")
            d.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
            d.connect("response", lambda _d, r: r == "ok" and
                      self._op(lambda: self.git.push(root, force=True, prompt=True)))
            d.present(self.get_root())
            return
        self._op(lambda: self.git.push(root, prompt=True))

    def _flow_start(self, kind):
        entry = Gtk.Entry(placeholder_text="nom", activates_default=True)
        d = Adw.AlertDialog(heading=f"Démarrer : {kind}", extra_child=entry)
        d.add_response("cancel", "Annuler")
        d.add_response("ok", "Démarrer")
        d.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("ok")
        root = self.root

        def response(_d, r):
            name = entry.get_text().strip()
            if r == "ok" and name:
                self._op(lambda: self.git.flow(root, kind, "start", name))
        d.connect("response", response)
        d.present(self.get_root())

    def _flow_finish(self, kind, branch_name):
        name = (branch_name or "").split("/", 1)[-1]
        root = self.root
        d = Adw.AlertDialog(heading=f"Finir la {kind} « {name} » ?",
                            body="La branche est fusionnée puis supprimée.")
        d.add_response("cancel", "Annuler")
        d.add_response("ok", "Finir")
        d.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: r == "ok" and
                  self._op(lambda: self.git.flow(root, kind, "finish", name)))
        d.present(self.get_root())

    # ---- fetch automatique --------------------------------------------------------------

    def _visible(self):
        root = self.get_root()
        return self.get_mapped() and isinstance(root, Gtk.Window) and root.is_active()

    def _tick(self):
        minutes = _fetch_minutes()
        if minutes > 0 and self._visible() and self._is_repo is not False \
                and time.monotonic() - self._last_fetch >= minutes * 60:
            self.fetch()
        elif self.remote and self._visible() and not self._busy_ops:
            self.refresh()      # pas de suivi du disque à distance
        return True

    # ---- suivi du disque ----------------------------------------------------------------

    def _watch(self):
        self._stop_watch()
        if self.remote:
            return      # le dossier est sur le serveur
        ref = weakref.ref(self)

        def changed(_m, file, other, _event):
            page = ref()
            if page is None:
                return
            names = {f.get_basename() for f in (file, other) if f is not None}
            parent = file.get_parent().get_basename() if file is not None and file.get_parent() \
                else ""
            if parent == ".git" and not names & WATCHED_IN_GIT:
                return
            if names == {".git"} or "index.lock" in names:
                return
            page._schedule_reload()

        folders = [self.root]
        git_dir = os.path.join(self.root, ".git")
        if os.path.isdir(git_dir):
            folders += [git_dir, os.path.join(git_dir, "refs", "heads"),
                        os.path.join(git_dir, "refs", "remotes", "origin")]
        for folder in folders:
            if not os.path.isdir(folder):
                continue
            try:
                m = Gio.File.new_for_path(folder).monitor_directory(
                    Gio.FileMonitorFlags.WATCH_MOVES, None)
            except GLib.Error:
                continue
            m.connect("changed", changed)
            self._monitors.append(m)

    def _stop_watch(self):
        for m in self._monitors:
            m.cancel()
        self._monitors = []

    def _schedule_reload(self):
        if self._closed:
            return
        if self._reload_id:
            GLib.source_remove(self._reload_id)
        ref = weakref.ref(self)

        def fire():
            page = ref()
            if page is not None:
                page._reload_id = 0
                page.refresh()
            return False
        self._reload_id = GLib.timeout_add(RELOAD_DELAY_MS, fire)

    def close(self):
        """Arrête le suivi du disque et la minuterie."""
        self._closed = True
        self._stop_watch()
        if self._reload_id:
            GLib.source_remove(self._reload_id)
            self._reload_id = 0
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
