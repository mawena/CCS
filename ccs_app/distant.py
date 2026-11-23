"""Calcul réparti : lancer une commande sur une autre machine de Charles.

Les machines sont jointes en SSH directement par le réseau maillé (Headscale) quand elles y sont
en ligne ; sinon Ricochet (≥ 0.3.0), en secours, ouvre un tunnel vers leur serveur SSH. La liste
vient du relais Ricochet, complétée par `reseau` de `machines.toml` (elle suffit sans relais). Le
reste est du `ssh` et du `rsync` ordinaires. `ccs distant lancer -- <commande>` :

1. choisit la machine (celle qui a l'outil demandé, puis la moins chargée) ;
2. y copie le dossier du projet (seuls les fichiers changés repartent) ;
3. lance la commande, sortie au fil de l'eau, même code de retour ;
4. rapporte les fichiers demandés (`--rapatrier`).

Réglages : `~/.config/ricochet/client.toml` (adresse du relais et jeton des tunnels, lu aussi par
`ricochet-agent tunnel`) et, si besoin, `~/.config/ccs/machines.toml` (`[machines.<id>]` : `user`,
`port` SSH et `limit` de commandes simultanées ; `~/.config` suit `XDG_CONFIG_HOME`). Avant la
1.0.0 : `distant.toml` avec `utilisateur` et `limite`, renommé tout seul et encore lu.
"""

import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import core, distant_jobs, migrate, network

# Outils cherchés d'office sur chaque machine (les autres le sont à la demande).
TOOLS = ("flutter", "dart", "cargo", "node", "npm", "pnpm", "yarn", "bun", "go", "java",
         "gradle", "mvn", "docker", "python3", "uv", "make", "cmake", "gcc", "clang", "php",
         "composer", "dotnet", "adb")
# Premiers mots d'une commande qui ne désignent pas un outil à chercher.
SHELL_WORDS = {"cd", "sh", "bash", "env", "time", "nice", "exec", "test", "[", "true", "echo",
               "ls", "cat", "export", "set", "for", "if", "while"}
INVENTORY_TTL = 3600
REMOTE_BASE = ".cache/ccs-distant"
HINT = ("Calcul réparti : d'autres machines de Charles sont joignables (réseau maillé, Ricochet en secours). Si un outil "
        "manque sur cette machine (flutter, par exemple) ou pour un travail lourd (build, longue "
        "suite de tests), lance la commande ailleurs depuis le dossier du projet : "
        "`ccs distant lancer -- <commande>` (options : `--machine <id>`, `--rapatrier <chemin>` "
        "pour rapporter les fichiers produits, `--inclure <chemin>` pour envoyer un fichier que "
        "git ignore). Tu peux lancer plusieurs commandes en parallèle : chaque machine a un "
        "nombre de places, et une commande attend son tour si elles sont toutes prises. Pour "
        "garder cette machine légère, envoie les longues suites de tests la nuit : "
        "`ccs distant lancer --quand nuit --detache -- <commande>` (ou `--quand HH:MM`), puis "
        "`ccs distant travaux`, `ccs distant journal <id>` et `ccs distant arreter <id>`. "
        "`ccs distant machines` liste les machines, leur charge et leurs outils.")
DEFAULT_LIMIT = 2
LIMIT_RANGE = (1, 8)
MACHINE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
WHEN_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
POLL = 5.0


class DistantError(Exception):
    """Erreur à montrer telle quelle à l'utilisateur."""


@dataclass
class Machine:
    id: str
    name: str = ""
    online: bool = False
    host: str = ""
    ports: list = field(default_factory=list)
    cores: int = 0
    load: float = 0.0
    mem_used: int = 0
    mem_total: int = 0
    agent: str = ""

    @property
    def score(self):
        """Charge par cœur : la plus petite gagne."""
        return self.load / max(self.cores, 1)

    @property
    def local(self):
        return bool(self.host) and self.host == socket.gethostname()


# ------------------------------------------------------------------ réglages

def client_path():
    return core.xdg_home("config") / "ricochet" / "client.toml"


def overrides_path():
    d = core.ccs_dir("config")
    return migrate.renamed(d / "machines.toml", d / "distant.toml")


# anciennes clés de `[machines.<id>]` (avant la 1.0.0), lues encore : à retirer en 2.0
OLD_OVERRIDE_KEYS = {"utilisateur": "user", "limite": "limit"}


def _cache_dir():
    d = core.ccs_dir("cache")
    d.mkdir(parents=True, exist_ok=True)
    return d


def configured():
    """Le client Ricochet est réglé sur cette machine."""
    return client_path().is_file() and shutil.which("ricochet-agent") is not None


def hint():
    """Consigne ajoutée aux chats quand le calcul réparti est disponible."""
    try:
        return HINT if available() else None
    except OSError:
        return None


def load_client():
    path = client_path()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise DistantError(
            f"Ricochet n'est pas réglé : écris {path} (droits 600) avec\n"
            '  relais = "https://ricochet.mawena.cloud"\n'
            '  jeton = "<jeton des tunnels>"') from None
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise DistantError(f"{path} illisible : {e}") from None
    relais, jeton = str(data.get("relais", "")).rstrip("/"), str(data.get("jeton", ""))
    if not relais.startswith(("https://", "http://")) or not jeton:
        raise DistantError(f"{path} : il faut relais (https://…) et jeton")
    return {"relais": relais, "jeton": jeton}


