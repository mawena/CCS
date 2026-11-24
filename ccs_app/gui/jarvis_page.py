"""Onglet « Jarvis » : Jarvis se parle par la version web du serveur CCS appairé (micro du
navigateur, appairage et réponse vocale gérés là-bas). L'onglet dit à quel serveur on parlera et
ouvre la page ; sans serveur, il mène aux Réglages pour en ajouter un.
"""

from gi.repository import Adw, Gtk


class JarvisPage(Adw.Bin):
    def __init__(self, window, jarvis_url=None):
        super().__init__()
        self.window = window
        if jarvis_url is None:
            from ..remote import servers
            jarvis_url = servers.jarvis_url
        self.jarvis_url = jarvis_url
        self.status = Adw.StatusPage(icon_name="audio-input-microphone-symbolic", title="Jarvis")
        self.talk = Gtk.Button(label="Parler à Jarvis", halign=Gtk.Align.CENTER)
        self.talk.add_css_class("pill")
        self.talk.add_css_class("suggested-action")
        self.talk.connect("clicked", lambda _b: self.activate_main())
        self.status.set_child(self.talk)
        self.set_child(self.status)
        self.connect("map", lambda _w: self.update())

    def update(self):
        url = self.jarvis_url()
        if url:
            self.status.set_description(
                "L'assistant vocal de la maison. La conversation s'ouvre dans le navigateur, "
                f"sur la version web de CCS ({url.split('/#')[0]}), qui gère le micro.")
            self.talk.set_label("Parler à Jarvis")
        else:
            self.status.set_description(
                "Jarvis passe par la version web d'un serveur CCS : ajoute d'abord un serveur "
                "dans les Réglages.")
            self.talk.set_label("Ouvrir les Réglages")

    def activate_main(self):
        if self.jarvis_url():
            self.window.open_jarvis()
        else:
            self.window.show_prefs()
