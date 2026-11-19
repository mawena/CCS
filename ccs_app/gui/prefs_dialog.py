"""Réglages : fenêtre à part (Adw.PreferencesDialog), ouverte par ☰ → Réglages ou Ctrl+, ; deuxième page :
Machines (calcul réparti)."""

from gi.repository import Adw

from .machines_page import MachinesPage
from .prefs import PrefsPage


class PrefsDialog(Adw.PreferencesDialog):
    def __init__(self, window):
        super().__init__(title="Réglages", search_enabled=True)
        self.window = window
        self.page = PrefsPage(window)
        self.page.render()
        self.add(self.page)
        self.machines = MachinesPage(toast=window.toast)
        self.add(self.machines)
