"""Réseau maillé de tous les appareils (WireGuard, Headscale sur network.mawena.cloud).

Chaque appareil fait tourner le client `tailscale`, inscrit auprès du serveur Headscale du VPS.
Les appareils publient leurs adresses (interfaces locales, adresse publique vue par STUN) et
chaque liaison prend le meilleur chemin, choisi tout seul et revu quand un appareil change de
réseau : le **LAN** si deux appareils y sont ensemble, sinon **direct** par internet (percement de
NAT), sinon le **relais** DERP du VPS.

Ce module lit l'état du client local (`tailscale status --json`) et, sur le serveur, crée les clés
d'inscription jetables (`headscale preauthkeys create`).
"""

import ipaddress
import re
import json
import shutil
import subprocess

SERVER_URL = "https://network.mawena.cloud"
BASE_DOMAIN = "mesh.mawena.cloud"
DEFAULT_USER = "charles"
KEY_TTL = "15m"
INSTALL_URL = "https://tailscale.com/install.sh"

PATH_LABELS = {"self": "cet appareil", "lan": "réseau local", "direct": "direct par internet",
               "relay": "relais du VPS", "offline": "hors ligne", "idle": "en veille"}


class NetworkError(Exception):
    """Erreur lisible pour l'utilisateur."""


def _run(argv, run=None, timeout=15):
    run = run or subprocess.run
    try:
        return run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise NetworkError(f"`{argv[0]}` n'est pas installé sur cette machine.") from None
    except subprocess.TimeoutExpired:
        raise NetworkError(f"`{' '.join(argv)}` ne répond pas.") from None


def installed():
    return shutil.which("tailscale") is not None


def _host(endpoint):
    """« 192.168.1.5:41641 » ou « [2a02::1]:41641 » → adresse IP (ou None)."""
    if not endpoint:
        return None
    host = endpoint.rsplit(":", 1)[0].strip("[]")
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def is_local(ip):
    """Adresse d'un réseau local (privée ou lien local), hors plage du réseau maillé."""
    if ip is None:
        return False
    if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"):
        return False
    return ip.is_private or ip.is_link_local


def path_of(peer):
    """Chemin d'une liaison d'après l'état du pair dans `tailscale status --json`."""
    if not peer.get("Online"):
        return "offline"
    cur = peer.get("CurAddr") or ""
    if cur:
        return "lan" if is_local(_host(cur)) else "direct"
    if peer.get("Relay"):
        return "relay"
    return "idle"


def _short(dns_name):
    name = (dns_name or "").rstrip(".")
    suffix = "." + BASE_DOMAIN
    return name[: -len(suffix)] if name.endswith(suffix) else name.split(".")[0]


def _device(node, path):
    return {
        "name": _short(node.get("DNSName")) or node.get("HostName", "?"),
        "host": node.get("HostName", ""),
        "os": node.get("OS", ""),
        "ips": list(node.get("TailscaleIPs") or []),
        "online": bool(node.get("Online")) or path == "self",
        "path": path,
        "endpoint": node.get("CurAddr") or "",
        "relay": node.get("Relay") or "",
        "addrs": list(node.get("Addrs") or []),
        "rx": node.get("RxBytes", 0),
        "tx": node.get("TxBytes", 0),
    }


def parse_status(data):
    """`tailscale status --json` → {'state', 'self', 'peers'} lisible."""
    self_node = data.get("Self") or {}
    peers = [_device(p, path_of(p)) for p in (data.get("Peer") or {}).values()]
    order = {"self": 0, "lan": 1, "direct": 2, "relay": 3, "idle": 4, "offline": 5}
    peers.sort(key=lambda d: (order.get(d["path"], 9), d["name"]))
    return {
        "state": data.get("BackendState", ""),
        "self": _device(self_node, "self") if self_node else None,
        "peers": peers,
    }


def status(run=None):
    if not installed() and run is None:
        raise NetworkError("Cet appareil n'est pas dans le réseau : tailscale n'est pas installé.")
    r = _run(["tailscale", "status", "--json"], run=run)
    if r.returncode != 0 and not r.stdout.strip():
        raise NetworkError((r.stderr or "tailscale status a échoué").strip())
    try:
        return parse_status(json.loads(r.stdout))
    except json.JSONDecodeError:
        raise NetworkError("Réponse illisible de `tailscale status --json`.") from None


def describe(st):
    """Lignes affichées par `ccs reseau`."""
    if st["state"] != "Running":
        return [f"Réseau : {st['state'] or 'arrêté'} (tailscale up --login-server {SERVER_URL})"]
    lines = []
    for d in ([st["self"]] if st["self"] else []) + st["peers"]:
        ip = d["ips"][0] if d["ips"] else "-"
        via = PATH_LABELS.get(d["path"], d["path"])
        if d["path"] in ("lan", "direct") and d["endpoint"]:
            via += f" ({d['endpoint']})"
        elif d["path"] == "relay" and d["relay"]:
            via += f" ({d['relay']})"
        lines.append(f"{d['name']:<20} {ip:<16} {d['os']:<8} {via}")
    return lines


