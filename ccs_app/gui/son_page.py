"""Écran « Son » du bureau, autonome : « Son partagé » (SoundGroup) et « Lecteurs » (PlayersGroup).

SonPage (Adw.PreferencesPage) réunit les deux groupes, pour un futur onglet « Son » ; en attendant,
network_page.py inclut simplement les deux groupes dans l'onglet Réseau. Les appels au pont
(`audio.list`, `audio.send`, `audio.stop`, `audio.control`) partent dans un fil.
"""

import time

from gi.repository import Adw, GLib, Gtk

from .. import audio
from .machines_page import REFRESH_S
from .servers_group import _threaded

STATUS = {"Playing": "▶", "Paused": "⏸", "Stopped": "■"}
HOLD_S = 3          # pas de redessin pendant le réglage du volume


def track_of(p):
    """« Titre — Artiste », ou un tiret."""
    return " — ".join(x for x in (p.get("title"), p.get("artist")) if x) or "—"


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


class PlayersGroup(Adw.PreferencesGroup):
    """Lecteurs (MPRIS) des PC Linux dont l'agent `ccs audio` tourne : ⏮ ⏯ ⏭, ±10 s si le lecteur
    sait se déplacer, et le volume. Mêmes données que le web (`players` de `audio.list`)."""

    def __init__(self, toast=None, runner=None, call=None):
        super().__init__(title="Lecteurs",
                         description="VLC, Firefox… des PC Linux (agent « ccs audio enable »)")
        self.toast = toast or (lambda _t: None)
        self.runner = runner or _threaded
        self.call = call or audio.call
        self._rows = []
        self._loading = False
        self._timer = None
        self._soon = None
        self._hold = 0.0
        self.connect("map", lambda _w: self.start_refresh())
        self.connect("unmap", lambda _w: self.stop_refresh())

    def start_refresh(self):
        if self._timer is None:
            self._timer = GLib.timeout_add_seconds(REFRESH_S, lambda: (self.refresh(), True)[1])
        self.refresh()

    def stop_refresh(self):
        for attr in ("_timer", "_soon"):
            if getattr(self, attr) is not None:
                GLib.source_remove(getattr(self, attr))
                setattr(self, attr, None)

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

    def _loaded(self, listing, error):
        self._loading = False
        if time.monotonic() < self._hold:
            return
        self._clear()
        if error is not None:
            self._add(Adw.ActionRow(title="Lecteurs indisponibles", subtitle=str(error)))
            return
        devices = [d for d in listing.get("devices") or [] if d.get("players") is not None]
        if not devices:
            self._add(Adw.ActionRow(title="Aucun PC ne publie ses lecteurs",
                                    subtitle="Sur un PC Linux : ccs audio enable"))
            return
        for d in devices:
            if not d["players"]:
                self._add(Adw.ActionRow(title=d.get("label") or d["device"],
                                        subtitle="Aucun lecteur ouvert"))
            for p in d["players"]:
                self._add(self._player_row(d, p))

    def _player_row(self, d, p):
        row = Adw.ActionRow(title=f"{STATUS.get(p.get('status'), '■')} {p.get('name', '?')} · "
                                  f"{d.get('label') or d['device']}",
                            subtitle=track_of(p))
        row.set_subtitle_lines(1)
        playing = p.get("status") == "Playing"
        keys = [("media-skip-backward-symbolic", "Précédent", "prev", None, p.get("can_prev", True)),
                ("media-playback-pause-symbolic" if playing else "media-playback-start-symbolic",
                 "Pause" if playing else "Lecture", "toggle", None,
                 p.get("can_pause", True) or p.get("can_play", True)),
                ("media-skip-forward-symbolic", "Suivant", "next", None, p.get("can_next", True))]
        if p.get("can_seek"):
            keys[1:1] = [("media-seek-backward-symbolic", "Reculer de 10 s", "seek", -10, True)]
            keys.insert(3, ("media-seek-forward-symbolic", "Avancer de 10 s", "seek", 10, True))
        for icon, tip, command, value, ok in keys:
            b = Gtk.Button(icon_name=icon, tooltip_text=tip, valign=Gtk.Align.CENTER, sensitive=bool(ok))
            b.add_css_class("flat")
            b.connect("clicked", lambda _b, c=command, v=value: self.control(d["device"], p, c, v))
            row.add_suffix(b)
        if p.get("volume") is not None:
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
            scale.set_value(p["volume"])
            scale.set_size_request(120, -1)
            scale.set_draw_value(False)
            scale.set_valign(Gtk.Align.CENTER)
            scale.set_tooltip_text(f"Volume de {p.get('name', '?')}")
            scale.connect("value-changed", lambda s: self._volume(d["device"], p, s))
            row.add_suffix(scale)
        return row

    def _volume(self, device, player, scale):
        """Glissement : on garde la page figée et on n'envoie que la dernière valeur (0,4 s)."""
        self._hold = time.monotonic() + HOLD_S
        if self._soon is not None:
            GLib.source_remove(self._soon)

        def send():
            self._soon = None
            self.control(device, player, "volume", round(scale.get_value()))
            return False
        self._soon = GLib.timeout_add(400, send)

    def control(self, device, player, command, value=None):
        params = {"device": device, "player": player["id"], "command": command}
        if value is not None:
            params["value"] = value

        def done(_res, error):
            if error is not None:
                self.toast(str(error))
            self._hold = 0.0
            GLib.timeout_add(600, lambda: (self.refresh(), False)[1])
        self.runner(lambda: self.call("audio.control", **params), done)


class SonPage(Adw.PreferencesPage):
    """L'écran Son seul : son partagé puis lecteurs."""

    def __init__(self, toast=None, sound=None, players=None):
        super().__init__(title="Son", icon_name="audio-speakers-symbolic")
        self.sound = sound if sound is not None else SoundGroup(toast=toast)
        self.players = players if players is not None else PlayersGroup(toast=toast)
        self.add(self.sound)
        self.add(self.players)
