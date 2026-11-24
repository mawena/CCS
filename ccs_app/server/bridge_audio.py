"""Son partagé sur le réseau maillé (`audio.*`) : registre des sorties et des sources audio des
appareils CCS, et mise en relation d'une source avec une sortie. Toujours traité sur ce serveur,
même quand le web pilote une autre machine (comme `network.*`).

Pas de multicast sur Tailscale, donc pas de mDNS : chaque appareil annonce lui-même ce qu'il sait
faire (`audio.announce`, toutes les 30 s), il est oublié 90 s après sa dernière annonce.

`audio.send {source, target}` ouvre un flux : le pont pousse l'événement `audio` à tous les
appareils de l'utilisateur, `{"action": "receive", ...}` pour la cible (se mettre à écouter sur
son port UDP) puis `{"action": "emit", ...}` pour la source (émettre vers l'adresse maillée de la
cible). Chaque appareil ne garde que ce qui le concerne (`device`). `audio.stop` pousse
`{"action": "stop", ...}`. Le son lui-même ne passe jamais par le serveur : RTP/Opus en UDP direct
entre les adresses 100.64.x (voir `ccs_app/audio.py` et `docs/audio.md`).

Une sortie ne joue qu'un flux à la fois : un nouvel envoi vers elle arrête le précédent.
"""

import ipaddress
import itertools
import re
import time

from . import rpc

ANNOUNCE_EVERY = 30
FORGET_AFTER = 90
DEFAULT_PORT = 4010
MAX_DEVICES = 64
SYSTEMS = ("linux", "android", "ios", "macos", "windows", "web", "autre")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
# format du son, le même partout : RTP/Opus (RFC 7587), 48 kHz stéréo, trames de 10 ms (20 ms acceptées)
CODEC = {"codec": "opus", "rate": 48000, "channels": 2, "frame_ms": 10, "payload": 96}


def _invalid(text):
    return rpc.RpcError("invalide", text)


def _device_name(params, key):
    name = params.get(key)
    if not isinstance(name, str) or not NAME_RE.match(name.strip()):
        raise _invalid(f"Nom d'appareil invalide ({key}) : lettres, chiffres, points et tirets.")
    return name.strip()


