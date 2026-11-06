"""Liste des projets de l'onglet Sessions (colonne de gauche) : « Tous les projets » en
tête, puis chaque projet avec son point d'activité (session ouverte ; point d'attention
si une session attend une réponse), son nombre de conversations, son compte associé, et
« dossier introuvable » pour un projet déplacé ou disparu. Les entrées viennent de
`session_hub.build` ; la liste n'est reconstruite que si elles changent."""

from gi.repository import Gtk, Pango

from .. import session_hub as hub
from .common import short_path

ACTIVITY_TIPS = {"attention": "Une session attend ta réponse", "ouverte": "Session ouverte"}


class ProjectList(Gtk.ScrolledWindow):
    def __init__(self, on_select):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.on_select = on_select      # on_select(dossier ou hub.ALL)
        self.signature = None
        self.syncing = False
        self.rows = []
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE,
                                css_classes=["navigation-sidebar", "ccs-projects"])
        self.list.set_header_func(self.header)
        # Sélection au clavier ou à la souris ; un clic sur le projet déjà choisi compte aussi
        # (fenêtre étroite : il referme la liste).
        self.list.connect("row-selected", self.on_row_selected)
        self.list.connect("row-activated", self.on_row_selected)
        self.set_child(self.list)

    @staticmethod
    def header(row, before):
        # Trait entre « Tous les projets » et les projets.
        wanted = before is not None and before.cwd is hub.ALL
        if wanted and row.get_header() is None:
            row.set_header(Gtk.Separator(margin_top=4, margin_bottom=4))
        elif not wanted and row.get_header() is not None:
            row.set_header(None)

    def show(self, entries, selected):
        """Affiche les entrées (session_hub.ProjectEntry) et sélectionne `selected`."""
        signature = (hub.entries_signature(entries), selected)
        if signature == self.signature:
            return
        same_rows = self.signature is not None and self.signature[0] == signature[0]
        self.signature = signature
        self.syncing = True
        try:
            if not same_rows:
                while (child := self.list.get_first_child()) is not None:
                    self.list.remove(child)
                self.rows = [self.row(e) for e in entries]
                for row in self.rows:
                    self.list.append(row)
            target = next((r for r in self.rows if r.cwd == selected), None)
            if target is not None:
                self.list.select_row(target)
        finally:
            self.syncing = False

    def row(self, entry):
        row = Gtk.ListBoxRow()
        row.cwd = entry.cwd
        box = Gtk.Box(spacing=10, margin_top=3, margin_bottom=3, margin_start=4, margin_end=4)
        dot = Gtk.Box(css_classes=["ccs-dot"] + ([entry.activity] if entry.activity else []),
                      valign=Gtk.Align.CENTER, tooltip_text=ACTIVITY_TIPS.get(entry.activity))
        box.append(dot)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, hexpand=True, valign=Gtk.Align.CENTER)
        name = Gtk.Label(label=entry.name, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        if entry.cwd is hub.ALL:
            name.add_css_class("heading")
        texts.append(name)
        detail, error = hub.entry_detail(entry)
        if detail:
            texts.append(Gtk.Label(label=detail, xalign=0, ellipsize=Pango.EllipsizeMode.END,
                                   css_classes=["caption", "error" if error else "dim-label"]))
        box.append(texts)
        count = Gtk.Label(label=str(entry.conversations), valign=Gtk.Align.CENTER,
                          css_classes=["caption", "dim-label", "ccs-count"])
        box.append(count)
        row.set_child(box)
        if entry.cwd:
            tip = entry.cwd + (f"\nDéplacé vers {short_path(entry.moved_to)} ?" if entry.moved_to else "")
            row.set_tooltip_text(tip)
        return row

    def on_row_selected(self, _list, row):
        if self.syncing or row is None:
            return
        self.on_select(row.cwd)