def load_overrides():
    """Réglages par machine : `[machines.<id>]` avec `user`, `port` et `limit` (anciennes clés
    françaises converties)."""
    try:
        data = tomllib.loads(overrides_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise DistantError(f"{overrides_path()} illisible : {e}") from None
    machines = data.get("machines", {})
    if not isinstance(machines, dict):
        return {}
    for conf in machines.values():
        if isinstance(conf, dict):
            for old, new in OLD_OVERRIDE_KEYS.items():
                if old in conf:
                    conf.setdefault(new, conf.pop(old))
    return machines


# ------------------------------------------------------------------ machines

def parse_machines(items):
    out = []
    for m in items or []:
        info, etat = m.get("info") or {}, m.get("etat") or {}
        charge = etat.get("charge") or [0.0]
        out.append(Machine(
            id=str(m.get("id", "")), name=m.get("nom") or "", online=bool(m.get("connectee")),
            host=info.get("nom_hote", ""), ports=list(info.get("tunnels") or []),
            cores=int(etat.get("nombre_coeurs") or 0), load=float(charge[0]),
            mem_used=int(etat.get("memoire_utilisee") or 0),
            mem_total=int(etat.get("memoire_totale") or 0), agent=info.get("version_agent", "")))
    return out


def fetch_machines(client=None, opener=None):
    client = client or load_client()
    req = urllib.request.Request(client["relais"] + "/api/machines", headers={
        "Authorization": "Bearer " + client["jeton"], "User-Agent": "ccs"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=15) as r:
            return parse_machines(json.loads(r.read().decode("utf-8")))
    except urllib.error.HTTPError as e:
        why = "jeton refusé" if e.code in (401, 403) else f"erreur {e.code}"
        raise DistantError(f"Relais Ricochet {client['relais']} : {why}") from None
    except (OSError, ValueError) as e:
        raise DistantError(f"Relais Ricochet {client['relais']} injoignable : {e}") from None


def mesh_declared(overrides):
    """Machines de `machines.toml` qui ont un nom dans le réseau maillé (`reseau = "…"`)."""
    return {mid: conf["reseau"] for mid, conf in overrides.items()
            if isinstance(conf, dict) and isinstance(conf.get("reseau"), str) and conf["reseau"]}


def available():
    """Calcul réparti possible : Ricochet réglé, ou au moins une machine du réseau maillé."""
    if configured():
        return True
    try:
        return bool(mesh_declared(load_overrides()))
    except DistantError:
        return False


def list_machines(opener=None, peers=None, overrides=None):
    """Machines connues : liste du relais Ricochet, complétée par les machines de `machines.toml`
    qui ont un nom `reseau`, et en ligne dès que le réseau maillé les voit. Sans relais (éteint,
    injoignable ou non réglé), le réseau maillé suffit ; l'erreur du relais n'est levée que s'il
    ne reste aucune machine."""
    overrides = load_overrides() if overrides is None else overrides
    machines, err = [], None
    if configured():
        try:
            machines = fetch_machines(opener=opener)
        except DistantError as e:
            err = e
    known = {m.id for m in machines}
    for mid, name in mesh_declared(overrides).items():
        if mid not in known:
            machines.append(Machine(id=mid, name=(overrides[mid].get("nom") or mid), host=name))
    if machines:
        peers = mesh_peers() if peers is None else peers
        for m in machines:
            if not m.online and not m.local and mesh_address(m, overrides, peers):
                m.online = True
    if not machines and err is not None:
        raise err
    if not machines and not configured():
        load_client()                      # message « Ricochet n'est pas réglé »
    return machines


def ssh_port(machine, overrides):
    port = (overrides.get(machine.id) or {}).get("port")
    if port:
        return int(port)
    if not machine.ports:
        return None
    return 22 if 22 in machine.ports else machine.ports[0]


def target(machine, overrides):
    user = (overrides.get(machine.id) or {}).get("user")
    return f"{user}@{machine.id}" if user else machine.id


# ------------------------------------------------------------------ réseau maillé

MESH_TTL_S = 30
_mesh_cache = {"at": 0.0, "peers": None}


def mesh_peers(run=None, now=time.time):
    """Appareils en ligne du réseau maillé : {nom (minuscules) : IPv4}, vide sans tailscale. Gardé
    30 s : un lancement ouvre plusieurs connexions SSH."""
    t = now()
    if run is None and _mesh_cache["peers"] is not None and t - _mesh_cache["at"] < MESH_TTL_S:
        return _mesh_cache["peers"]
    peers = {}
    try:
        st = network.status(run=run)
    except Exception:  # noqa: BLE001 — pas de réseau maillé : on passe par Ricochet
        st = {"state": "", "peers": []}
    if st.get("state") == "Running":
        for d in st["peers"]:
            ip = next((i for i in d["ips"] if ":" not in i), None)
            if d["online"] and ip:
                for key in (d["name"], d["host"]):
                    if key:
                        peers.setdefault(key.lower(), ip)
    if run is None:
        _mesh_cache.update(at=t, peers=peers)
    return peers


def mesh_address(machine, overrides, peers=None):
    """Adresse de la machine dans le réseau maillé, ou None (Ricochet sert alors de tunnel).
    Nom cherché : `reseau` de `[machines.<id>]` (false pour toujours passer par Ricochet), puis
    l'identifiant Ricochet, puis le nom d'hôte."""
    conf = overrides.get(machine.id) or {}
    if conf.get("reseau") is False:
        return None
    peers = mesh_peers() if peers is None else peers
    for key in (conf.get("reseau"), machine.id, machine.host):
        if isinstance(key, str) and key and key.lower() in peers:
            return peers[key.lower()]
    return None


def ssh_options(machine, overrides, peers=None):
    common = {
        "HostKeyAlias": f"ricochet-{machine.id}",
        "StrictHostKeyChecking": "accept-new", "BatchMode": "yes",
        "ControlMaster": "auto", "ControlPath": str(_cache_dir() / "distant-%C"),
        "ControlPersist": "120", "ServerAliveInterval": "30", "LogLevel": "ERROR",
    }
    ip = mesh_address(machine, overrides, peers)
    if ip:
        # Réseau maillé : SSH direct sur l'adresse 100.64.x (réseau local quand c'est possible),
        # même clé d'hôte qu'à travers Ricochet.
        opts = {"HostName": ip, "Port": str(ssh_port(machine, overrides) or 22), **common}
        return [x for k, v in opts.items() for x in ("-o", f"{k}={v}")]
    agent = shutil.which("ricochet-agent")
    if not agent:
        raise DistantError("ricochet-agent (0.3.0 ou plus) n'est pas installé sur cette machine")
    port = ssh_port(machine, overrides)
    if port is None:
        raise DistantError(
            f"{machine.id} n'accepte pas de tunnel : ajoute [tunnel] ports = [22] à son "
            "/etc/ricochet/agent.toml (agent 0.3.0 ou plus)")
    proxy = f"{agent} tunnel %h --port {port} --config {client_path()}"
    opts = {"ProxyCommand": proxy, **common}
    return [x for k, v in opts.items() for x in ("-o", f"{k}={v}")]


def _ssh(machine, overrides, command, run=None, **kw):
    argv = ["ssh", *ssh_options(machine, overrides), target(machine, overrides), command]
    return (run or subprocess.run)(argv, **kw)


# ------------------------------------------------------------------ inventaire

def _inventory_file():
    d = _cache_dir()
    return migrate.renamed(d / "machines.json", d / "distant.json")


def _load_inventory():
    try:
        data = json.loads(_inventory_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_inventory(data):
    core.atomic_write_json(_inventory_file(), data)


def cached_inventory(machine_id, now=time.time):
    inv = _load_inventory().get(machine_id)
    # une entrée d'avant la 1.0.0 (`outils`, `quand`) n'a pas `checked_at` : périmée, relevée à nouveau
    if isinstance(inv, dict) and isinstance(inv.get("tools"), dict) \
            and now() - (inv.get("checked_at") or 0) < INVENTORY_TTL:
        return inv
    return None


def parse_inventory(text):
    path, tools = "", {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("CCS_PATH="):
            path = line[len("CCS_PATH="):]
        elif line.startswith(("CCS_TOOL=", "CCS_OUTIL=")):   # CCS_OUTIL : avant la 1.0.0
            name, _, where = line.partition("=")[2].partition("=")
            if name and where:
                tools[name] = where
    return path, tools


def inventory(machine, overrides, run=None, now=time.time, refresh=False):
    """Chemin de recherche et outils de la machine, gardés une heure.

    Le chemin est celui d'un shell interactif : c'est là (`~/.bashrc`) que flutter, cargo ou nvm
    s'ajoutent d'habitude, et un shell de commande ne le lit pas en entier.
    """
    if not refresh:
        inv = cached_inventory(machine.id, now)
        if inv:
            return inv
    probe = ("echo CCS_PATH=$PATH; for o in " + " ".join(TOOLS) +
             "; do p=$(type -P $o) && echo CCS_TOOL=$o=$p; done")
    path, tools = "", {}
    for shell in ("bash -lic", "bash -lc"):
        try:
            r = _ssh(machine, overrides, f"{shell} {shlex.quote(probe)} 2>/dev/null", run=run,
                     capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            continue
        if r.returncode == 255:
            last = ((r.stderr or "").strip().splitlines() or ["sans détail"])[-1]
            raise DistantError(f"{machine.id} : SSH refusé ou injoignable ({last})")
        path, tools = parse_inventory(r.stdout or "")
        if path:
            break
    if not path:
        raise DistantError(f"{machine.id} : impossible de lire son environnement")
    inv = {"path": path, "tools": tools, "checked_at": now()}
    data = _load_inventory()
    data[machine.id] = inv
    _save_inventory(data)
    return inv


def has_tool(machine, overrides, inv, tool, run=None):
    """L'outil est sur la machine ; un outil hors de la liste d'office est cherché puis retenu."""
    tools = inv.setdefault("tools", {})
    if tool in tools:
        return bool(tools[tool])
    cmd = f"PATH={shlex.quote(inv['path'])} type -P {shlex.quote(tool)}"
    r = _ssh(machine, overrides, f"bash -c {shlex.quote(cmd)}", run=run, capture_output=True,
             text=True, timeout=60, stdin=subprocess.DEVNULL)
    tools[tool] = (r.stdout or "").strip() if r.returncode == 0 else ""
    data = _load_inventory()
    data[machine.id] = inv
    _save_inventory(data)
    return bool(tools[tool])


def wanted_tool(command):
    """L'outil dont la commande a besoin : son premier mot, sauf mot du shell."""
    words = shlex.split(command[0]) if len(command) == 1 else list(command)
    if not words:
        return None
    first = words[0]
    if first in SHELL_WORDS or "=" in first or first.startswith((".", "/", "~")):
        return None
    return first


def eligible(machines, overrides, tool=None, wanted=None, run=None, now=time.time, why=None):
    """Machines où la commande peut tourner, la moins chargée d'abord (inventaire à la demande :
    on s'arrête dès que l'appelant a ce qu'il lui faut). `why` reçoit les raisons des refus."""
    why = why if why is not None else []
    if wanted:
        m = next((m for m in machines if m.id == wanted), None)
        if m is None:
            known = ", ".join(x.id for x in machines) or "aucune"
            raise DistantError(f"Machine inconnue : {wanted} (connues : {known})")
        if not m.online:
            raise DistantError(f"{m.id} est éteinte ou déconnectée de Ricochet")
        yield m, inventory(m, overrides, run=run, now=now)
        return
    for m in sorted(machines, key=lambda m: m.score):
        if m.local:
            why.append(f"{m.id} : c'est cette machine")
            continue
        if not m.online:
            why.append(f"{m.id} : hors ligne")
            continue
        if ssh_port(m, overrides) is None:
            why.append(f"{m.id} : tunnel non activé")
            continue
        try:
            inv = inventory(m, overrides, run=run, now=now)
            if tool and not has_tool(m, overrides, inv, tool, run=run):
                why.append(f"{m.id} : pas de {tool}")
                continue
        except DistantError as e:
            why.append(str(e))
            continue
        yield m, inv


def _none_available(tool, why):
    need = f" avec {tool}" if tool else ""
    return DistantError(f"Aucune machine disponible{need}.\n  " + "\n  ".join(why or ["aucune machine"]))


def choose(machines, overrides, tool=None, wanted=None, run=None, now=time.time):
    """La machine où lancer : celle demandée, sinon la moins chargée qui a l'outil."""
    why = []
    for m, inv in eligible(machines, overrides, tool, wanted, run, now, why):
        return m, inv
    raise _none_available(tool, why)


def limit_for(machine_id, overrides):
    """Nombre de commandes lancées en même temps sur la machine (`limit`, 2 par défaut)."""
    value = (overrides.get(machine_id) or {}).get("limit")
    if isinstance(value, int) and not isinstance(value, bool) and \
            LIMIT_RANGE[0] <= value <= LIMIT_RANGE[1]:
        return value
    return DEFAULT_LIMIT


# ------------------------------------------------------------------ heure de départ

def _local_tz():
    from .orchestrator import local_tz
    return local_tz()


def schedule(when, now=None):
    """(heure de départ ou None pour tout de suite, raison) pour `--quand nuit|HH:MM`."""
    when = (when or "").strip()
    t = time.time() if now is None else now
    if not when:
        return None, ""
    current = datetime.fromtimestamp(t, timezone.utc)
    if when == "nuit":
        from . import tasks
        from .settings import load_settings
        night = tasks.config(load_settings())["night"]
        win = tasks.night_window(current, night["start"], night["end"], _local_tz())
        if win is None or win[0] <= current < win[1]:
            return None, ""
        return win[0].timestamp(), f"programmé pour la nuit, à {night['start']}"
    if not WHEN_RE.match(when):
        raise DistantError(f"--quand {when} : il faut « nuit » ou une heure HH:MM")
    h, m = (int(x) for x in when.split(":"))
    local = current.astimezone(_local_tz())
    at = local.replace(hour=h, minute=m, second=0, microsecond=0)
    if at <= local:
        at = (local + timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0)
    return at.timestamp(), f"programmé à {when}"


# ------------------------------------------------------------------ projet

def project_root(cwd):
    """Racine du projet (dépôt git s'il y en a un) et chemin du dossier courant dedans."""
    cwd = Path(cwd).resolve()
    try:
        r = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=10)
        root = Path(r.stdout.strip()).resolve() if r.returncode == 0 and r.stdout.strip() else cwd
    except (OSError, subprocess.TimeoutExpired):
        root = cwd
    try:
        rel = cwd.relative_to(root)
    except ValueError:
        root, rel = cwd, Path(".")
    return root, rel


def remote_dir(root):
    """Dossier du projet sur l'autre machine, sous son dossier personnel."""
    digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:8]
    name = "".join(c if c.isalnum() or c in "-_." else "_" for c in root.name) or "projet"
    return f"{REMOTE_BASE}/{name}-{digest}"


def include_rules(root, cwd, paths):
    """Règles rsync qui forcent l'envoi de chemins que git ignore."""
    rules = []
    for p in paths:
        full = (Path(cwd) / p).resolve()
        try:
            rel = full.relative_to(root)
        except ValueError:
            raise DistantError(f"--inclure {p} : hors du projet") from None
        parts = rel.parts
        for i in range(1, len(parts)):
            rules.append("--include=/" + "/".join(parts[:i]) + "/")
        rules.append("--include=/" + "/".join(parts) + ("/***" if full.is_dir() else ""))
    return rules


def send_argv(machine, overrides, root, include=(), with_git=False, cwd=None):
    ssh = shlex.join(["ssh", *ssh_options(machine, overrides)])
    argv = ["rsync", "-az", "--delete", "-e", ssh, *include_rules(root, cwd or root, include)]
    if not with_git:
        argv.append("--exclude=/.git/")
    argv += ["--filter=:- .gitignore", f"{root}/",
             f"{target(machine, overrides)}:{remote_dir(root)}/"]
    return argv


def fetch_argv(machine, overrides, root, rel, path):
    ssh = shlex.join(["ssh", *ssh_options(machine, overrides)])
    inside = os.path.normpath(os.path.join(str(rel), path))
    if inside == ".." or inside.startswith("../") or os.path.isabs(path):
        raise DistantError(f"--rapatrier {path} : hors du projet")
    return ["rsync", "-azR", "-e", ssh,
            f"{target(machine, overrides)}:{remote_dir(root)}/./{inside}", f"{root}/"]


# Côté distant, la commande tourne dans sa propre session ; un garde lit l'entrée de la
# connexion SSH, qui ne reçoit jamais rien : sa fin (Ctrl+C, ssh ou ccs arrêtés, connexion
# perdue) veut dire « arrête », et tout le groupe reçoit TERM, puis KILL 5 s plus tard.
GUARD = """cd "$HOME/$1" || exit 1
export PATH="$2"
exec 3<&0
setsid bash -c "$3" </dev/null &
p=$!
{ while read -r _; do :; done <&3; kill -TERM -- -$p; sleep 5; kill -KILL -- -$p; } >/dev/null 2>&1 &
w=$!
exec 3<&-
wait $p
c=$?
kill $w 2>/dev/null
exit $c"""


def remote_command(root, rel, inv, command):
    line = command[0] if len(command) == 1 else shlex.join(command)
    where = remote_dir(root) + ("" if str(rel) == "." else "/" + Path(rel).as_posix())
    return " ".join(["exec bash -c", shlex.quote(GUARD), "ccs-distant",
                     shlex.quote(where), shlex.quote(inv["path"]), shlex.quote(line)])


def _attached(argv):
    """Lance ssh en gardant son entrée ouverte : la fermer arrête la commande distante."""
    def stop(signum, frame):
        raise KeyboardInterrupt
    try:
        previous = signal.signal(signal.SIGTERM, stop)
    except ValueError:  # pas dans le fil principal
        previous = None
    p = subprocess.Popen(argv, stdin=subprocess.PIPE)
    try:
        return subprocess.CompletedProcess(argv, p.wait())
    except KeyboardInterrupt:
        p.stdin.close()
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
        raise
    finally:
        if not p.stdin.closed:
            p.stdin.close()
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


def _trap_term():
    """SIGTERM (`ccs distant arreter`) devient une interruption, comme Ctrl+C."""
    def stop(signum, frame):
        raise KeyboardInterrupt
    try:
        return signal.signal(signal.SIGTERM, stop)
    except ValueError:  # pas dans le fil principal
        return None


def launch(command, machine=None, tool=None, fetch=(), include=(), with_git=False, cwd=None,
           run=None, say=None, opener=None, when="", job_id=None, detached=False,
           now=time.time, sleep=time.sleep, poll=POLL):
    """Envoie le projet, lance la commande ailleurs, rapporte les fichiers ; code de retour.

    Chaque lancement est inscrit au registre (`distant_jobs`) : il attend l'heure demandée
    (`when`), puis une place libre sur une machine, et son état avance jusqu'au bout."""
    say = say or (lambda text: print(f"[ccs distant] {text}", file=sys.stderr, flush=True))
    if not command:
        raise DistantError("Aucune commande : ccs distant lancer -- <commande>")
    cwd = cwd or os.getcwd()
    if job_id:
        job = distant_jobs.update(job_id, pid=os.getpid(), detached=bool(detached))
        if job is None:
            raise DistantError(f"Travail inconnu : {job_id}")
        not_before = job.get("not_before")
        why = job.get("why") or ""
    else:
        not_before, why = schedule(when, now())
        job_id = distant_jobs.create(command, cwd, machine=machine, tool=tool, when=when,
                                     not_before=not_before, why=why, detached=detached, now=now)
    previous = _trap_term()
    try:
        code, why = _launch(job_id, command, machine, tool, fetch, include, with_git, cwd, run,
                            say, opener, not_before, why, now, sleep, poll)
    except KeyboardInterrupt:
        distant_jobs.finish(job_id, "stopped", 130, "interrompu", now=now)
        say("interrompu")
        return 130
    except DistantError as e:
        distant_jobs.finish(job_id, "failed", None, str(e).splitlines()[0], now=now)
        raise
    except BaseException as e:
        distant_jobs.finish(job_id, "failed", None, f"erreur : {e}", now=now)
        raise
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)
    state = "done" if code == 0 else "stopped" if code == 130 else "failed"
    distant_jobs.finish(job_id, state, code, why, now=now)
    return code


def _wait(job_id, until, now, sleep, poll):
    while now() < until:
        if distant_jobs.stopped(job_id):
            raise KeyboardInterrupt
        sleep(max(min(poll, until - now()), 0))


def _launch(job_id, command, machine, tool, fetch, include, with_git, cwd, run, say, opener,
            not_before, why, now, sleep, poll):
    attached = run or _attached
    run = run or subprocess.run
    if not_before and now() < not_before:
        say(f"{why} (travail {job_id})")
        _wait(job_id, not_before, now, sleep, max(poll, 30.0))
    overrides = load_overrides()
    machines = list_machines(opener=opener)
    tool = tool or (None if machine else wanted_tool(command))
    refused, candidates, chosen = [], [], None
    for m, inv in eligible(machines, overrides, tool=tool, wanted=machine, run=run, why=refused):
        candidates.append((m, inv))
        if distant_jobs.reserve(job_id, m.id, limit_for(m.id, overrides), now=now)[0]:
            chosen = (m, inv)
            break
    if not candidates:
        raise _none_available(tool, refused)
    told = ""
    while chosen is None:
        busy = []
        for m, inv in candidates:
            ok, n = distant_jobs.reserve(job_id, m.id, limit_for(m.id, overrides), now=now)
            if ok:
                chosen = (m, inv)
                break
            busy.append(f"{m.id} ({n}/{limit_for(m.id, overrides)})")
        if chosen:
            break
        wait = "en attente d'une place sur " + ", ".join(busy)
        if wait != told:
            distant_jobs.update(job_id, state="waiting", why=wait, machine=machine)
            say(f"{wait} (travail {job_id})")
            told = wait
        _wait(job_id, now() + poll, now, sleep, poll)
    chosen, inv = chosen
    root, rel = project_root(cwd)
    say(f"{chosen.id} ({chosen.host or '?'}, charge {chosen.load:.1f} sur {chosen.cores} cœurs) : "
        f"envoi de {root.name}…")
    started = time.monotonic()
    r = _ssh(chosen, overrides, f'mkdir -p "$HOME"/{shlex.quote(remote_dir(root))}', run=run,
             stdin=subprocess.DEVNULL)
    if r.returncode:
        raise DistantError(f"{chosen.id} : SSH refusé ou injoignable (code {r.returncode})")
    r = run(send_argv(chosen, overrides, root, include, with_git, cwd))
    if r.returncode:
        raise DistantError(f"Envoi du projet vers {chosen.id} raté (rsync, code {r.returncode})")
    say(f"envoyé en {time.monotonic() - started:.0f} s ; lancement de la commande")
    distant_jobs.update(job_id, state="running")
    try:
        code = _ssh(chosen, overrides, remote_command(root, rel, inv, command),
                    run=attached).returncode
    except KeyboardInterrupt:
        say(f"interrompu : commande arrêtée sur {chosen.id}")
        return 130, f"interrompu : commande arrêtée sur {chosen.id}"
    why = ""
    if code == 255:
        why = f"connexion à {chosen.id} perdue (ou la commande a renvoyé 255)"
        say(why)
    elif code:
        why = f"la commande a renvoyé {code}"
    for path in fetch:
        if code and code != 0:
            say(f"commande en échec (code {code}) : {path} non rapatrié")
            continue
        r = run(fetch_argv(chosen, overrides, root, rel, path))
        say(f"{path} rapatrié" if r.returncode == 0
            else f"{path} : rien à rapatrier (rsync, code {r.returncode})")
        if r.returncode and not code:
            code, why = 1, f"{path} : rien à rapatrier"
    return code, why


# ------------------------------------------------------------------ page « Machines »

def _public(m):
    return {"id": m.id, "name": m.name or m.id, "online": m.online, "local": m.local,
            "cores": m.cores, "load": m.load, "mem_used": m.mem_used, "mem_total": m.mem_total,
            "tunnel": bool(m.ports)}


def machines_overview(fetch=None):
    """Machines, leurs outils connus, leurs places et leurs travaux ; ne lève jamais."""
    out = {"configured": False, "message": "", "machines": []}
    try:
        out["configured"] = available()
        if not out["configured"]:
            out["message"] = ("Calcul réparti non réglé sur ce serveur "
                              "(~/.config/ricochet/client.toml).")
            return out
        machines = (fetch or list_machines)()
        overrides = load_overrides()
        inv = _load_inventory()
        counts = distant_jobs.counts()
    except (DistantError, OSError, ValueError) as e:
        out["message"] = str(e)
        return out
    for m in machines:
        item = _public(m)
        tools = (inv.get(m.id) or {}).get("tools") or {}
        c = counts.get(m.id) or {}
        item.update(tools=sorted(k for k, v in tools.items() if v),
                    limit=limit_for(m.id, overrides), running=c.get("running", 0),
                    waiting=c.get("waiting", 0))
        out["machines"].append(item)
    return out


def _toml_key(key):
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key, ensure_ascii=False)


def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{_toml_key(k)} = {_toml_value(x)}" for k, x in v.items()) + "}"
    return json.dumps(str(v), ensure_ascii=False)


