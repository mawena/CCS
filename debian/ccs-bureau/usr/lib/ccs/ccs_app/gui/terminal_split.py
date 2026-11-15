"""Deux onglets du terminal intégré côte à côte.

Un widget GTK n'a qu'un parent : chaque `TerminalTab` (enfant de sa page d'`Adw.TabView`)
garde son contenu dans `tab.panel` (terminal, bandeaux, file de messages). La vue scindée
« emprunte » le panneau de deux onglets, le place dans un `Gtk.Paned` redimensionnable et
le rend à son onglet au retour à la vue par onglets ; le processus et le terminal VTE ne
sont jamais recréés.
"""

from gi.repository import GLib, Gtk, Pango

CENTER_TRIES = 40  # 40 × 25 ms : le temps que la vue soit placée


class Half(Gtk.Box):
    """Une moitié : en-tête (titre, « Afficher seul », « Fermer ») puis le panneau emprunté."""

    def __init__(self, split, tab):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True,
                         css_classes=["ccs-split-half"])
        self.split, self.tab = split, tab
        header = Gtk.Box(spacing=4, css_classes=["ccs-split-header"])
        self.title = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        header.append(self.title)
        alone = Gtk.Button(icon_name="view-paged-symbolic", css_classes=["flat", "circular"],
                           tooltip_text="Afficher seul")
        alone.connect("clicked", lambda *_: split.on_single(tab))
        close = Gtk.Button(icon_name="window-close-symbolic", css_classes=["flat", "circular"],
                           tooltip_text="Fermer l'onglet")
        close.connect("clicked", lambda *_: split.on_close(tab))
        header.append(alone)
        header.append(close)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda *_: tab.focus())
        header.add_controller(click)
        self.append(header)

        tab.remove(tab.panel)
        self.append(tab.panel)
        focus = Gtk.EventControllerFocus()
        focus.connect("enter", lambda *_: split.on_focus(tab))
        self.add_controller(focus)
        self.update()

    def update(self):
        self.title.set_label(self.tab.state.title)
        self.title.set_tooltip_text(self.tab.state.cwd)

    def give_back(self):
        """Rend le panneau à son onglet."""
        if self.tab.panel.get_parent() is self:
            self.remove(self.tab.panel)
            self.tab.append(self.tab.panel)


class SplitView(Gtk.Box):
    """Vue scindée : `on_focus(tab)` quand une moitié prend le focus clavier,
    `on_single(tab)` pour revenir aux onglets sur cet onglet, `on_close(tab)` pour le fermer."""

    def __init__(self, on_focus, on_single, on_close):
        super().__init__(hexpand=True, vexpand=True)
        self.on_focus, self.on_single, self.on_close = on_focus, on_single, on_close
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, wide_handle=True, hexpand=True,
                               vexpand=True, resize_start_child=True, resize_end_child=True,
                               shrink_start_child=False, shrink_end_child=False)
        self.append(self.paned)
        self.halves = []
        self.active = None

    @property
    def tabs(self):
        return [h.tab for h in self.halves]

    def contains(self, tab):
        return any(h.tab is tab for h in self.halves)

    def show(self, left, right):
        """Emprunte les panneaux de `left` et `right` (ceux d'avant sont rendus)."""
        self.release()
        self.halves = [Half(self, left), Half(self, right)]
        self.paned.set_start_child(self.halves[0])
        self.paned.set_end_child(self.halves[1])
        tries = iter(range(CENTER_TRIES))
        GLib.timeout_add(25, lambda: self.center() and next(tries, None) is not None)

    def release(self):
        """Rend les panneaux à leurs onglets ; renvoie les onglets qui étaient affichés."""
        tabs = self.tabs
        root = self.get_root()
        if self.halves and root is not None:
            root.set_focus(None)  # le terminal déplacé ne doit pas rester le focus du Gtk.Paned
        for half in self.halves:
            half.give_back()
        self.paned.set_start_child(None)
        self.paned.set_end_child(None)
        self.halves, self.active = [], None
        return tabs

    def center(self):
        """Séparateur au milieu une fois la vue placée ; True tant qu'il faut réessayer."""
        width = self.paned.get_width()
        if not self.halves:
            return False
        if width <= 0 or not self.paned.get_mapped():
            return True
        self.paned.set_position(width // 2)
        return False

    def set_active(self, tab):
        """Moitié active : bordure de la couleur d'accent, en-tête en clair."""
        self.active = tab if self.contains(tab) else None
        for half in self.halves:
            if half.tab is self.active:
                half.add_css_class("active")
            else:
                half.remove_css_class("active")

    def update(self, tab):
        for half in self.halves:
            if half.tab is tab:
                half.update()
