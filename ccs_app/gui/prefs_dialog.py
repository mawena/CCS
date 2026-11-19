"""Réglages : fenêtre à part (Adw.PreferencesDialog), ouverte par ☰ → Réglages ou Ctrl+,.
Deux pages : « Général » (les réglages) et « Machines » (relais Ricochet, travaux distants)."""

import os

from gi.repository import Adw

from .machines_page import MachinesPage
from .prefs import PrefsPage


def current_project(window):
    """Dossier proposé pour lancer une commande : le projet choisi dans Sessions, sinon le
    dossier personnel."""
    selected = getattr(getattr(window, "sessions", None), "selected", None)
    return selected if isinstance(selected, str) and os.path.isdir(selected) else os.path.expanduser("~")


class PrefsDialog(Adw.PreferencesDialog):
    def __init__(self, window):
        super().__init__(title="Réglages", search_enabled=True)
        self.window = window
        self.page = PrefsPage(window)
        self.page.set_title("Général")
        self.page.set_icon_name("preferences-system-symbolic")
        self.page.render()
        self.add(self.page)
        self.machines = MachinesPage(toast=getattr(window, "toast", None), default_cwd=current_project(window))
        self.add(self.machines)