def toml_dump(data, prefix=()):
    """TOML simple (valeurs, listes, tables imbriquées) : de quoi réécrire nos réglages."""
    lines = [f"{_toml_key(k)} = {_toml_value(v)}" for k, v in data.items()
             if not isinstance(v, dict)]
    for k, v in data.items():
        if isinstance(v, dict):
            name = (*prefix, _toml_key(k))
            body = toml_dump(v, name).splitlines()
            if not v or any(not isinstance(x, dict) for x in v.values()):
                if lines:
                    lines.append("")
                lines.append(f"[{'.'.join(name)}]")
            elif lines and body:
                lines.append("")
            lines.extend(body)
    return "\n".join(lines) + ("\n" if lines and not prefix else "")


def _write_private(path, text):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_toml(path):
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise DistantError(f"{path} illisible : {e}") from None


def client_settings():
    """Réglages du client Ricochet et places par machine ; le jeton n'est jamais renvoyé."""
    try:
        data = _read_toml(client_path())
    except DistantError:
        data = {}
    try:
        overrides = load_overrides()
    except DistantError:
        overrides = {}
    limits = {}
    for mid, conf in overrides.items():
        value = conf.get("limit") if isinstance(conf, dict) else None
        if isinstance(value, int) and not isinstance(value, bool) and \
                LIMIT_RANGE[0] <= value <= LIMIT_RANGE[1]:
            limits[mid] = value
    relay, token_set, path = str(data.get("relais", "")), bool(data.get("jeton")), str(client_path())
    return {"relay": relay, "token_set": token_set, "path": path, "default_limit": DEFAULT_LIMIT,
            "limits": limits, "operator_set": bool(data.get("jeton_operateur")),
            # compatibilité 1.x (appli iPhone), à retirer en 2.0
            "relais": relay, "jeton_defini": token_set, "chemin": path,
            "limite_defaut": DEFAULT_LIMIT, "limites": limits}


