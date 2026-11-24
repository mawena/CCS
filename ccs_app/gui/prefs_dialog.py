"""Réglages : fenêtre à part (Adw.PreferencesDialog), ouverte par ☰ → Réglages ou Ctrl+,.
Machines, travaux distants et relais Ricochet sont dans l'onglet Réseau (network_page)."""

import os

from gi.repository import Adw

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
