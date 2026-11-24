"""Onglet « Réseau » : les appareils du réseau maillé (`tailscale status`, chemin réel par
« Mesurer ») puis les machines du relais, les travaux distants, le lancement d'une commande et
le secours Ricochet (MachinesPage), et le son partagé (SoundGroup, `audio.*` du serveur CCS). Même contenu que l'onglet web `#/reseau`, en plus simple.

`tailscale` est lent ou absent : il est appelé dans un fil, le résultat revient dans la page.
"""

from gi.repository import Adw, GLib, Gtk

from .. import audio, network
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


class SoundGroup(Adw.PreferencesGroup):
    """Son partagé : appareils annoncés, flux en cours, « Envoyer le son de … vers … », et
    l'interrupteur du service `ccs-audio` de ce PC (sorties virtuelles des autres appareils)."""

    def __init__(self, toast=None, runner=None, call=None, config=None, service=None):
        super().__init__(title="Son partagé",
                         description="Le son d'un appareil joué sur un autre (RTP/Opus sur le réseau maillé)")
        self.toast = toast or (lambda _t: None)
        self.runner = runner or _threaded
        self.call = call or audio.call
        self.config = config or audio.load_config
        self.service = service or audio.service
        self._rows = []
        self._loading = False
        self._timer = None
        self.devices = []
        cfg = self.config()
        self.switch = Adw.SwitchRow(title="Son partagé sur ce PC",
                                    subtitle="Annonce ce PC ; les autres appareils deviennent des sorties son",
                                    active=cfg["active"])
        self.switch.connect("notify::active", self._toggled)
        self.add(self.switch)
        self.connect("map", lambda _w: self.start_refresh())
        self.connect("unmap", lambda _w: self.stop_refresh())

    def start_refresh(self):
        if self._timer is None:
            self._timer = GLib.timeout_add_seconds(REFRESH_S, lambda: (self.refresh(), True)[1])
        self.refresh()

    def stop_refresh(self):
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _toggled(self, row, _pspec):
        on = row.get_active()

        def work():
            cfg = audio.load_config()
            cfg["active"] = on
            audio.save_config(cfg)
            return self.service("on" if on else "off")

        def done(res, error):
            ok, err = res if error is None else (False, str(error))
            self.toast(("Son partagé activé." if on else "Son partagé désactivé.") if ok
                       else f"ccs-audio : {err}")
        self.runner(work, done)

    def refresh(self):
        if self._loading:
            return
        self._loading = True
        self.runner(lambda: self.call("audio.list"), self._loaded)

    def _clear(self):
        for row in self._rows:
            self.remove(row)
        self._rows = []

    def _add(self, row):
        self.add(row)
        self._rows.append(row)

    def _label(self, name):
        return next((d["label"] for d in self.devices if d["device"] == name), name)

    def _loaded(self, listing, error):
        self._loading = False
        self._clear()
        if error is not None:
            self._add(Adw.ActionRow(title="Son partagé indisponible", subtitle=str(error)))
            return
        self.devices = listing.get("devices") or []
        if not self.devices:
            self._add(Adw.ActionRow(title="Aucun appareil annoncé",
                                    subtitle="CCS ouvert sur le téléphone, ou son partagé activé sur un PC"))
            return
        for d in self.devices:
            can = " + ".join(x for x, ok in (("joue", d["play"]), ("capte", d["capture"])) if ok) or "-"
            row = Adw.ActionRow(title=d["label"], subtitle=f"{d['device']} · {d['ip']} · {can}")
            row.add_prefix(Gtk.Image(icon_name="phone-symbolic" if d["system"] in ("android", "ios")
                                     else "audio-speakers-symbolic"))
            self._add(row)
        for st in listing.get("streams") or []:
            row = Adw.ActionRow(title=f"{self._label(st['source'])} → {self._label(st['target'])}",
                                subtitle=f"flux {st['stream']}")
            row.add_prefix(Gtk.Image(icon_name="media-playback-start-symbolic"))
            stop = Gtk.Button(label="Arrêter", valign=Gtk.Align.CENTER)
            stop.add_css_class("destructive-action")
            stop.connect("clicked", lambda _b, sid=st["stream"]: self._act("audio.stop", stream=sid))
            row.add_suffix(stop)
            self._add(row)
        sources = [d for d in self.devices if d["capture"]]
        outputs = [d for d in self.devices if d["play"]]
        if sources and outputs:
            self._add(self._send_row(sources, outputs))

    def _send_row(self, sources, outputs):
        row = Adw.ActionRow(title="Envoyer le son")
        src = Gtk.DropDown.new_from_strings([d["label"] for d in sources])
        dst = Gtk.DropDown.new_from_strings([d["label"] for d in outputs])
        if len(outputs) > 1 and outputs[0]["device"] == sources[0]["device"]:
            dst.set_selected(1)
        for w in (src, dst):
            w.set_valign(Gtk.Align.CENTER)
        go = Gtk.Button(label="Envoyer", valign=Gtk.Align.CENTER)
        go.add_css_class("suggested-action")
        go.connect("clicked", lambda _b: self._act(
            "audio.send", source=sources[src.get_selected()]["device"],
            target=outputs[dst.get_selected()]["device"]))
        row.add_suffix(src)
        row.add_suffix(Gtk.Label(label="→"))
        row.add_suffix(dst)
        row.add_suffix(go)
        return row

    def _act(self, method, **params):
        def done(_res, error):
            if error is not None:
                self.toast(str(error))
            self.refresh()
        self.runner(lambda: self.call(method, **params), done)


class NetworkPage(MachinesPage):
    def __init__(self, toast=None, default_cwd=None):
        self.mesh = MeshGroup(toast=toast)
        self.sound = SoundGroup(toast=toast)
        super().__init__(toast=toast, default_cwd=default_cwd, first_groups=(self.mesh, self.sound))
        self.set_title("Réseau")
