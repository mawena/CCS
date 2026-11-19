"""Calcul réparti : lancer une commande sur une autre machine du réseau Ricochet.

Ricochet (≥ 0.3.0) ouvre un tunnel vers le serveur SSH d'une machine, même sans IP publique ;
le reste est du `ssh` et du `rsync` ordinaires. `ccs distant lancer -- <commande>` :

1. choisit la machine (celle qui a l'outil demandé, puis la moins chargée) ;
2. y copie le dossier du projet (seuls les fichiers changés repartent) ;
3. lance la commande, sortie au fil de l'eau, même code de retour ;
4. rapporte les fichiers demandés (`--rapatrier`).

Réglages : `~/.config/ricochet/client.toml` (adresse du relais et jeton des tunnels, lu aussi par
`ricochet-agent tunnel`) et, si besoin, `~/.config/ccs/distant.toml` (utilisateur et port SSH
par machine).
"""

import hashlib
import json
import os
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
from pathlib import Path

from . import core

# Outils cherchés d'office sur chaque machine (les autres le sont à la demande).
TOOLS = ("flutter", "dart", "cargo", "node", "npm", "pnpm", "yarn", "bun", "go", "java",
         "gradle", "mvn", "docker", "python3", "uv", "make", "cmake", "gcc", "clang", "php",
         "composer", "dotnet", "adb")
# Premiers mots d'une commande qui ne désignent pas un outil à chercher.
SHELL_WORDS = {"cd", "sh", "bash", "env", "time", "nice", "exec", "test", "[", "true", "echo",
               "ls", "cat", "export", "set", "for", "if", "while"}
INVENTORY_TTL = 3600
REMOTE_BASE = ".cache/ccs-distant"
HINT = ("Calcul réparti : d'autres machines de Charles sont joignables par Ricochet. Si un outil "
        "manque sur cette machine (flutter, par exemple) ou pour un travail lourd (build, longue "
        "suite de tests), lance la commande ailleurs depuis le dossier du projet : "
        "`ccs distant lancer -- <commande>` (options : `--machine <id>`, `--rapatrier <chemin>` "
        "pour rapporter les fichiers produits, `--inclure <chemin>` pour envoyer un fichier que "
        "git ignore). `ccs distant machines` liste les machines, leur charge et leurs outils.")


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

def _config_home():
    return core.paths().home / ".config"


def client_path():
    return _config_home() / "ricochet" / "client.toml"


def overrides_path():
    return _config_home() / "ccs" / "distant.toml"


def _cache_dir():
    d = core.paths().home / ".cache" / "ccs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def configured():
    """Le client Ricochet est réglé sur cette machine."""
    return client_path().is_file() and shutil.which("ricochet-agent") is not None