def save_client(relay=None, token=None):
    """Écrit `~/.config/ricochet/client.toml` (droits 600) ; une valeur absente est gardée. Les
    clés du fichier (`relais`, `jeton`) ne changent pas."""
    path = client_path()
    data = _read_toml(path)
    if relay is not None:
        relay = str(relay).strip().rstrip("/")
        if not relay.startswith(("https://", "http://")):
            raise DistantError("L'adresse du relais doit commencer par https:// (ou http://).")
        data["relais"] = relay
    if token is not None:
        token = str(token).strip()
        if not token:
            raise DistantError("Le jeton est vide.")
        data["jeton"] = token
    _write_private(path, toml_dump(data))


def set_limit(machine_id, limit):
    """Écrit `limit` dans `[machines.<id>]` de `~/.config/ccs/machines.toml`."""
    if not isinstance(machine_id, str) or not MACHINE_ID.match(machine_id):
        raise DistantError("Machine invalide.")
    if isinstance(limit, bool) or not isinstance(limit, int) or \
            not LIMIT_RANGE[0] <= limit <= LIMIT_RANGE[1]:
        raise DistantError(f"La limite doit être un nombre de {LIMIT_RANGE[0]} à {LIMIT_RANGE[1]}.")
    path = overrides_path()
    data = _read_toml(path)
    machines = data.get("machines")
    if not isinstance(machines, dict):
        machines = data["machines"] = {}
    conf = machines.get(machine_id)
    if not isinstance(conf, dict):
        conf = machines[machine_id] = {}
    conf.pop("limite", None)
    conf["limit"] = limit
    _write_private(path, toml_dump(data))


