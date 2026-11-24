"""Son partagé sur le réseau maillé, côté Linux (phase 42, protocole : `docs/audio.md`).

L'agent (`ccs audio agent`, service utilisateur `ccs-audio`) :

- annonce cette machine au pont du serveur CCS toutes les 30 s (`audio.announce`) : sortie (sait
  jouer) et source (sait capter le son de ses sorties PipeWire) ;
- crée une **sortie PipeWire virtuelle** pour chaque autre appareil qui sait jouer (« iPhone de
  Charles ») : choisie dans les réglages du son par une appli, elle lance l'envoi vers l'appareil
  (`audio.send`) ; restée muette 10 s, l'envoi s'arrête ;
- suit l'événement `audio` du pont : `receive` → GStreamer écoute en UDP et joue (RTP/Opus) ;
  `emit` → GStreamer capte le moniteur d'une sortie et émet ; `stop` → arrêt.

Le pont est joint par son socket quand cette machine héberge le serveur CCS (ticket fait avec la
clé du pont, lisible par l'utilisateur), sinon par le premier serveur appairé (`servers.json`).

Autres systèmes (même agent, `ccs audio agent` lancé à la main) : macOS et Windows jouent par
`autoaudiosink` ; Windows capte le son de sa sortie par `wasapi2src loopback=true`, macOS par un
périphérique de bouclage (BlackHole) donné dans `capture_device`. Pas de sorties virtuelles hors
de Linux : l'envoi se lance depuis `ccs audio envoyer` ou une autre appli CCS.

Réglages : `~/.config/ccs/audio.toml` (`active`, `port`, `label`, `capture_device` sur macOS). `ccs audio activer` l'écrit et
lance le service.
"""

import asyncio
import hashlib
import hmac
import ipaddress
import logging
import os
import platform
import re
import secrets
import shutil
import signal
import subprocess
import time
import tomllib
import unicodedata
from pathlib import Path

from . import network

log = logging.getLogger("ccs.audio")

DEFAULT_PORT = 4010
ANNOUNCE_EVERY = 30
POLL_S = 2
IDLE_STOP_S = 10            # sortie virtuelle muette depuis 10 s : envoi arrêté
RESEND_GAP_S = 5            # pas plus d'une demande d'envoi par sortie toutes les 5 s
LATENCY_MS = 100            # tampon de gigue du récepteur
SINK_PREFIX = "ccs_audio_"
MESH = ipaddress.ip_network("100.64.0.0/10")
RTP_CAPS = "application/x-rtp,media=audio,clock-rate=48000,encoding-name=OPUS,payload=96"
SERVICE = "ccs-audio.service"


class AudioError(Exception):
    pass


# ---- réglages ------------------------------------------------------------------------------

def config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "ccs" / "audio.toml"


def load_config(path=None):
    path = Path(path or config_path())
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        data = {}
    port = data.get("port", DEFAULT_PORT)
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        port = DEFAULT_PORT
    label = data.get("label") if isinstance(data.get("label"), str) else ""
    out = {"active": data.get("active") is True, "port": port, "label": label.strip()}
    if isinstance(data.get("capture_device"), str) and data["capture_device"].strip():
        out["capture_device"] = data["capture_device"].strip()
    return out


