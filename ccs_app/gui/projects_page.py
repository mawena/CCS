"""Page Projets : une carte par projet qui a une feuille de route, puis le détail d'un projet
(feuille de route, frise des versions, cases cochées par jour, dates de fin des phases).

Les listes et l'historique (git) sont calculés dans un fil, jamais à l'ouverture de la page.
"""

from datetime import date, datetime, timedelta
from pathlib import Path

from gi.repository import Adw, Gio, GLib, Gtk

from .. import account_colors, conversations, projects, settings
from .common import clear, in_thread
from .roadmap_view import RoadmapView, gauge

DAYS_SHOWN = 30
BAR_RGB = account_colors.rgb(account_colors.PALETTE[0])


def fmt_day(day):
    return day.strftime("%d/%m/%Y")


def fmt_activity(ts):
    if not ts:
        return "aucune activité"
    return "activité le " + fmt_day(datetime.fromtimestamp(ts))


def last_days(checks_per_day, today=None, days=DAYS_SHOWN):
    """[(jour, cases cochées)] des `days` derniers jours, le plus ancien d'abord."""
    today = today or date.today()
    return [(d, int(checks_per_day.get(d, 0)))
            for d in (today - timedelta(days=n) for n in range(days - 1, -1, -1))]


class DayBars(Gtk.DrawingArea):
    """Histogramme : une barre par jour."""

    def __init__(self):
        super().__init__(content_height=120, hexpand=True)
        self.values = []
        self.set_draw_func(self._draw)

    def set_data(self, days):
        self.values = list(days)
        self.queue_draw()

    def _draw(self, _area, cr, width, height):
        if not self.values:
            return
        c = self.get_color()
        peak = max(n for _d, n in self.values) or 1
        bottom = 16
        slot = width / len(self.values)
        cr.set_font_size(9)
        for i, (day, n) in enumerate(self.values):
            bh = (height - bottom - 4) * n / peak
            cr.set_source_rgba(*BAR_RGB, 0.85)
            cr.rectangle(i * slot + 1, height - bottom - bh, max(1, slot - 2), bh)
            cr.fill()
            if i % 5 == 0:
                cr.set_source_rgba(c.red, c.green, c.blue, 0.6)
                cr.move_to(i * slot + 1, height - 3)
                cr.show_text(day.strftime("%d/%m"))


