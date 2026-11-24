"""Onglet « Market » (phase 45) : le chat Claude dédié à Facebook Marketplace au Togo. Le bouton
ouvre (ou retrouve) ce chat dans l'onglet Sessions : dossier `~/.local/share/ccs/market/`, dernière
conversation reprise. Claude y cherche par `ccs market …`, toujours par pc-bureau."""

from gi.repository import Adw, Gtk

DESCRIPTION = ("Pose une question (« le routeur le moins cher compatible WireGuard à Lomé ») ou "
               "donne le lien d'un vendeur : Market cherche sur Facebook Marketplace au Togo et "
               "répond par un classement avec les liens des annonces. Les recherches passent par "
               "pc-bureau ; la première fois, lance « ccs market login ».")


class MarketPage(Adw.Bin):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.status = Adw.StatusPage(icon_name="system-search-symbolic", title="Market",
                                     description=DESCRIPTION)
        self.open_button = Gtk.Button(label="Ouvrir le chat Market", halign=Gtk.Align.CENTER)
        self.open_button.add_css_class("pill")
        self.open_button.add_css_class("suggested-action")
        self.open_button.connect("clicked", lambda _b: self.activate_main())
        self.status.set_child(self.open_button)
        self.set_child(self.status)

    def activate_main(self):
        self.window.open_market()
