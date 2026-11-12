"""Espace de session : arbre des fichiers / feuille de route, chat, éditeur de fichiers.

Deux `Gtk.Paned` imbriqués (les widgets ne sont jamais recréés quand la disposition change) :

    disposition B (défaut) :  [ gauche ] | [ chat ] | [ fichier ]   (fichier caché tant que
                                                                    rien n'est ouvert)
    disposition A          :  [ gauche ] | [ fichier ] | [ chat ]

« gauche » est une pile à deux pages (« Fichiers » : `FileTree`, « Feuille de route » :
`RoadmapView`) avec son sélecteur. Les largeurs sont gardées par disposition
(`terminal_store.save_panes`).
"""

import os

from gi.repository import Adw, GLib, GObject, Gtk

from .. import roadmap, settings, terminal_store
from .file_editor import FileEditor
from .file_panel import FileTree
from .roadmap_view import RoadmapView

ASK_CREATE_TEXT = ("Crée une feuille de route ROADMAP.md pour ce projet "
                   "(phases `##` et cases à cocher).")
MIN_TREE = 120
MIN_SIDE = 200
SAVE_DELAY_MS = 600
APPLY_TRIES = 60       # 60 × 50 ms : le temps que la fenêtre soit placée
TREE_ACCEL = "<Control>b"


def _show_ignored():
    try:
        return bool(settings.load_settings().get("files", {}).get("show_ignored", False))
    except Exception:  # noqa: BLE001 — réglages illisibles : valeur par défaut
        return False


