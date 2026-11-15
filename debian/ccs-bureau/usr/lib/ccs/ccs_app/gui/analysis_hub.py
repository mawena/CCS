"""Onglet Analyse : l'analyse (où part l'usage, conseils) et l'historique (courbes, journal des
bascules) derrière un sélecteur « Analyse | Historique »."""

from gi.repository import Gtk

from .analysis import AnalysisPage
from .common import load_state
from .history import HistoryPage

SUBS = ("analysis", "history")


class AnalysisHub(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.analysis = AnalysisPage(window)
        self.history = HistoryPage(window)
        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_titled(self.analysis, "analysis", "Analyse")
        self.stack.add_titled(self.history, "history", "Historique")
        self.switcher = Gtk.StackSwitcher(stack=self.stack, halign=Gtk.Align.CENTER,
                                          margin_top=10, margin_bottom=4)
        self.append(self.switcher)
        self.append(self.stack)
        self.stack.connect("notify::visible-child-name", lambda *_: self.on_shown())

    def current(self):
        return self.stack.get_visible_child_name()

    def show(self, sub=None):
        """Choisit « analysis » ou « history » (None : la partie déjà affichée)."""
        if sub in SUBS:
            self.stack.set_visible_child_name(sub)
        self.on_shown()

    def on_shown(self):
        """Charge la partie visible (l'onglet vient d'être affiché, ou la partie a changé)."""
        if self.current() == "history":
            self.history.render(load_state(), self.window.store)
        else:
            self.analysis.ensure_loaded()

    def reload(self, state, store, visible):
        """Nouveau relevé : la partie visible se met à jour (si l'onglet est affiché), l'autre
        garde la dernière version pour son prochain affichage."""
        if visible and self.current() == "analysis":
            self.analysis.budgets.refresh()
        if visible and self.current() == "history":
            self.history.render(state, store)
        else:
            self.history.last = (state, store)