def ping(name, run=None):
    """Chemin et latence réels vers un appareil (`tailscale ping`) : {ok, path, via, ms} ou {ok, error}."""
    r = _run(["tailscale", "ping", "--c", "5", name], run=run, timeout=25)
    return parse_ping((r.stdout or "") + "\n" + (r.stderr or ""))


def ping_text(res):
    if not res.get("ok"):
        return res.get("error", "pas de réponse")
    return f"{PATH_LABELS.get(res['path'], res['path'])} ({res['via']}) : {res['ms']:g} ms"


# --- Côté serveur (VPS) : clés d'inscription ---------------------------------------------------

def _headscale(args, run=None):
    r = _run(["headscale", *args, "--output", "json"], run=run)
    if r.returncode != 0:
        raise NetworkError((r.stderr or r.stdout or "headscale a échoué").strip())
    try:
        return json.loads(r.stdout or "null")
    except json.JSONDecodeError:
        raise NetworkError("Réponse illisible de headscale.") from None


def user_id(name=DEFAULT_USER, run=None):
    users = _headscale(["users", "list"], run=run) or []
    for u in users:
        if u.get("name") == name:
            return str(u.get("id"))
    created = _headscale(["users", "create", name], run=run) or {}
    return str(created.get("id"))


def auth_key(user=DEFAULT_USER, ttl=KEY_TTL, run=None):
    """Clé d'inscription jetable (une machine, valable `ttl`)."""
    uid = user_id(user, run=run)
    data = _headscale(["preauthkeys", "create", "--user", uid, "--expiration", ttl], run=run) or {}
    key = data.get("key")
    if not key:
        raise NetworkError("headscale n'a pas rendu de clé.")
    return key


def join_lines(key, hostname=None):
    """Commandes shell qui installent tailscale et inscrivent la machine (root)."""
    up = f"tailscale up --login-server {SERVER_URL} --authkey {key} --accept-dns=false"
    if hostname:
        up += f" --hostname {hostname}"
    return [f"command -v tailscale >/dev/null || curl -fsSL {INSTALL_URL} | sh", up]


def server_nodes(run=None):
    """Appareils connus du serveur, avec leurs adresses publiées (interfaces et adresse publique)."""
    nodes = _headscale(["nodes", "list"], run=run) or []
    out = []
    for n in nodes:
        out.append({
            "id": n.get("id"),
            "name": n.get("given_name") or n.get("name", "?"),
            "host": n.get("name", ""),
            "ips": list(n.get("ip_addresses") or []),
            "online": bool(n.get("online")),
            "last_seen": (n.get("last_seen") or {}).get("seconds"),
            "created": (n.get("created_at") or {}).get("seconds"),
        })
    return out


NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _node_id(name, run=None):
    for n in server_nodes(run=run):
        if name in (n["name"], n["host"]):
            return str(n["id"])
    raise NetworkError(f"Appareil « {name} » inconnu du serveur.")


def rename(name, new, run=None):
    if not NAME_RE.match(new or ""):
        raise NetworkError("Nom invalide : lettres minuscules, chiffres et tirets.")
    _headscale(["nodes", "rename", "--identifier", _node_id(name, run), new], run=run)


def remove(name, run=None):
    _headscale(["nodes", "delete", "--identifier", _node_id(name, run), "--force"], run=run)


PING_RE = re.compile(r"pong from (?P<name>\S+) \((?P<ip>[^)]+)\) via (?P<via>.+?) in (?P<ms>[\d.]+)\s*ms")


def parse_ping(text):
    """Dernière ligne « pong from x (ip) via 192.168.1.5:41641 in 3ms » → {path, via, ms}."""
    for line in reversed((text or "").splitlines()):
        m = PING_RE.search(line)
        if not m:
            continue
        via = m["via"]
        if via.startswith("DERP("):
            path = "relay"
        else:
            path = "lan" if is_local(_host(via)) else "direct"
        return {"ok": True, "path": path, "via": via, "ms": float(m["ms"])}
    return {"ok": False, "error": (text or "pas de réponse").strip().splitlines()[-1][:200]
            if (text or "").strip() else "pas de réponse"}


REG_KEY_RE = re.compile(r"^[A-Za-z0-9:_-]{8,200}$")


def register(key, user=DEFAULT_USER, run=None):
    """Valide un appareil qui s'est connecté depuis l'appli Tailscale (Android, iPhone) : la clé
    affichée par la page https://network.mawena.cloud/register/<clé>."""
    key = (key or "").strip().rsplit("/", 1)[-1]
    if not REG_KEY_RE.match(key):
        raise NetworkError("Clé d'inscription invalide.")
    data = _headscale(["auth", "register", "--user", user, "--auth-id", key], run=run) or {}
    return data.get("given_name") or data.get("name") or "appareil"

