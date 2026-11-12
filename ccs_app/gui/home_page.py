"""Onglet Accueil : cartes des comptes, file de tâches et meilleur moment, fil des derniers
événements (bascules, tâches finies)."""

import time

from gi.repository import Adw, GLib, Graphene, Gtk

from .. import switch_log, tasks
from .accounts import AccountsPage
from .common import in_thread
from .planning import PlanningPage

EVENTS_SHOWN = 8
EVENTS_DAYS = 7
SUBPARTS = ("accounts", "planning", "events")


def recent_events(store, now=None, limit=EVENTS_SHOWN):
    """[(ts, icône, titre, détail)] des derniers événements, du plus récent au plus ancien :
    bascules de compte et tâches finies. Lit le journal et les tâches : hors de l'interface."""
    now = time.time() if now is None else now
    found = []
    try:
        for e in switch_log.load(store, days=EVENTS_DAYS, now=now):
            found.append((e.ts, "media-playlist-shuffle-symbolic" if e.ok else "dialog-warning-symbolic",
                          f"Bascule {e.title}", e.reason))
    except Exception:  # noqa: BLE001 — journal illisible : le reste s'affiche
        pass
    try:
        for t in tasks.all():
            if t.finished and t.state in tasks.FINISHED:
                icon = {tasks.DONE: "emblem-ok-symbolic", tasks.FAILED: "dialog-error-symbolic"}.get(
                    t.state, "process-stop-symbolic")
                found.append((t.finished, icon, f"Tâche {tasks.STATE_LABELS.get(t.state, t.state).lower()}",
                              tasks.summary(t) if hasattr(tasks, "summary") else t.message))
    except Exception:  # noqa: BLE001
        pass
    found.sort(key=lambda item: item[0], reverse=True)
    return found[:limit]


def _flatten(page):
    """Une page défilante dans l'Accueil : elle prend sa hauteur et laisse l'Accueil défiler."""
    if isinstance(page, Gtk.ScrolledWindow):
        page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        page.set_propagate_natural_height(True)
    page.set_vexpand(False)


class HomePage(Gtk.ScrolledWindow):
    def __init__(self, window):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.window = window
        self.accounts = AccountsPage(window)
        self.planning = PlanningPage(window)
        for page in (self.accounts, self.planning):
            _flatten(page)
        self.events_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        self.events_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=12,
                                   margin_end=12, margin_bottom=18)
        self.events_card.append(Gtk.Label(label="Derniers événements", xalign=0, css_classes=["title-4"]))
        self.events_card.append(self.events_list)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for part in (self.accounts, self.planning, Adw.Clamp(maximum_size=900, child=self.events_card)):
            self.body.append(part)
        self.set_child(self.body)
        self.events_card_widget = self.events_card.get_parent()

    # ---- rendu ---------------------------------------------------------------

    def render(self, state, store):
        self.accounts.render(state, store)
        self.planning.render(state)
        in_thread(lambda: recent_events(store), self.render_events)

    def render_events(self, events):
        while (row := self.events_list.get_first_child()) is not None:
            self.events_list.remove(row)
        if not events:
            self.events_list.append(Adw.ActionRow(title="Rien pour le moment",
                                                  subtitle="Les bascules et les tâches finies s'afficheront ici."))
        for ts, icon, title, detail in events:
            row = Adw.ActionRow(title=GLib.markup_escape_text(title),
                                subtitle=GLib.markup_escape_text(detail or ""))
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            row.add_suffix(Gtk.Label(label=time.strftime("%d/%m %H:%M", time.localtime(ts)),
                                     css_classes=["dim-label"]))
            self.events_list.append(row)

    # ---- navigation ----------------------------------------------------------

    def show(self, sub):
        """Fait défiler jusqu'à la partie demandée (« accounts », « planning », « events » ;
        None : le haut)."""
        target = {"planning": self.planning, "events": self.events_card_widget}.get(sub)
        adj = self.get_vadjustment()
        if target is None:
            adj.set_value(adj.get_lower())
            return

        def scroll():
            point = target.compute_point(self.body, Graphene.Point.zero())
            if point[0]:
                adj.set_value(max(adj.get_lower(), point[1].y))
            return False
        GLib.idle_add(scroll)
