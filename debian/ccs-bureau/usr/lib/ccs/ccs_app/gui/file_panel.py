"""Panneau Fichiers : arbre du dossier d'une session, marques git, menu contextuel."""

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, Gio, GLib, GObject, Graphene, Gtk

from .. import file_tree
from .common import in_thread

CSS = b"""
.ccs-mark { font-weight: bold; font-size: 0.85em; min-width: 14px; }
.ccs-mark-M { color: @warning_color; }
.ccs-mark-A { color: @success_color; }
.ccs-mark-D { color: @error_color; }
.ccs-mark-Q { color: alpha(currentColor, 0.5); }
.ccs-mark-dir { color: @warning_color; }
.ccs-deleted label.ccs-name { text-decoration: line-through; }
"""
_css_done = False

MARK_TEXT = {"M": "M", "A": "A", "D": "D", "?": "?", "•": "•"}
MARK_CLASS = {"M": "ccs-mark-M", "A": "ccs-mark-A", "D": "ccs-mark-D",
              "?": "ccs-mark-Q", "•": "ccs-mark-dir"}
REFRESH_MS = 500


def _install_css():
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


class _Node(GObject.Object):
    """Une ligne de l'arbre : un fichier, un dossier ou un fichier supprimé."""

    name = GObject.Property(type=str, default="")
    mark = GObject.Property(type=str, default="")

    def __init__(self, name, path, relpath, is_dir, deleted=False):
        super().__init__(name=name)
        self.path = path
        self.relpath = relpath
        self.is_dir = is_dir
        self.deleted = deleted


def _list_dir(root, dirpath, show_ignored, marks):
    """[(nom, est_dossier, supprimé)] triés, dossiers d'abord. Les liens
    symboliques vers des dossiers ne sont pas des dossiers (jamais suivis)."""
    rel_dir = os.path.relpath(dirpath, root)
    prefix = "" if rel_dir == "." else rel_dir + "/"
    entries = {}
    try:
        with os.scandir(dirpath) as it:
            for e in it:
                if e.name in file_tree.ALWAYS_HIDDEN:
                    continue
                try:
                    is_dir = e.is_dir(follow_symlinks=False)
                except OSError:
                    is_dir = False
                entries[e.name] = (is_dir, False)
    except OSError:
        return []
    for relpath, mark in marks.items():
        if mark == "D" and relpath.startswith(prefix):
            name = relpath[len(prefix):]
            if "/" not in name and name not in entries:
                entries[name] = (False, True)
    if not show_ignored:
        probe = {prefix + n + ("/" if d else ""): n for n, (d, _x) in entries.items()}
        for hidden in file_tree.ignored(root, probe):
            entries.pop(probe.get(hidden), None)
    return sorted(((n, d, x) for n, (d, x) in entries.items()),
                  key=lambda t: (not t[1], t[0].casefold(), t[0]))


