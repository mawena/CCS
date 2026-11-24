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

Lecteurs (MPRIS, machines Linux) : l'agent les joint à son annonce et les rapporte dès qu'ils
changent (`audio.report`), le pont les garde avec l'appareil (`audio.list`, `audio.players`) et
pousse `{"action": "players", ...}`. `audio.control {device, player, command, value}` pousse
`{"action": "control", ...}` à la machine, qui exécute puis rapporte l'état ; `audio.players`
pousse `{"action": "players_refresh"}` pour une relecture immédiate.
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
PLAYER_COMMANDS = ("play", "pause", "toggle", "next", "prev", "seek", "volume")
PLAYER_STATUS = ("Playing", "Paused", "Stopped")
PLAYER_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,199}$")
MAX_PLAYERS = 16
CODEC = {"codec": "opus", "rate": 48000, "channels": 2, "frame_ms": 10, "payload": 96}


def _invalid(text):
    return rpc.RpcError("invalide", text)


def _text(v, limit):
    return v.strip()[:limit] if isinstance(v, str) else ""


def _num(v, low=0.0, high=1e7):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not low <= v <= high:
        return None
    return v


def clean_players(raw):
    """Lecteurs annoncés, nettoyés et bornés ; None si absent (appareil sans lecteurs pilotables)."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise _invalid("Lecteurs invalides (liste attendue).")
    out = []
    for p in raw[:MAX_PLAYERS]:
        if not isinstance(p, dict) or not isinstance(p.get("id"), str) or not PLAYER_ID_RE.match(p["id"]):
            continue
        vol = _num(p.get("volume"), 0, 100)
        out.append({
            "id": p["id"], "name": _text(p.get("name"), 80) or p["id"],
            "status": p.get("status") if p.get("status") in PLAYER_STATUS else "Stopped",
            "title": _text(p.get("title"), 200), "artist": _text(p.get("artist"), 200),
            "position": _num(p.get("position")), "length": _num(p.get("length")),
            "volume": round(vol) if vol is not None else None,
            **{k: bool(p.get(k)) for k in ("can_play", "can_pause", "can_next", "can_prev", "can_seek")},
            "can_control": bool(p.get("can_control", True))})
    return out


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
            "audio.list": self.list, "audio.send": self.send, "audio.stop": self.stop,
            "audio.report": self.report, "audio.players": self.players, "audio.control": self.control})
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
            {"age": round(now - d["seen"], 1), "players": d.get("players")}

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
        players = clean_players(params.get("players"))
        if players is None and "players" not in params and device in self.devices:
            players = self.devices[device].get("players")
        self.devices[device] = {"players": players,
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

    # ---- lecteurs (MPRIS) ----------------------------------------------------------------

    def _known(self, device):
        d = self._alive().get(device)
        if d is None:
            raise rpc.RpcError("introuvable", f"{device} n'est pas annoncé (agent `ccs audio` lancé ?).")
        return d

    async def report(self, _conn, params):
        """L'agent d'une machine rapporte ses lecteurs (changement, ou après une commande)."""
        device = _device_name(params, "device")
        d = self._known(device)
        d["players"] = clean_players(params.get("players")) or []
        d["seen"] = self.clock()
        await self.bridge.broadcast("audio", {"action": "players", "device": device,
                                              "players": d["players"]})
        return {"ok": True}

    async def players(self, _conn, params):
        """Lecteurs connus (d'une machine, ou de toutes) ; demande aux agents de les relire."""
        await self.sweep()
        device = _device_name(params, "device") if params.get("device") else None
        if device is not None:
            self._known(device)
        await self.bridge.broadcast("audio", {"action": "players_refresh", "device": device})
        return {"devices": [{"device": d["device"], "label": d["label"], "players": d.get("players")}
                            for d in sorted(self.devices.values(), key=lambda d: d["label"].lower())
                            if device in (None, d["device"]) and d.get("players") is not None]}

    async def control(self, _conn, params):
        """`{device, player, command, value?}` → poussé à la machine, qui exécute et rapporte."""
        device = _device_name(params, "device")
        d = self._known(device)
        player, command, value = params.get("player"), params.get("command"), params.get("value")
        if not isinstance(player, str) or not PLAYER_ID_RE.match(player):
            raise _invalid("Lecteur invalide.")
        if command not in PLAYER_COMMANDS:
            raise _invalid(f"Commande invalide : {', '.join(PLAYER_COMMANDS)}.")
        if isinstance(value, bool) or (value is not None and not isinstance(value, (int, float, str))):
            raise _invalid("Valeur invalide.")
        if isinstance(value, str) and len(value) > 16:
            raise _invalid("Valeur invalide.")
        if command == "volume" and value is None:
            raise _invalid("Volume manquant (0 à 100).")
        known = d.get("players")
        if known is None:
            raise _invalid(f"{d['label']} ne rapporte pas de lecteurs (agent Linux à jour ?).")
        if player not in {p["id"] for p in known}:
            raise rpc.RpcError("introuvable", f"Lecteur « {player} » inconnu sur {d['label']}.")
        await self.bridge.broadcast("audio", {"action": "control", "device": device, "player": player,
                                              "command": command, "value": value})
        return {"ok": True}