# ------------------------------------------------------------------ ajout d'une machine

NEW_MACHINE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")   # règle de Ricochet
UNIX_USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
SSH_KEYS = ("id_ed25519", "id_ecdsa", "id_rsa")


def public_key(run=None):
    """Clé publique SSH de cette machine (celle que `ssh` présente aux autres) ; une clé ed25519
    sans phrase de passe est créée s'il n'y en a aucune (les travaux tournent sans terminal)."""
    ssh = Path.home() / ".ssh"
    for name in SSH_KEYS:
        pub = ssh / f"{name}.pub"
        if pub.is_file() and (ssh / name).is_file():
            return pub.read_text(encoding="utf-8").strip()
    ssh.mkdir(mode=0o700, exist_ok=True)
    key = ssh / "id_ed25519"
    try:
        (run or subprocess.run)(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C",
                                 f"ccs@{socket.gethostname()}", "-f", str(key)],
                                check=True, capture_output=True)
        return (ssh / "id_ed25519.pub").read_text(encoding="utf-8").strip()
    except (OSError, subprocess.CalledProcessError) as e:
        raise DistantError(f"Clé SSH impossible à créer ({key}) : {e}") from None


def operator_token():
    path = client_path()
    token = str(_read_toml(path).get("jeton_operateur", "")).strip()
    if not token:
        raise DistantError(
            f"Pour ajouter une machine, CCS a besoin du jeton opérateur du relais : ajoute "
            f'jeton_operateur = "…" à {path} (jeton de `ricochet-serveur jeton`, son empreinte '
            "dans jeton_operateur_sha256 de /etc/ricochet/serveur.toml).")
    return token


