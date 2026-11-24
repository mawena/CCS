"""Onglet « Fichiers » : l'arbre d'un dossier (le dossier personnel au départ) à gauche, les
fichiers ouverts à droite (mêmes FileTree et FileEditor que l'espace d'une session). « Changer
de dossier » choisit une autre racine. Équivalent bureau de l'onglet web `#/fichiers`.
"""

import os

from gi.repository import Adw, Gio, Gtk

from .file_editor import FileEditor
from .file_panel import FileTree


class FilesPage(Gtk.Box):
    def __init__(self, root=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.root = os.path.abspath(root or os.path.expanduser("~"))
        self.tree = None

        bar = Gtk.Box(spacing=6, margin_start=6, margin_end=6, margin_top=6, margin_bottom=6)
        choose = Gtk.Button(icon_name="folder-open-symbolic", tooltip_text="Changer de dossier")
        choose.update_property([Gtk.AccessibleProperty.LABEL], ["Changer de dossier"])
        choose.add_css_class("flat")
        choose.connect("clicked", lambda _b: self.choose_root())
        home = Gtk.Button(icon_name="go-home-symbolic", tooltip_text="Dossier personnel")
        home.update_property([Gtk.AccessibleProperty.LABEL], ["Dossier personnel"])
        home.add_css_class("flat")
        home.connect("clicked", lambda _b: self.set_root(os.path.expanduser("~")))
        bar.append(choose)
        bar.append(home)

        self.tree_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.append(bar)
        left.append(Gtk.Separator())
        left.append(self.tree_box)

        self.editor = FileEditor()
        self.editor.connect("empty", lambda _e: self.right.set_visible_child_name("vide"))
        empty = Adw.StatusPage(icon_name="text-x-generic-symbolic", title="Aucun fichier ouvert",
                               description="Choisis un fichier dans l'arbre pour l'ouvrir ici.")
        self.right = Gtk.Stack(hexpand=True, vexpand=True)
        self.right.add_named(empty, "vide")
        self.right.add_named(self.editor, "fichiers")

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True,
                          start_child=left, end_child=self.right, position=320,
                          shrink_start_child=False, resize_start_child=False)
        self.append(paned)
        self.set_root(self.root)

    def set_root(self, root):
        self.root = os.path.abspath(root)
        if self.tree is not None:
            self.tree_box.remove(self.tree)
        self.tree = FileTree(self.root, self.open_file)
        self.tree_box.append(self.tree)

    def open_file(self, path, line=None):
        self.right.set_visible_child_name("fichiers")
        self.editor.open(path if os.path.isabs(path) else os.path.join(self.root, path), line)

    def choose_root(self):
        dialog = Gtk.FileDialog(title="Dossier à parcourir",
                                initial_folder=Gio.File.new_for_path(self.root))

        def done(d, result):
            try:
                folder = d.select_folder_finish(result)
            except Exception:  # noqa: BLE001 — annulé
                return
            if folder is not None and folder.get_path():
                self.set_root(folder.get_path())
        dialog.select_folder(self.get_root(), None, done)