def save_config(cfg, path=None):
    path = Path(path or config_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    label = cfg.get("label", "").replace("\\", "").replace('"', "")
    dev = str(cfg.get("capture_device") or "").replace("\\", "").replace('"', "")
    capture = f'capture_device = "{dev}"\n' if dev else ""
    path.write_text(f'active = {"true" if cfg.get("active") else "false"}\n'
                    f'port = {int(cfg.get("port", DEFAULT_PORT))}\n'
                    f'label = "{label}"\n' + capture, encoding="utf-8")


# ---- identité sur le réseau maillé -----------------------------------------------------------

def mesh_ip(ips):
    for ip in ips or ():
        try:
            if ipaddress.ip_address(ip) in MESH:
                return ip
        except ValueError:
            continue
    return None


def identity(status):
    """(nom, adresse 100.64.x) de cette machine d'après `network.status()`."""
    me = (status or {}).get("self") or {}
    ip = mesh_ip(me.get("ips"))
    if not me.get("name") or not ip:
        raise AudioError("Cette machine n'est pas dans le réseau maillé (tailscale up).")
    return me["name"], ip


# ---- PipeWire (par pactl, la couche PulseAudio de PipeWire) ----------------------------------

def sink_name(device):
    return SINK_PREFIX + re.sub(r"[^A-Za-z0-9_]", "_", device)


def clean_label(text):
    text = unicodedata.normalize("NFC", str(text))
    return re.sub(r"[\"'\\\n\r\t]", "", text).strip()[:60] or "Appareil"


def parse_sinks(text):
    """`pactl list short sinks` → {nom: état} (RUNNING, IDLE, SUSPENDED)."""
    out = {}
    for line in text.splitlines():
        cols = line.split("\t")
        if len(cols) >= 5:
            out[cols[1]] = cols[4].strip()
    return out


def parse_modules(text):
    """`pactl list short modules` → {sortie ccs: id du module null-sink qui la crée}."""
    out = {}
    for line in text.splitlines():
        cols = line.split("\t")
        if len(cols) >= 3 and cols[1] == "module-null-sink":
            m = re.search(r"sink_name=(" + SINK_PREFIX + r"\w+)", cols[2])
            if m:
                out[m.group(1)] = cols[0]
    return out


class Pipewire:
    def __init__(self, run=subprocess.run):
        self._run = run

    def _pactl(self, *args):
        try:
            r = self._run(["pactl", *args], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise AudioError(f"pactl : {e}") from None
        if r.returncode != 0:
            raise AudioError((r.stderr or "pactl a échoué").strip())
        return r.stdout

    def sinks(self):
        return parse_sinks(self._pactl("list", "short", "sinks"))

    def modules(self):
        return parse_modules(self._pactl("list", "short", "modules"))

    def create(self, device, label):
        self._pactl("load-module", "module-null-sink", f"sink_name={sink_name(device)}",
                    # toute la valeur entre apostrophes : sans elles, PipeWire coupe au premier espace
                    f"""sink_properties='device.description="{clean_label(label)}"'""")

    def remove(self, sink):
        module = self.modules().get(sink)
        if module is not None:
            self._pactl("unload-module", module)

    def remove_all(self):
        for module in self.modules().values():
            try:
                self._pactl("unload-module", module)
            except AudioError:
                pass


# ---- GStreamer ---------------------------------------------------------------------------------

def this_system(name=None):
    """linux | macos | windows | autre."""
    name = (name or platform.system()).lower()
    return {"linux": "linux", "darwin": "macos", "windows": "windows"}.get(name, "autre")


def player_element(system):
    return ["pulsesink", "client-name=CCS"] if system == "linux" else ["autoaudiosink"]


def capture_elements(system, monitor=None, device=None):
    """Élément GStreamer qui capte le son joué par la machine, ou None si elle ne sait pas."""
    if system == "linux":
        return ["pulsesrc", f"device={monitor or '@DEFAULT_MONITOR@'}", "buffer-time=40000",
                "latency-time=10000", "client-name=CCS"]
    if system == "windows":
        return ["wasapi2src", "loopback=true", "low-latency=true"]
    if system == "macos" and device:
        return ["osxaudiosrc", f"device={device}"]
    return None


def receiver_argv(port, latency=LATENCY_MS, system="linux"):
    return ["gst-launch-1.0", "-q", "udpsrc", f"port={port}", f"caps={RTP_CAPS}", "!",
            "rtpjitterbuffer", f"latency={latency}", "drop-on-latency=true", "!",
            "rtpopusdepay", "!", "opusdec", "plc=true", "!", "audioconvert", "!", "audioresample",
            "!", *player_element(system)]


def sender_argv(monitor, ip, port, system="linux", device=None):
    src = capture_elements(system, monitor, device)
    if src is None:
        raise AudioError("Cette machine ne sait pas capter son son (macOS : capture_device).")
    return ["gst-launch-1.0", "-q", *src, "!", "audioconvert", "!", "audioresample", "!",
            "audio/x-raw,rate=48000,channels=2", "!", "opusenc", "bitrate=96000", "frame-size=20",
            "audio-type=generic", "!", "rtpopuspay", "pt=96", "!", "udpsink", f"host={ip}",
            f"port={port}", "sync=false", "async=false"]


def missing_tools(which=shutil.which, system=None):
    tools = ("gst-launch-1.0", "pactl") if (system or this_system()) == "linux" else ("gst-launch-1.0",)
    return [t for t in tools if which(t) is None]


class Process:
    """Un pipeline GStreamer lancé et arrêté proprement (SIGINT puis SIGKILL)."""

    def __init__(self, argv, popen=subprocess.Popen):
        self.argv = argv
        self.proc = popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, start_new_session=True)

    def alive(self):
        return self.proc.poll() is None

    def stop(self):
        if self.proc.poll() is not None:
            return
        try:
            self.proc.send_signal(signal.SIGINT)
            self.proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                self.proc.kill()
                self.proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass


# ---- connexion au pont du serveur ------------------------------------------------------------

class ServerSocketTransport:
    """Pont du serveur CCS hébergé sur cette machine : son socket, et un ticket fait avec sa clé
    (lisible par l'utilisateur, dans le dossier de son pont)."""
    needs_hello = True

    def __init__(self, socket_path, key_path):
        self.path, self.key_path = str(socket_path), str(key_path)
        self.label = "ce serveur"

    def hello_params(self):
        key = Path(self.key_path).read_bytes()
        h = secrets.token_hex(16)
        return {"session_hash": h, "ticket": hmac.new(key, h.encode(), hashlib.sha256).hexdigest()}

    async def connect(self):
        from .remote.client import _LocalLink
        from .server import rpc
        try:
            r, w = await asyncio.open_unix_connection(self.path, limit=rpc.MAX_LINE + 1)
        except OSError as e:
            raise ConnectionError(f"pont du serveur injoignable : {e}") from None
        return _LocalLink(r, w)


def server_transport(user=None, servers=None):
    """Transport vers le pont du serveur CCS : socket local si cette machine l'héberge, sinon le
    premier serveur appairé."""
    from .server import paths
    user = user or os.environ.get("USER") or ""
    try:
        sock, key = paths.bridge_socket(user), paths.bridge_key(user)
        if sock.exists() and os.access(key, os.R_OK):
            return ServerSocketTransport(sock, key)
    except ValueError:
        pass
    from .remote import client, servers as servers_mod
    known = servers if servers is not None else servers_mod.load()
    if not known:
        raise AudioError("Aucun serveur CCS appairé (appli CCS → Serveurs, ou `ccs tui`).")
    return client.WebTransport(known[0])


async def _with_bridge(fn, transport=None):
    from .remote.client import BridgeClient
    c = BridgeClient(transport or server_transport(), retry_delays=())
    try:
        await c.connect()
    except (ConnectionError, OSError) as e:
        raise AudioError(str(e)) from None
    try:
        return await fn(c)
    finally:
        await c.close()


def call(method, transport=None, **params):
    """Un appel au pont du serveur (commandes `ccs audio`)."""
    from .server import rpc

    async def go(c):
        try:
            return await c.call(method, **params)
        except rpc.RpcError as e:
            raise AudioError(e.message) from None
    return asyncio.run(_with_bridge(go, transport))


def resolve(devices, text, me=None):
    """Nom d'appareil d'après un nom ou un nom affiché approché (« ici » : cette machine)."""
    t = (text or "").strip().lower()
    if t in ("ici", "moi", "local") and me:
        return me
    for d in devices:
        if t == d["device"].lower():
            return d["device"]
    hits = [d["device"] for d in devices if t and (t in d["label"].lower() or t in d["device"].lower())]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise AudioError(f"Aucun appareil « {text} » (voir `ccs audio lister`).")
    raise AudioError(f"« {text} » désigne plusieurs appareils : {', '.join(hits)}.")


def describe(listing, me=None):
    devices, streams = listing.get("devices") or [], listing.get("streams") or []
    if not devices:
        return ["Aucun appareil annoncé (CCS ouvert sur le téléphone, `ccs audio activer` sur les PC)."]
    lines = []
    for d in devices:
        can = " + ".join(x for x, ok in (("joue", d["play"]), ("capte", d["capture"])) if ok) or "-"
        mark = " (ici)" if d["device"] == me else ""
        lines.append(f"{d['device']:<18} {d['label'][:24]:<24} {d['ip']:<15} {can}{mark}")
    for s in streams:
        lines.append(f"flux {s['stream']} : {s['source']} → {s['target']}")
    return lines


# ---- agent -------------------------------------------------------------------------------------

class Agent:
    def __init__(self, transport, name, ip, cfg, pipewire=None, popen=subprocess.Popen,
                 clock=time.monotonic, system="linux"):
        self.transport = transport
        self.system = system
        self.name, self.ip, self.cfg = name, ip, cfg
        # sorties virtuelles : Linux seulement (PipeWire / PulseAudio)
        self.pw = pipewire or (Pipewire() if system == "linux" else None)
        self._popen = popen
        self.clock = clock
        self.client = None
        self.devices = {}            # appareils annoncés (sauf moi)
        self.receiver = None         # (flux, Process)
        self.sender = None           # (flux, cible, Process, lancé par la sortie virtuelle ?)
        self.idle_since = {}         # sortie → muette depuis
        self.asked = {}              # cible → dernière demande d'envoi
        self._stop = asyncio.Event()

    # événements du pont
    def on_event(self, event, data):
        if event != "audio" or data.get("device") not in (None, self.name):
            if event == "audio" and data.get("action") == "stop":
                self._on_stop(data)
            return
        action = data.get("action")
        if action == "receive":
            self.start_receiver(data)
        elif action == "emit":
            self.start_sender(data)
        elif action == "stop":
            self._on_stop(data)

    def _on_stop(self, data):
        sid = data.get("stream")
        if self.receiver and self.receiver[0] == sid:
            self.stop_receiver()
        if self.sender and self.sender[0] == sid:
            self.stop_sender()

    def start_receiver(self, data):
        self.stop_receiver()
        log.info("réception de %s (flux %s)", data.get("from"), data.get("stream"))
        self.receiver = (data.get("stream"),
                         Process(receiver_argv(self.cfg["port"], system=self.system), self._popen))

    def stop_receiver(self):
        if self.receiver:
            self.receiver[1].stop()
            self.receiver = None

    def start_sender(self, data):
        target = data.get("to") or data.get("target")
        ip, port = data.get("ip"), data.get("port")
        if not target or not ip or not isinstance(port, int):
            return
        self.stop_sender()
        sink = sink_name(target)
        try:
            from_sink = self.pw is not None and self.pw.sinks().get(sink) == "RUNNING"
        except AudioError:
            from_sink = False
        monitor = f"{sink}.monitor" if from_sink else "@DEFAULT_MONITOR@"
        try:
            argv = sender_argv(monitor, ip, port, self.system, self.cfg.get("capture_device"))
        except AudioError as e:
            log.warning("%s", e)
            return
        log.info("émission vers %s (%s:%s) depuis %s", target, ip, port, monitor)
        self.sender = (data.get("stream"), target, Process(argv, self._popen), from_sink)

    def stop_sender(self):
        if self.sender:
            self.sender[2].stop()
            self.sender = None

    # annonce et sorties virtuelles
    def announcement(self):
        return {"device": self.name, "label": self.cfg.get("label") or self.name, "ip": self.ip,
                "port": self.cfg["port"], "play": True, "system": self.system,
                "capture": capture_elements(self.system, device=self.cfg.get("capture_device")) is not None}

    async def announce(self):
        r = await self.client.call("audio.announce", **self.announcement())
        listing = await self.client.call("audio.list")
        self.devices = {d["device"]: d for d in listing.get("devices") or []
                        if d["device"] != self.name}
        streams = {s["stream"] for s in listing.get("streams") or []}
        # flux arrêtés pendant une coupure : on ne joue plus dans le vide
        if self.receiver and self.receiver[0] not in streams:
            self.stop_receiver()
        if self.sender and self.sender[0] not in streams:
            self.stop_sender()
        return r

    def sync_sinks(self):
        """Une sortie virtuelle par appareil distant qui sait jouer ; les autres retirées."""
        if self.pw is None:
            return
        wanted = {sink_name(d): d for d, info in self.devices.items() if info.get("play")}
        have = self.pw.modules()
        for sink, device in wanted.items():
            if sink not in have:
                self.pw.create(device, self.devices[device]["label"])
        for sink in have:
            if sink not in wanted:
                self.pw.remove(sink)

    async def watch_sinks(self):
        """Sortie virtuelle utilisée → envoi ; muette 10 s → arrêt."""
        if self.pw is None:
            return
        try:
            states = self.pw.sinks()
        except AudioError:
            return
        now = self.clock()
        for device in list(self.devices):
            sink = sink_name(device)
            running = states.get(sink) == "RUNNING"
            if running:
                self.idle_since.pop(sink, None)
                busy = self.sender and self.sender[1] == device
                if not busy and now - self.asked.get(device, -1e9) >= RESEND_GAP_S:
                    self.asked[device] = now
                    try:
                        await self.client.call("audio.send", source=self.name, target=device)
                    except Exception as e:  # noqa: BLE001 — cible partie, hors ligne
                        log.warning("envoi vers %s refusé : %s", device, e)
            elif self.sender and self.sender[1] == device and self.sender[3]:
                since = self.idle_since.setdefault(sink, now)
                if now - since >= IDLE_STOP_S:
                    self.idle_since.pop(sink, None)
                    sid = self.sender[0]
                    self.stop_sender()
                    try:
                        await self.client.call("audio.stop", stream=sid)
                    except Exception:  # noqa: BLE001
                        pass

    async def run(self):
        from .remote.client import BridgeClient
        self.client = BridgeClient(self.transport)
        self.client.on_event = self.on_event
        await self.client.connect()
        try:
            if self.pw is not None:
                self.pw.remove_all()         # restes d'un agent précédent
        except AudioError as e:
            log.warning("%s", e)
        last = -1e9
        try:
            while not self._stop.is_set():
                if self.clock() - last >= ANNOUNCE_EVERY and self.client.online:
                    try:
                        await self.announce()
                        self.sync_sinks()
                        last = self.clock()
                    except Exception as e:  # noqa: BLE001 — pont coupé : on réessaie
                        log.warning("annonce : %s", e)
                        last = self.clock() - ANNOUNCE_EVERY + 5
                if self.client.online:
                    await self.watch_sinks()
                try:
                    await asyncio.wait_for(self._stop.wait(), POLL_S)
                except asyncio.TimeoutError:
                    pass
        finally:
            await self.shutdown()

    async def shutdown(self):
        self.stop_sender()
        self.stop_receiver()
        try:
            if self.pw is not None:
                self.pw.remove_all()
        except AudioError:
            pass
        if self.client:
            try:
                if self.client.online:
                    await self.client.call("audio.forget", device=self.name)
            except Exception:  # noqa: BLE001
                pass
            await self.client.close()

    def stop(self):
        self._stop.set()


def run_agent():
    """`ccs audio agent` : tourne jusqu'à SIGTERM/SIGINT."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    missing = missing_tools()
    if missing:
        raise AudioError("Manque : " + ", ".join(missing) + " (paquets gstreamer1.0-tools, "
                         "gstreamer1.0-plugins-good, gstreamer1.0-pulseaudio, pulseaudio-utils).")
    try:
        name, ip = identity(network.status())
    except network.NetworkError as e:
        raise AudioError(str(e)) from None
    agent = Agent(server_transport(), name, ip, load_config(), system=this_system())

    async def main():
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, agent.stop)
            except (NotImplementedError, RuntimeError):   # Windows : Ctrl+C arrête asyncio.run
                pass
        await agent.run()
    asyncio.run(main())


def service(action, run=subprocess.run):
    """systemctl --user enable --now / disable --now ccs-audio (Linux) ; ailleurs, l'agent se
    lance à la main."""
    if this_system() != "linux":
        return False, "pas de systemd ici : lance `ccs audio agent` (au démarrage de la session)"
    argv = ["systemctl", "--user", *(["enable", "--now"] if action == "on" else ["disable", "--now"]),
            SERVICE]
    r = run(argv, capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or "").strip()