def mesh_join(machine_id, key=None):
    """Suite de la ligne « Ajouter un PC » : installe tailscale et inscrit la machine au réseau
    maillé sous le nom `machine_id`. None si cette machine n'est pas le serveur Headscale."""
    if key is None:
        if not shutil.which("headscale"):
            return None
        try:
            key = network.auth_key()
        except network.NetworkError:
            return None
    host = re.sub(r"[^a-z0-9-]", "-", machine_id.lower()).strip("-")[:63] or "machine"
    return host, "sudo sh -c " + shlex.quote(" && ".join(network.join_lines(key, host)))


def add_machine(machine_id, name=None, user=None, limit=None, ports=(22,), opener=None, run=None,
                mesh=None):
    """Déclare une machine dans Ricochet et renvoie la commande à coller sur elle (lien à usage
    unique, 15 min) : elle installe l'agent, le serveur SSH et la clé de cette machine, ouvre les
    ports aux tunnels et démarre l'agent. L'utilisateur et la limite vont dans `machines.toml`."""
    if not isinstance(machine_id, str) or not NEW_MACHINE_ID.match(machine_id):
        raise DistantError("Identifiant invalide : lettres, chiffres, - et _ (64 au plus).")
    user = (user or "").strip() or None
    if user is None or not UNIX_USER.match(user):
        raise DistantError("Indique l'utilisateur de la machine (nom Unix en minuscules).")
    name = (name or "").strip() or None
    if name and len(name) > 100:
        raise DistantError("Nom trop long (100 caractères au plus).")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)
                              or not LIMIT_RANGE[0] <= limit <= LIMIT_RANGE[1]):
        raise DistantError(f"La limite doit être un nombre de {LIMIT_RANGE[0]} à {LIMIT_RANGE[1]}.")
    client = load_client()
    token = operator_token()
    ports = sorted({int(p) for p in ports})
    body = {"id": machine_id, "nom": name, "utilisateur": user, "ports": ports,
            "cles_ssh": [public_key(run)] if 22 in ports else []}
    req = urllib.request.Request(
        client["relais"] + "/api/machines", data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                 "User-Agent": "ccs"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=15) as r:
            created = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace").strip()[:200]
        why = {401: "jeton opérateur refusé", 403: "jeton opérateur refusé",
               409: f"« {machine_id} » existe déjà (révoque-la dans Ricochet pour la recréer)"
               }.get(e.code, f"erreur {e.code} : {detail}")
        raise DistantError(f"Relais Ricochet : {why}") from None
    except (OSError, ValueError) as e:
        raise DistantError(f"Relais Ricochet {client['relais']} injoignable : {e}") from None
    link = created.get("lien")
    if not isinstance(link, str) or not link.startswith("/rejoindre/"):
        raise DistantError("Ce relais ne donne pas de lien d'installation : Ricochet 0.6.0 ou plus.")
    path = overrides_path()
    data = _read_toml(path)
    machines = data.get("machines")
    if not isinstance(machines, dict):
        machines = data["machines"] = {}
    conf = machines.setdefault(machine_id, {})
    if not isinstance(conf, dict):
        conf = machines[machine_id] = {}
    conf["user"] = user
    if limit is not None:
        conf["limit"] = limit
    command = f"curl -fsSL {client['relais']}{link} | sudo sh"
    joined = (mesh or mesh_join)(machine_id)
    if joined:
        conf["reseau"] = joined[0]
        command += " && " + joined[1]
    _write_private(path, toml_dump(data))
    return {"id": machine_id, "command": command, "mesh": bool(joined),
            "expires_s": int(created.get("expire_s") or 900)}


def describe(machines, overrides, probe=True, run=None):
    """Lignes de `ccs distant machines`."""
    lines = []
    for m in machines:
        label = m.id + (f" ({m.name})" if m.name else "")
        if not m.online:
            lines.append(f"{label} : hors ligne")
            continue
        mem = f"{m.mem_used / 2**30:.0f}/{m.mem_total / 2**30:.0f} Go" if m.mem_total else "?"
        head = f"{label} : en ligne, charge {m.load:.1f} sur {m.cores} cœurs, mémoire {mem}"
        if m.local:
            lines.append(head + " — cette machine")
            continue
        mesh = mesh_address(m, overrides)
        if mesh is None and ssh_port(m, overrides) is None:
            lines.append(head + " — tunnel non activé ([tunnel] dans son agent.toml)")
            continue
        lines.append(head + (f" — par le réseau maillé ({mesh})" if mesh else " — par Ricochet"))
        try:
            inv = inventory(m, overrides, run=run) if probe else cached_inventory(m.id)
        except DistantError as e:
            lines.append(f"  {e}")
            continue
        if inv:
            tools = sorted(k for k, v in inv.get("tools", {}).items() if v)
            lines.append("  outils : " + (", ".join(tools) or "aucun de la liste"))
    return lines