class AudioApi:
    def __init__(self, bridge, clock=time.time):
        self.bridge = bridge
        self.clock = clock
        self.devices = {}            # nom → annonce (+ "seen")
        self.streams = {}            # id → {id, source, target, started}
        self._ids = itertools.count(1)
        bridge.add_handlers({
            "audio.announce": self.announce, "audio.forget": self.forget,
            "audio.list": self.list, "audio.send": self.send, "audio.stop": self.stop})
        hooks = getattr(bridge, "tick_hooks", None)
        if hooks is not None:
            hooks.append(self.sweep)

    # ---- registre ------------------------------------------------------------------------

    def _alive(self):
        now = self.clock()
        return {n: d for n, d in self.devices.items() if now - d["seen"] <= FORGET_AFTER}

    def _public(self, d):
        now = self.clock()
        return {k: d[k] for k in ("device", "label", "ip", "port", "play", "capture", "system")} | \
            {"age": round(now - d["seen"], 1)}

    async def sweep(self):
        """Oublie les appareils muets depuis 90 s et arrête leurs flux."""
        alive = self._alive()
        gone = set(self.devices) - set(alive)
        if not gone:
            return
        self.devices = alive
        for sid, s in list(self.streams.items()):
            if s["source"] in gone or s["target"] in gone:
                await self._end(sid, "appareil injoignable")

    async def announce(self, _conn, params):
        device = _device_name(params, "device")
        ip = params.get("ip")
        try:
            ip = str(ipaddress.ip_address(str(ip).strip()))
        except ValueError:
            raise _invalid("Adresse IP maillée manquante ou invalide.") from None
        port = params.get("port", DEFAULT_PORT)
        if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
            raise _invalid("Port UDP invalide (1024 à 65535).")
        label = params.get("label") or device
        if not isinstance(label, str):
            raise _invalid("Nom affiché invalide.")
        system = params.get("system") or "autre"
        if system not in SYSTEMS:
            system = "autre"
        if device not in self.devices and len(self._alive()) >= MAX_DEVICES:
            raise _invalid("Trop d'appareils annoncés.")
        self.devices[device] = {
            "device": device, "label": label.strip()[:60] or device, "ip": ip, "port": port,
            "play": bool(params.get("play")), "capture": bool(params.get("capture")),
            "system": system, "seen": self.clock()}
        mine = [self._stream_view(s) for s in self.streams.values() if device in (s["source"], s["target"])]
        return {"ok": True, "every": ANNOUNCE_EVERY, "forget_after": FORGET_AFTER, "streams": mine}

    async def forget(self, _conn, params):
        device = _device_name(params, "device")
        self.devices.pop(device, None)
        for sid, s in list(self.streams.items()):
            if device in (s["source"], s["target"]):
                await self._end(sid, "appareil parti")
        return {"ok": True}

    def _stream_view(self, s):
        return {"stream": s["id"], "source": s["source"], "target": s["target"],
                "started": s["started"]}

    async def list(self, _conn, _params):
        await self.sweep()
        outputs = sorted((self._public(d) for d in self.devices.values()),
                         key=lambda d: d["label"].lower())
        return {"devices": outputs, "streams": [self._stream_view(s) for s in self.streams.values()],
                "codec": CODEC, "every": ANNOUNCE_EVERY}

    # ---- flux ----------------------------------------------------------------------------

    async def _end(self, sid, reason=""):
        s = self.streams.pop(sid, None)
        if s is None:
            return
        await self.bridge.broadcast("audio", {"action": "stop", "stream": sid, "reason": reason,
                                              "devices": [s["source"], s["target"]],
                                              "source": s["source"], "target": s["target"]})

    async def send(self, _conn, params):
        await self.sweep()
        source, target = _device_name(params, "source"), _device_name(params, "target")
        if source == target:
            raise _invalid("La source et la sortie sont le même appareil.")
        src, dst = self.devices.get(source), self.devices.get(target)
        if src is None or dst is None:
            raise rpc.RpcError("introuvable", f"{source if src is None else target} n'est pas annoncé "
                                              "(CCS ouvert et réseau maillé connecté ?).")
        if not src["capture"]:
            raise _invalid(f"{src['label']} ne sait pas capter son son.")
        if not dst["play"]:
            raise _invalid(f"{dst['label']} ne sait pas jouer de son.")
        # une sortie, un flux ; une source, un flux
        for sid, s in list(self.streams.items()):
            if s["target"] == target or s["source"] == source:
                await self._end(sid, "remplacé")
        sid = f"a{next(self._ids)}"
        self.streams[sid] = {"id": sid, "source": source, "target": target, "started": self.clock()}
        common = {"stream": sid, "source": source, "target": target, **CODEC}
        await self.bridge.broadcast("audio", {
            "action": "receive", "device": target, "from": source, "from_label": src["label"],
            "from_ip": src["ip"], "port": dst["port"], **common})
        await self.bridge.broadcast("audio", {
            "action": "emit", "device": source, "to": target, "to_label": dst["label"],
            "ip": dst["ip"], "port": dst["port"], **common})
        return {"stream": sid, "ip": dst["ip"], "port": dst["port"], **CODEC}

    async def stop(self, _conn, params):
        sid = params.get("stream")
        if isinstance(sid, str) and sid:
            if sid not in self.streams:
                raise rpc.RpcError("introuvable", "Flux inconnu (déjà arrêté ?).")
            await self._end(sid, "arrêté")
            return {"ok": True, "stopped": [sid]}
        device = _device_name(params, "device")
        stopped = [sid for sid, s in self.streams.items() if device in (s["source"], s["target"])]
        for sid in stopped:
            await self._end(sid, "arrêté")
        return {"ok": True, "stopped": stopped}