class SessionWorkspace(Gtk.Box):
    """`SessionWorkspace(cwd, center, on_ask_create=None, layout="B")`.

    `center` : le widget du chat. S'il émet `open-file(path, line)` et `show-diff(path,
    old, new)`, ils ouvrent l'éditeur. Signal `insert-reference(relpath)` : « Insérer
    @chemin » depuis l'arbre (renvoyé aussi à `center.insert_reference(relpath)` s'il existe)."""

    __gsignals__ = {
        "insert-reference": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "layout-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, cwd, center, on_ask_create=None, layout="B"):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        self.cwd = os.fspath(cwd)
        self.center = center
        self.layout = layout if layout in ("A", "B") else "B"
        self._on_ask_create = on_ask_create
        self._panes = terminal_store.load_panes()
        self._applying = 0
        self._save_source = 0
        self._destroyed = False
        self._dark = False

        # -- gauche : fichiers / feuille de route
        self.tree = FileTree(self.cwd, self.open_file, show_ignored=_show_ignored())
        self.tree.connect("insert-reference", self._on_insert_reference)
        self.roadmap = RoadmapView(self.cwd, on_ask_create=self.ask_create)
        self.left_stack = Gtk.Stack(vexpand=True, hexpand=True)
        self.tree_holder = Gtk.Box(vexpand=True, hexpand=True)   # l'arbre change avec le dossier du projet
        self.tree_holder.append(self.tree)
        self.left_stack.add_titled(self.tree_holder, "fichiers", "Fichiers")
        self.left_stack.add_titled(self.roadmap, "feuille", "Feuille de route")
        self.left_stack.set_visible_child_name(self._panes["left"])
        self.left_stack.connect("notify::visible-child-name", self._on_left_changed)
        switcher = Gtk.StackSwitcher(stack=self.left_stack, halign=Gtk.Align.CENTER, margin_top=4,
                                     margin_bottom=4)
        self.left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        self.left.append(switcher)
        self.left.append(self.left_stack)
        self.left.set_size_request(MIN_TREE, -1)
        self.left.set_visible(self._panes["tree_visible"])

        # -- éditeur
        self.editor = FileEditor()
        self.editor.connect("empty", self._on_editor_empty)
        self.editor_box = Gtk.Box(vexpand=True, hexpand=True)
        self.editor_box.append(self.editor)
        self.editor_box.set_size_request(MIN_SIDE, -1)
        self.editor_box.set_visible(False)

        # -- assemblage
        self.inner = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, wide_handle=True,
                               hexpand=True, vexpand=True, shrink_start_child=False,
                               shrink_end_child=False)
        self.outer = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, wide_handle=True,
                               hexpand=True, vexpand=True, shrink_start_child=False,
                               shrink_end_child=False, resize_start_child=False,
                               resize_end_child=True)
        self.outer.set_start_child(self.left)
        self.outer.set_end_child(self.inner)
        self.banner = Adw.Banner(revealed=False, use_markup=False)
        self.append(self.banner)
        self.append(self.outer)
        self.arrange()

        for name in ("open-file", "show-diff"):
            if GObject.signal_lookup(name, type(center)):
                center.connect(name, getattr(self, "_on_" + name.replace("-", "_")))

        keys = Gtk.ShortcutController(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string(TREE_ACCEL),
                                       action=Gtk.CallbackAction.new(
                                           lambda *_a: (self.toggle_tree(), True)[1])))
        self.add_controller(keys)

        self.outer.connect("notify::position", self._on_moved)
        self.inner.connect("notify::position", self._on_moved)
        self.connect("map", lambda *_: self.apply_sizes())
        self.connect("destroy", self._on_destroy)

    # ---- disposition ------------------------------------------------------------------

    def arrange(self):
        """Place le chat et le fichier selon `self.layout` sans recréer aucun widget."""
        self._applying += 1
        try:
            self.inner.set_start_child(None)
            self.inner.set_end_child(None)
            if self.layout == "B":
                self.inner.set_start_child(self.center)
                self.inner.set_end_child(self.editor_box)
                self.inner.set_resize_start_child(True)
                self.inner.set_resize_end_child(False)
            else:
                self.inner.set_start_child(self.editor_box)
                self.inner.set_end_child(self.center)
                self.inner.set_resize_start_child(False)
                self.inner.set_resize_end_child(True)
            self.editor_box.set_visible(self.layout == "A" or bool(self.editor.paths()))
        finally:
            self._applying -= 1
        self.apply_sizes()

    def set_layout(self, layout):
        if layout not in ("A", "B") or layout == self.layout:
            return
        self.flush_save()
        self.layout = layout
        self.arrange()
        self.emit("layout-changed", layout)

    # ---- largeurs ---------------------------------------------------------------------

    def apply_sizes(self, tries=APPLY_TRIES):
        """Pose les largeurs gardées pour la disposition (attend que la page soit placée)."""
        if self._destroyed:
            return
        width = self.outer.get_width()
        if width <= 0:
            if tries > 0:
                GLib.timeout_add(50, lambda: (self.apply_sizes(tries - 1), False)[1])
            return
        self._applying += 1
        try:
            keep = self._panes[self.layout]
            self.outer.set_position(keep["tree"] if self.left.get_visible() else 0)
            inner_width = self.inner.get_width() or max(width - keep["tree"], 0)
            if self.editor_box.get_visible() and inner_width > 0:
                self.inner.set_position(max(inner_width - keep["side"], 0))
        finally:
            GLib.idle_add(self._settle)

    def _settle(self):
        self._applying = max(self._applying - 1, 0)
        return False

    def sizes(self):
        """{"tree": largeur de l'arbre, "side": largeur du panneau de droite} mesurées."""
        out = dict(self._panes[self.layout])
        if self.left.get_visible() and self.outer.get_position() >= MIN_TREE:
            out["tree"] = self.outer.get_position()
        inner_width = self.inner.get_width()
        if self.editor_box.get_visible() and inner_width > 0:
            side = inner_width - self.inner.get_position()
            if side >= MIN_SIDE:
                out["side"] = side
        return out

    def _on_moved(self, *_):
        if self._applying or self._destroyed or self.outer.get_width() <= 0:
            return
        if not self._save_source:
            self._save_source = GLib.timeout_add(SAVE_DELAY_MS, self._save_due)

    def _save_due(self):
        self._save_source = 0
        self.save_sizes()
        return False

    def flush_save(self):
        if self._save_source:
            GLib.source_remove(self._save_source)
            self._save_source = 0
            self.save_sizes()

    def save_sizes(self):
        """Garde les largeurs de la disposition affichée (et le reste de l'état des volets)."""
        self._panes[self.layout] = self.sizes()
        self.persist()

    def persist(self):
        fresh = terminal_store.load_panes()   # un autre espace a pu garder l'autre disposition
        fresh[self.layout] = self._panes[self.layout]
        fresh["tree_visible"] = self._panes["tree_visible"]
        fresh["left"] = self._panes["left"]
        self._panes = fresh
        terminal_store.save_panes(fresh)

    def _on_destroy(self, *_):
        self._destroyed = True
        if self._save_source:
            GLib.source_remove(self._save_source)
            self._save_source = 0

    # ---- arbre, feuille de route ------------------------------------------------------

    def toggle_tree(self, show=None):
        """Ctrl+B : replie ou rouvre le panneau de gauche."""
        show = (not self.left.get_visible()) if show is None else bool(show)
        self.left.set_visible(show)
        self._panes["tree_visible"] = show
        self.outer.set_position(self._panes[self.layout]["tree"] if show else 0)
        self.persist()

    def show_left(self, name):
        if name in ("fichiers", "feuille"):
            self.left_stack.set_visible_child_name(name)

    def _on_left_changed(self, *_):
        name = self.left_stack.get_visible_child_name()
        if name in ("fichiers", "feuille") and name != self._panes["left"]:
            self._panes["left"] = name
            self.persist()

    # ---- projet de la conversation ----------------------------------------------------

    @property
    def project_root(self):
        return self.tree.root

    @property
    def followed_roadmap(self):
        followed = self.roadmap.followed
        return str(followed) if followed is not None else None

    def follow_tool(self, name, data):
        """Une action de Claude : si elle lit ou modifie un ROADMAP.md, le panneau le suit (une
        conversation lancée depuis ~ ou le Bureau montre ainsi la feuille de route du projet)."""
        found = roadmap.path_in_tool(name, data, self.cwd)
        if found is not None:
            self.roadmap.follow(found)

    def set_project_root(self, folder):
        """« Dossier du projet… » : l'arbre et la feuille de route partent de ce dossier
        (le processus de la conversation n'est pas touché)."""
        folder = os.path.abspath(os.fspath(folder))
        if folder == self.tree.root:
            return
        old = self.tree
        self.tree = FileTree(folder, self.open_file, show_ignored=_show_ignored())
        self.tree.connect("insert-reference", self._on_insert_reference)
        self.tree_holder.remove(old)
        self.tree_holder.append(self.tree)
        self.roadmap.set_root(folder)

    def ask_create(self):
        """« Demander à Claude d'en créer une » : un message pour le chat."""
        if self._on_ask_create is not None:
            self._on_ask_create()
        elif hasattr(self.center, "send_auto"):
            self.center.send_auto(ASK_CREATE_TEXT)

    def _on_insert_reference(self, _tree, relpath):
        if hasattr(self.center, "insert_reference"):
            self.center.insert_reference(relpath)
        self.emit("insert-reference", relpath)

    # ---- éditeur ----------------------------------------------------------------------

    def _abs(self, path):
        return path if os.path.isabs(path) else os.path.join(self.cwd, path)

    def reveal_editor(self):
        self.editor_box.set_visible(True)
        self.apply_sizes()

    def open_file(self, path, line=None):
        self.reveal_editor()
        self.editor.open(self._abs(path), line)

    def _on_open_file(self, _center, path, line=0):
        self.open_file(path, line or None)

    def show_diff(self, path, old, new):
        self.reveal_editor()
        self.editor.show_diff(self._abs(path), old, new)

    def _on_show_diff(self, _center, path, old, new):
        self.show_diff(path, old, new)

    def set_notice(self, text):
        """Bandeau au-dessus de l'espace (None : masqué)."""
        self.banner.set_title(text or "")
        self.banner.set_revealed(bool(text))

    def _on_editor_empty(self, *_):
        if self.layout == "B":
            self.editor_box.set_visible(False)

    def has_unsaved(self):
        return self.editor.has_unsaved()

    def set_dark(self, dark):
        self._dark = bool(dark)
        self.editor.set_dark(self._dark)

    def close(self):
        """Libère ce qui surveille le disque (la feuille de route)."""
        self.roadmap.close()
