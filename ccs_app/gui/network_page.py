"""Onglet « Réseau » : les appareils du réseau maillé (`tailscale status`, chemin réel par
« Mesurer ») puis les machines du relais, les travaux distants, le lancement d'une commande et
le secours Ricochet (MachinesPage). Même contenu que l'onglet web `#/reseau`, en plus simple.

`tailscale` est lent ou absent : il est appelé dans un fil, le résultat revient dans la page.
"""

from gi.repository import Adw, GLib, Gtk

from .. import network
from .machines_page import REFRESH_S, MachinesPage
from .servers_group import _threaded


def device_subtitle(d):
    """« 100.64.0.3 · android · direct par internet (1.2.3.4:41641) »."""
    parts = [d["ips"][0] if d["ips"] else "sans adresse"]
    if d.get("os"):
        parts.append(d["os"])
    via = network.PATH_LABELS.get(d["path"], d["path"])
    if d["path"] in ("lan", "direct") and d.get("endpoint"):
        via += f" ({d['endpoint']})"
    elif d["path"] == "relay" and d.get("relay"):
        via += f" ({d['relay']})"
    parts.append(via)
    return " · ".join(parts)


class MeshGroup(Adw.PreferencesGroup):
    def __init__(self, toast=None, runner=None, status=None, ping=None):
        super().__init__(title="Réseau maillé",
                         description=f"Appareils inscrits sur {network.SERVER_URL.split('//')[-1]}")
        self.toast = toast or (lambda _t: None)
        self.runner = runner or _threaded
        self.status = status or network.status
        self.ping = ping or network.ping
        self._rows = []
        self._loading = False
        self._timer = None
        self.connect("map", lambda _w: self.start_refresh())
        self.connect("unmap", lambda _w: self.stop_refresh())

    def start_refresh(self):
        if self._timer is None:
            self._timer = GLib.timeout_add_seconds(REFRESH_S * 2, lambda: (self.refresh(), True)[1])
        self.refresh()

    def stop_refresh(self):
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def refresh(self):
        if self._loading:
            return
        self._loading = True
        self.runner(self.status, self._loaded)

    def _clear(self):
        for row in self._rows:
            self.remove(row)
        self._rows = []

    def _add(self, row):
        self.add(row)
        self._rows.append(row)

    def _loaded(self, st, error):
        self._loading = False
        self._clear()
        if error is not None:
            self._add(Adw.ActionRow(title="Réseau maillé indisponible", subtitle=str(error)))
            return
        if st["state"] != "Running":
            self._add(Adw.ActionRow(title=f"Réseau : {st['state'] or 'arrêté'}",
                                    subtitle=f"tailscale up --login-server {network.SERVER_URL}"))
            return
        for d in ([st["self"]] if st["self"] else []) + st["peers"]:
            self._add(self._device_row(d))

    def _device_row(self, d):
        row = Adw.ActionRow(title=d["name"], subtitle=device_subtitle(d))
        row.set_subtitle_selectable(True)
        icon = "computer-symbolic"
        if d.get("os") in ("android", "iOS"):
            icon = "phone-symbolic"
        row.add_prefix(Gtk.Image(icon_name=icon))
        if not d["online"]:
            row.add_css_class("dim-label")
        if d["path"] != "self" and d["online"]:
            button = Gtk.Button(label="Mesurer", valign=Gtk.Align.CENTER,
                                tooltip_text="Chemin et latence réels (tailscale ping)")
            button.add_css_class("flat")
            button.connect("clicked", lambda b, name=d["name"]: self._measure(b, name))
            row.add_suffix(button)
        return row

    def _measure(self, button, name):
        button.set_sensitive(False)
        button.set_label("…")

        def done(res, error):
            button.set_sensitive(True)
            button.set_label("Mesurer")
            text = str(error) if error is not None else network.ping_text(res)
            self.toast(f"{name} : {text}")
        self.runner(lambda: self.ping(name), done)


class NetworkPage(MachinesPage):
    def __init__(self, toast=None, default_cwd=None):
        self.mesh = MeshGroup(toast=toast)
        super().__init__(toast=toast, default_cwd=default_cwd, first_groups=(self.mesh,))
        self.set_title("Réseau")