def hint():
    """Consigne ajoutée aux chats quand le calcul réparti est disponible."""
    try:
        return HINT if configured() else None
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
    """Réglages par machine : `[machines.<id>]` avec `utilisateur` et `port`."""
    try:
        data = tomllib.loads(overrides_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise DistantError(f"{overrides_path()} illisible : {e}") from None
    machines = data.get("machines", {})
    return machines if isinstance(machines, dict) else {}


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


def ssh_port(machine, overrides):
    port = (overrides.get(machine.id) or {}).get("port")
    if port:
        return int(port)
    if not machine.ports:
        return None
    return 22 if 22 in machine.ports else machine.ports[0]


def target(machine, overrides):
    user = (overrides.get(machine.id) or {}).get("utilisateur")
    return f"{user}@{machine.id}" if user else machine.id


def ssh_options(machine, overrides):
    agent = shutil.which("ricochet-agent")
    if not agent:
        raise DistantError("ricochet-agent (0.3.0 ou plus) n'est pas installé sur cette machine")
    port = ssh_port(machine, overrides)
    if port is None:
        raise DistantError(
            f"{machine.id} n'accepte pas de tunnel : ajoute [tunnel] ports = [22] à son "
            "/etc/ricochet/agent.toml (agent 0.3.0 ou plus)")
    proxy = f"{agent} tunnel %h --port {port} --config {client_path()}"
    opts = {
        "ProxyCommand": proxy, "HostKeyAlias": f"ricochet-{machine.id}",
        "StrictHostKeyChecking": "accept-new", "BatchMode": "yes",
        "ControlMaster": "auto", "ControlPath": str(_cache_dir() / "distant-%C"),
        "ControlPersist": "120", "ServerAliveInterval": "30", "LogLevel": "ERROR",
    }
    return [x for k, v in opts.items() for x in ("-o", f"{k}={v}")]


def _ssh(machine, overrides, command, run=None, **kw):
    argv = ["ssh", *ssh_options(machine, overrides), target(machine, overrides), command]
    return (run or subprocess.run)(argv, **kw)


# ------------------------------------------------------------------ inventaire

def _inventory_file():
    return _cache_dir() / "distant.json"


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
    if inv and now() - inv.get("quand", 0) < INVENTORY_TTL:
        return inv
    return None


def parse_inventory(text):
    path, tools = "", {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("CCS_PATH="):
            path = line[len("CCS_PATH="):]
        elif line.startswith("CCS_OUTIL="):
            name, _, where = line[len("CCS_OUTIL="):].partition("=")
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
             "; do p=$(type -P $o) && echo CCS_OUTIL=$o=$p; done")
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
    inv = {"path": path, "outils": tools, "quand": now()}
    data = _load_inventory()
    data[machine.id] = inv
    _save_inventory(data)
    return inv


def has_tool(machine, overrides, inv, tool, run=None):
    """L'outil est sur la machine ; un outil hors de la liste d'office est cherché puis retenu."""
    tools = inv.setdefault("outils", {})
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


def choose(machines, overrides, tool=None, wanted=None, run=None, now=time.time):
    """La machine où lancer : celle demandée, sinon la moins chargée qui a l'outil."""
    if wanted:
        m = next((m for m in machines if m.id == wanted), None)
        if m is None:
            known = ", ".join(x.id for x in machines) or "aucune"
            raise DistantError(f"Machine inconnue : {wanted} (connues : {known})")
        if not m.online:
            raise DistantError(f"{m.id} est éteinte ou déconnectée de Ricochet")
        return m, inventory(m, overrides, run=run, now=now)
    why = []
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
        return m, inv
    need = f" avec {tool}" if tool else ""
    raise DistantError(f"Aucune machine disponible{need}.\n  " + "\n  ".join(why or ["aucune machine"]))


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


def launch(command, machine=None, tool=None, fetch=(), include=(), with_git=False, cwd=None,
           run=None, say=None, opener=None):
    """Envoie le projet, lance la commande ailleurs, rapporte les fichiers ; code de retour."""
    say = say or (lambda text: print(f"[ccs distant] {text}", file=sys.stderr, flush=True))
    if not command:
        raise DistantError("Aucune commande : ccs distant lancer -- <commande>")
    cwd = cwd or os.getcwd()
    attached = run or _attached
    run = run or subprocess.run
    overrides = load_overrides()
    machines = fetch_machines(opener=opener)
    tool = tool or (None if machine else wanted_tool(command))
    chosen, inv = choose(machines, overrides, tool=tool, wanted=machine, run=run)
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
    try:
        code = _ssh(chosen, overrides, remote_command(root, rel, inv, command),
                    run=attached).returncode
    except KeyboardInterrupt:
        say(f"interrompu : commande arrêtée sur {chosen.id}")
        return 130
    if code == 255:
        say(f"connexion à {chosen.id} perdue (ou la commande a renvoyé 255)")
    for path in fetch:
        if code and code != 0:
            say(f"commande en échec (code {code}) : {path} non rapatrié")
            continue
        r = run(fetch_argv(chosen, overrides, root, rel, path))
        say(f"{path} rapatrié" if r.returncode == 0
            else f"{path} : rien à rapatrier (rsync, code {r.returncode})")
        if r.returncode and not code:
            code = 1
    return code


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
        if ssh_port(m, overrides) is None:
            lines.append(head + " — tunnel non activé ([tunnel] dans son agent.toml)")
            continue
        lines.append(head)
        try:
            inv = inventory(m, overrides, run=run) if probe else cached_inventory(m.id)
        except DistantError as e:
            lines.append(f"  {e}")
            continue
        if inv:
            tools = sorted(k for k, v in inv.get("outils", {}).items() if v)
            lines.append("  outils : " + (", ".join(tools) or "aucun de la liste"))
    return lines