class ProjectsPage(Gtk.Box):
    """`ProjectsPage(window)` : `refresh()` et `show_project(path)`."""

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, vexpand=True, hexpand=True)
        self.window = window
        self.projects = []
        self.loaded = False
        self.cards = {}              # chemin du projet -> bouton de la carte
        self.detail = None           # page de détail ouverte
        self.detail_path = None
        self.open_button = None
        self.versions_box = self.chart = self.phases_box = None
        self.roadmap_view = None
        self._token = 0

        self.nav = Adw.NavigationView()
        self.append(self.nav)
        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                min_children_per_line=1, max_children_per_line=4,
                                column_spacing=12, row_spacing=12,
                                margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.stack = Gtk.Stack()
        self.stack.add_named(Adw.StatusPage(
            icon_name="folder-symbolic", title="Chargement…"), "loading")
        self.stack.add_named(Adw.StatusPage(
            icon_name="view-list-symbolic", title="Aucun projet avec feuille de route",
            description="Les projets où tu as ouvert une session Claude et qui ont un "
                        "ROADMAP.md apparaissent ici."), "empty")
        self.stack.add_named(Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                                child=self.flow), "cards")
        self.stack.set_visible_child_name("loading")
        self.root_page = Adw.NavigationPage(title="Projets", child=self.stack, tag="projets")
        self.nav.add(self.root_page)

    # ---- liste ----------------------------------------------------------------------

    def refresh(self):
        """Recalcule la liste des projets dans un fil."""
        self._token += 1
        token = self._token

        def work():
            hidden = settings.load_settings().get("projects", {}).get("hidden", [])
            return projects.list_projects(conversations.scan(), hidden)

        def done(found):
            if token == self._token:
                self._show_cards(found)

        in_thread(work, done)

    def _show_cards(self, found):
        self.projects, self.loaded = list(found), True
        self.cards = {}
        while (child := self.flow.get_first_child()) is not None:
            self.flow.remove(child)
        for project in self.projects:
            card = self._card(project)
            self.cards[str(project.path)] = card
            self.flow.append(card)
        self.stack.set_visible_child_name("cards" if self.projects else "empty")

    def _card(self, project):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["ccs-card"],
                      margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        head = Gtk.Box(spacing=8)
        head.append(Gtk.Label(label=project.name, xalign=0, hexpand=True, ellipsize=3,
                              css_classes=["title-4"]))
        if project.version:
            head.append(Gtk.Label(label=f"v{project.version}", css_classes=["ccs-chip", "accent"]))
        box.append(head)
        box.append(Gtk.Label(label=fmt_activity(project.last_activity), xalign=0,
                             css_classes=["ccs-subtle", "dim-label"]))
        phase = project.current_phase
        if phase is not None:
            box.append(Gtk.Label(label=phase.title, xalign=0, ellipsize=3))
            line = Gtk.Box(spacing=8)
            bar = gauge(phase.done_count, phase.total)
            bar.set_hexpand(True)
            line.append(bar)
            line.append(Gtk.Label(label=f"{phase.done_count}/{phase.total}",
                                  css_classes=["ccs-count"]))
            box.append(line)
        else:
            box.append(Gtk.Label(label=f"Toutes les phases sont finies ({project.done}/{project.total})",
                                 xalign=0, css_classes=["dim-label"]))
        button = Gtk.Button(child=box, css_classes=["flat"])
        button.connect("clicked", lambda _b, p=project.path: self.show_project(p))
        menu = Gio.Menu()
        menu.append("Masquer ce projet", "card.hide")
        more = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu, valign=Gtk.Align.START,
                              halign=Gtk.Align.END, css_classes=["flat", "circular"],
                              tooltip_text="Menu du projet", margin_top=6, margin_end=6)
        group = Gio.SimpleActionGroup()
        action = Gio.SimpleAction.new("hide", None)
        action.connect("activate", lambda *_a, p=project.path: self.hide_project(p))
        group.add_action(action)
        overlay = Gtk.Overlay(child=button)
        overlay.add_overlay(more)
        overlay.insert_action_group("card", group)
        overlay.hide_action = action
        overlay.menu_button = more
        return overlay

    def hide_project(self, path):
        """Retire le projet de la page (`projects.hidden`) ; « Réglages → Projets masqués » le
        réaffiche."""
        current = settings.load_settings()
        hidden = [str(h) for h in current.get("projects", {}).get("hidden", [])]
        key = str(path).rstrip("/")
        if key not in [h.rstrip("/") for h in hidden]:
            current.setdefault("projects", {})["hidden"] = hidden + [key]
            settings.save_settings(current)
        self.refresh()

    # ---- détail ---------------------------------------------------------------------

    def show_project(self, path):
        """Ouvre le détail du projet `path` (dossier du ROADMAP.md ou d'une session dedans)."""
        path = Path(path)
        match = next((p for p in self.projects if p.path == path), None)
        name = match.name if match else (path.name or str(path))
        if self.detail is not None:
            self.nav.pop_to_page(self.root_page)
            self._close_detail()
        self.detail_path = path
        page = Adw.NavigationPage(title=name, tag="detail")
        self.detail = page
        page.set_child(self._detail_content(path))
        self.nav.push(page)
        self._load_history(path)

    def _close_detail(self):
        if self.roadmap_view is not None:
            self.roadmap_view.close()
        self.detail = self.roadmap_view = self.detail_path = None

    def _detail_content(self, path):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                      margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.open_button = Gtk.Button(label="Ouvrir une session dans ce projet",
                                      halign=Gtk.Align.START, css_classes=["suggested-action"])
        self.open_button.connect("clicked", lambda _b: self.window.open_session(str(path)))
        box.append(self.open_button)

        self.roadmap_view = RoadmapView(path)
        self.roadmap_view.set_vexpand(False)
        self.roadmap_view.set_size_request(-1, 360)
        box.append(self.roadmap_view)

        box.append(Gtk.Label(label="Versions", xalign=0, css_classes=["title-4"]))
        self.versions_box = Gtk.Box(spacing=8)
        self.versions_box.append(Gtk.Label(label="Chargement…", css_classes=["dim-label"]))
        box.append(Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER,
                                      child=self.versions_box))

        box.append(Gtk.Label(label=f"Tâches cochées par jour ({DAYS_SHOWN} derniers jours)",
                             xalign=0, css_classes=["title-4"]))
        self.chart = DayBars()
        box.append(self.chart)

        box.append(Gtk.Label(label="Phases finies", xalign=0, css_classes=["title-4"]))
        self.phases_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE,
                                      css_classes=["boxed-list"])
        box.append(self.phases_box)

        header = Adw.HeaderBar()
        view = Adw.ToolbarView(content=Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=box))
        view.add_top_bar(header)
        return view

    def _load_history(self, path):
        def done(history):
            if self.detail_path == path:
                self._show_history(history)

        in_thread(lambda: projects.history(path), done)

    def _show_history(self, history):
        self.history = history
        clear(self.versions_box)
        if history.versions:
            for tag, day in history.versions:
                chip = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                               css_classes=["ccs-card", "flat"])
                chip.append(Gtk.Label(label=tag, css_classes=["heading"]))
                chip.append(Gtk.Label(label=fmt_day(day), css_classes=["caption", "dim-label"]))
                self.versions_box.append(chip)
        else:
            self.versions_box.append(Gtk.Label(label="Aucune version (pas de tag v* dans git).",
                                               css_classes=["dim-label"]))
        self.chart.set_data(last_days(history.checks_per_day))
        while (row := self.phases_box.get_first_child()) is not None:
            self.phases_box.remove(row)
        if history.phase_done:
            for title, day in history.phase_done.items():
                self.phases_box.append(Adw.ActionRow(
                    title=GLib.markup_escape_text(title), subtitle=f"finie le {fmt_day(day)}"))
        else:
            self.phases_box.append(Adw.ActionRow(title="Aucune phase finie datée dans git"))