class FileTree(Gtk.Box):
    """Arbre des fichiers de `root`. `on_open(path)` est appelé pour un fichier
    activé. Signal `insert-reference(relpath)` : « Insérer @chemin »."""

    __gsignals__ = {"insert-reference": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, root, on_open, show_ignored=False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        _install_css()
        self.root = os.path.abspath(os.fspath(root))
        self.on_open = on_open
        self._show_ignored = bool(show_ignored)
        self._marks = {}
        self._stores = {}      # chemin du dossier -> Gio.ListStore de _Node
        self._monitors = {}    # chemin du dossier -> Gio.FileMonitor
        self._busy = False
        self._again = False
        self._timer = 0
        self._menu_node = None
        self._destroyed = False

        self._root_store = self._store_for(self.root)
        self.model = Gtk.TreeListModel.new(
            self._root_store, False, False, self._create_children)
        self.selection = Gtk.SingleSelection(model=self.model)
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_row)
        factory.connect("bind", self._bind_row)
        factory.connect("unbind", self._unbind_row)
        self.list_view = Gtk.ListView(model=self.selection, factory=factory,
                                      single_click_activate=True)
        self.list_view.add_css_class("navigation-sidebar")
        self.list_view.connect("activate", self._on_activate)
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True,
                                      hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.list_view)
        self.append(scroller)

        self._build_menu()
        self.connect("destroy", self._on_destroy)
        git_dir = os.path.join(self.root, ".git")
        if os.path.isdir(git_dir):
            self._watch(git_dir)

    # ---- modèle -------------------------------------------------------------

    def _store_for(self, dirpath):
        store = self._stores.get(dirpath)
        if store is None:
            store = Gio.ListStore(item_type=_Node)
            self._stores[dirpath] = store
            self._watch(dirpath)
            self._request_refresh()
        return store

    def _create_children(self, node):
        return self._store_for(node.path) if node.is_dir else None

    def _watch(self, dirpath):
        if dirpath in self._monitors:
            return
        try:
            mon = Gio.File.new_for_path(dirpath).monitor_directory(
                Gio.FileMonitorFlags.NONE, None)
        except GLib.Error:
            return
        mon.connect("changed", lambda *_a: self._request_refresh())
        self._monitors[dirpath] = mon

    def _request_refresh(self):
        if self._timer or self._destroyed:
            return
        self._timer = GLib.timeout_add(REFRESH_MS, self._fire_refresh)

    def _fire_refresh(self):
        self._timer = 0
        self.refresh()
        return False

    def refresh(self):
        """Relit git et les dossiers déjà ouverts, dans un fil."""
        if self._destroyed:
            return
        if self._busy:
            self._again = True
            return
        self._busy = True
        dirs = list(self._stores)
        show = self._show_ignored

        def work():
            marks = file_tree.git_marks(self.root)
            return marks, {d: _list_dir(self.root, d, show, marks) for d in dirs}

        in_thread(work, self._apply)

    def _apply(self, result):
        self._busy = False
        if self._destroyed:
            return
        marks, listings = result
        self._marks = marks
        for dirpath, entries in listings.items():
            store = self._stores.get(dirpath)
            if store is not None:
                self._sync(store, dirpath, entries)
        self._apply_marks()
        if self._again:
            self._again = False
            self._request_refresh()

    def _sync(self, store, dirpath, entries):
        """Aligne `store` sur `entries` sans recréer les lignes qui restent
        (les dossiers ouverts le restent)."""
        wanted = {(n, d, x) for n, d, x in entries}
        for i in range(store.get_n_items() - 1, -1, -1):
            node = store.get_item(i)
            if (node.name, node.is_dir, node.deleted) not in wanted:
                store.remove(i)
        rel_dir = os.path.relpath(dirpath, self.root)
        for i, (name, is_dir, deleted) in enumerate(entries):
            if i < store.get_n_items():
                cur = store.get_item(i)
                if (cur.name, cur.is_dir, cur.deleted) == (name, is_dir, deleted):
                    continue
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            store.insert(i, _Node(name, os.path.join(dirpath, name), rel,
                                  is_dir, deleted))

    def _apply_marks(self):
        dirty_dirs = set()
        for rel in self._marks:
            parts = rel.split("/")
            for k in range(1, len(parts)):
                dirty_dirs.add("/".join(parts[:k]))
        for store in self._stores.values():
            for i in range(store.get_n_items()):
                node = store.get_item(i)
                if node.is_dir:
                    node.mark = "•" if node.relpath in dirty_dirs else ""
                else:
                    node.mark = self._marks.get(node.relpath, "")

    def set_show_ignored(self, show):
        show = bool(show)
        if show != self._show_ignored:
            self._show_ignored = show
            self.refresh()

    # ---- lecture pour les tests et les autres modules -------------------------

    def rows(self):
        """[(nom, profondeur, marque)] des lignes visibles."""
        out = []
        for i in range(self.model.get_n_items()):
            row = self.model.get_item(i)
            node = row.get_item()
            out.append((node.name, row.get_depth(), node.mark))
        return out

    def row_index(self, relpath):
        for i in range(self.model.get_n_items()):
            if self.model.get_item(i).get_item().relpath == relpath:
                return i
        return -1

    def expand(self, relpath, expanded=True):
        i = self.row_index(relpath)
        if i >= 0:
            self.model.get_item(i).set_expanded(expanded)
        return i >= 0

    # ---- lignes ----------------------------------------------------------------

    def _setup_row(self, _factory, item):
        box = Gtk.Box(spacing=6)
        icon = Gtk.Image()
        label = Gtk.Label(xalign=0, hexpand=True, ellipsize=3)
        label.add_css_class("ccs-name")
        mark = Gtk.Label()
        mark.add_css_class("ccs-mark")
        box.append(icon)
        box.append(label)
        box.append(mark)
        expander = Gtk.TreeExpander()
        expander.set_child(box)
        click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        click.connect("pressed", self._on_right_click, expander)
        expander.add_controller(click)
        item.set_child(expander)

    def _bind_row(self, _factory, item):
        expander = item.get_child()
        row = item.get_item()
        node = row.get_item()
        expander.set_list_row(row)
        box = expander.get_child()
        icon, label, mark = box.get_first_child(), box.get_first_child().get_next_sibling(), box.get_last_child()
        icon.set_from_icon_name("folder-symbolic" if node.is_dir else "text-x-generic-symbolic")
        label.set_label(node.name)
        box.remove_css_class("ccs-deleted")
        if node.deleted:
            box.add_css_class("ccs-deleted")

        def show_mark(*_a):
            for c in list(mark.get_css_classes()):
                if c.startswith("ccs-mark-"):
                    mark.remove_css_class(c)
            mark.set_label(MARK_TEXT.get(node.mark, ""))
            if node.mark in MARK_CLASS:
                mark.add_css_class(MARK_CLASS[node.mark])

        show_mark()
        expander._ccs_handler = node.connect("notify::mark", show_mark)
        expander._ccs_node = node

    def _unbind_row(self, _factory, item):
        expander = item.get_child()
        node = getattr(expander, "_ccs_node", None)
        if node is not None:
            node.disconnect(expander._ccs_handler)
            expander._ccs_node = None
        expander.set_list_row(None)

    def _on_activate(self, _view, position):
        row = self.model.get_item(position)
        if row is None:
            return
        node = row.get_item()
        if node.is_dir:
            row.set_expanded(not row.get_expanded())
        elif not node.deleted:
            self.on_open(node.path)

    # ---- menu du clic droit -------------------------------------------------------

    def _build_menu(self):
        group = Gio.SimpleActionGroup()
        for name, handler in (("open", self._act_open), ("copy", self._act_copy),
                              ("insert", self._act_insert),
                              ("default-app", self._act_default),
                              ("show", self._act_show)):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", lambda _a, _p, h=handler: h())
            group.add_action(act)
        self.insert_action_group("fichiers", group)
        menu = Gio.Menu()
        menu.append("Ouvrir", "fichiers.open")
        menu.append("Copier le chemin", "fichiers.copy")
        menu.append("Insérer @chemin dans le message", "fichiers.insert")
        menu.append("Ouvrir avec l'application par défaut", "fichiers.default-app")
        menu.append("Afficher dans Fichiers", "fichiers.show")
        self._menu_model = menu
        self._popover = Gtk.PopoverMenu.new_from_model(menu)
        self._popover.set_has_arrow(False)
        self._popover.set_parent(self)

    def _on_right_click(self, gesture, _n, x, y, expander):
        row = expander.get_list_row()
        if row is None:
            return
        self._menu_node = row.get_item()
        ok, point = expander.compute_point(self, Graphene.Point().init(x, y))
        rect = Gdk.Rectangle()
        rect.x, rect.y = (int(point.x), int(point.y)) if ok else (int(x), int(y))
        rect.width = rect.height = 1
        self._popover.set_pointing_to(rect)
        self._popover.popup()

    def _act_open(self):
        node = self._menu_node
        if node is not None and not node.is_dir and not node.deleted:
            self.on_open(node.path)

    def _act_copy(self):
        if self._menu_node is not None:
            self.get_clipboard().set(self._menu_node.path)

    def _act_insert(self):
        if self._menu_node is not None:
            self.emit("insert-reference", self._menu_node.relpath)

    def _launcher(self):
        if self._menu_node is None:
            return None
        return Gtk.FileLauncher.new(Gio.File.new_for_path(self._menu_node.path))

    def _window(self):
        root = self.get_root()
        return root if isinstance(root, Gtk.Window) else None

    def _act_default(self):
        launcher = self._launcher()
        if launcher is not None:
            launcher.launch(self._window(), None, lambda *_a: None)

    def _act_show(self):
        launcher = self._launcher()
        if launcher is not None:
            launcher.open_containing_folder(self._window(), None, lambda *_a: None)

    # ---- fin de vie -----------------------------------------------------------------

    def _on_destroy(self, _w):
        self._destroyed = True
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        for mon in self._monitors.values():
            mon.cancel()
        self._monitors.clear()
        if self._popover.get_parent() is not None:
            self._popover.unparent()
