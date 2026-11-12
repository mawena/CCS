"""Bilan de santé de CCS (`ccs doctor`) : service, version, bureau, intégration, comptes,
Claude Code, terminal intégré.

Chaque vérification renvoie un `Check(nom, statut, detail, commande)` ; `commande`
est la commande qui corrige le problème, à copier (jamais exécutée ici). Toutes les
sondes passent par `Probes` : les tests les remplacent sans toucher au poste.

Les jetons de connexion ne sont jamais lus au-delà de « présent / absent » et de
leurs dates d'expiration : rien d'autre ne sort de `token_info()`.
"""

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import __version__, core, daemon, settings

OK, AVERTISSEMENT, ERREUR = "ok", "avertissement", "erreur"
STATUTS = (OK, AVERTISSEMENT, ERREUR)
SERVICE = "ccs-daemon"
EXTENSION = "ubuntu-appindicators@ubuntu.com"
INSTALLED_DIR = "/usr/lib/ccs"
REFRESH_SOON_S = 3 * 86400          # connexion qui expire bientôt : avertissement
DAEMON_RESTART_GRACE_S = 600        # le service redémarre seul quand son code change
CLAUDE_INSTALL = "curl -fsSL https://claude.ai/install.sh | bash"
RESTART = f"systemctl --user restart {SERVICE}"
SECRET_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]+|[A-Za-z0-9_\-]{32,}")


@dataclass
class Check:
    nom: str
    statut: str                  # OK | AVERTISSEMENT | ERREUR
    detail: str
    commande: str | None = None  # commande qui corrige, à copier


@dataclass
class TokenInfo:
    """Ce que le bilan sait d'une connexion : jamais le jeton lui-même."""
    present: bool                        # jeton de renouvellement non vide
    refresh_expires_at: float | None     # secondes ; None : inconnu (pas d'expiration fournie)
    access_expires_at: float | None      # secondes


@dataclass
class ProcessCode:
    path: str                    # dossier qui contient ccs_app
    version: str | None
    started_at: float | None     # démarrage du processus (secondes)


# --------------------------------------------------------------------------
# Sondes réelles
# --------------------------------------------------------------------------

def _run(args, timeout=10):
    """(code de retour, sortie) ; code None si la commande est introuvable."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, LC_ALL="C"))
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return r.returncode, r.stdout


def systemctl(*args):
    return _run(["systemctl", "--user", *args])


def package_version():
    rc, out = _run(["dpkg-query", "-W", "-f=${Status} ${Version}", "ccs"])
    if rc != 0 or "installed" not in out.split(" ")[:3]:
        return None
    return out.rsplit(" ", 1)[-1].strip() or None


def read_version(path):
    """__version__ de <path>/ccs_app/__init__.py, lu sans importer le module."""
    try:
        text = (Path(path) / "ccs_app" / "__init__.py").read_text()
    except OSError:
        return None
    m = re.search(r"""^__version__\s*=\s*["']([^"']+)["']""", text, re.M)
    return m.group(1) if m else None


def package_dir(argv, cwd=None):
    """Dossier du paquet ccs_app qu'utilise un processus, d'après sa ligne de commande
    (même règle que le lanceur bin/claude-accounts)."""
    args = list(argv[1:]) if argv and os.path.basename(argv[0]).startswith("python") else list(argv)
    if args[:1] == ["-m"] or (args and args[0].startswith("-m")):
        if cwd and os.path.isdir(os.path.join(cwd, "ccs_app")):
            return cwd
        return INSTALLED_DIR
    script = next((a for a in args if not a.startswith("-")), None)
    if script:
        here = os.path.dirname(os.path.realpath(script))
        candidate = os.path.abspath(os.path.join(here, ".."))
        if os.path.isdir(os.path.join(candidate, "ccs_app")):
            return candidate
    return INSTALLED_DIR


def _cmdline(pid, proc="/proc"):
    try:
        with open(f"{proc}/{pid}/cmdline", "rb") as f:
            return [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
    except OSError:
        return None


def _start_time(pid, proc="/proc"):
    try:
        with open(f"{proc}/{pid}/stat") as f:
            ticks = int(f.read().rsplit(")", 1)[1].split()[19])
        with open(f"{proc}/stat") as f:
            btime = next(int(line.split()[1]) for line in f if line.startswith("btime "))
        return btime + ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration):
        return None


def process_code(pid, proc="/proc"):
    """Code (dossier, version) que fait tourner le processus, ou None s'il n'existe pas."""
    argv = _cmdline(pid, proc)
    if not argv:
        return None
    try:
        cwd = os.readlink(f"{proc}/{pid}/cwd")
    except OSError:
        cwd = None
    path = package_dir(argv, cwd)
    return ProcessCode(path, read_version(path), _start_time(pid, proc))


def tray_running(proc="/proc"):
    """Vrai si l'indicateur (`claude-accounts tray`) tourne pour cet utilisateur."""
    uid = os.getuid()
    try:
        entries = os.listdir(proc)
    except OSError:
        return False
    for name in entries:
        if not name.isdigit():
            continue
        try:
            if os.stat(f"{proc}/{name}").st_uid != uid:
                continue
        except OSError:
            continue
        argv = _cmdline(name, proc) or []
        if "tray" in argv[1:] and any(os.path.basename(a) == "claude-accounts" or "ccs_app" in a
                                      for a in argv):
            return True
    return False


def gnome_extensions():
    """{"installed", "enabled"} pour l'extension AppIndicator ; None sans gnome-extensions."""
    rc, out = _run(["gnome-extensions", "list"])
    if rc is None:
        return None
    installed = EXTENSION in out.split()
    rc, out = _run(["gnome-extensions", "list", "--enabled"])
    return {"installed": installed, "enabled": rc == 0 and EXTENSION in out.split()}


def watcher_available():
    from . import tray
    return tray.watcher_available()


def integration_status():
    from . import integration
    return integration.status()


def token_info(profile):
    """Présence du jeton de renouvellement et dates d'expiration, sans rien garder du jeton.
    Compte actif : fichier de connexion vivant de Claude Code (comme core.access_token)."""
    p = core.paths()
    source = p.creds if profile.active else p.store / profile.name / "oauth.json"
    oauth = core.load_json(source).get("claudeAiOauth")
    oauth = oauth if isinstance(oauth, dict) else {}

    def seconds(key):
        v = oauth.get(key)
        return float(v) / 1000 if isinstance(v, (int, float)) and v > 0 else None

    present = isinstance(oauth.get("refreshToken"), str) and len(oauth["refreshToken"]) > 0
    return TokenInfo(present, seconds("refreshTokenExpiresAt"), seconds("expiresAt"))


def find_claude():
    from . import sessions
    found = sessions._claude_bin()
    return found if os.path.isabs(found) else shutil.which(found)


def claude_version(path):
    rc, out = _run([path, "--version"], timeout=15)
    return out.strip().splitlines()[0] if rc == 0 and out.strip() else None


def vte_available():
    try:
        import gi
        gi.require_version("Vte", "3.91")
        return True
    except (ImportError, ValueError):
        return False


def gtksource_available():
    try:
        import gi
        gi.require_version("GtkSource", "5")
        return True
    except (ImportError, ValueError):
        return False


def markdown_it_available():
    try:
        import markdown_it  # noqa: F401
        return True
    except ImportError:
        return False


def local_deb(version):
    """Paquet déjà construit dans le dépôt (dist/ccs_<version>_all.deb), s'il existe."""
    deb = Path(__file__).resolve().parent.parent / "dist" / f"ccs_{version}_all.deb"
    return str(deb) if deb.is_file() else None


def archive_info():
    """État de l'archive des conversations : {"count", "bytes", "dir", "mode", "index_ok"} ;
    "dir" vaut None si le dossier n'existe pas encore. Lit l'index, jamais les conversations."""
    from . import archive
    folder = archive.archive_dir()
    if not folder.is_dir():
        return {"count": 0, "bytes": 0, "dir": None, "mode": None, "index_ok": True}
    index = archive.index_path()
    index_ok = True
    if index.exists():
        try:
            import json
            data = json.loads(index.read_text())
            index_ok = isinstance(data, dict)
        except (OSError, ValueError):
            index_ok = False
    count, size = archive.stats() if index_ok else (0, 0)
    return {"count": count, "bytes": size, "dir": str(folder),
            "mode": folder.stat().st_mode & 0o777, "index_ok": index_ok}


def phone_info():
    """Téléphone : {"enabled", "server", "channel"} (canal : valide ou non, jamais sa valeur)."""
    from . import phone
    cfg = phone.config(settings.load_settings())
    return {"enabled": cfg["enabled"], "server": cfg["server"],
            "channel": phone.subscribe_url(cfg) is not None}


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (OSError, ValueError, TypeError):
        return True  # PermissionError : il existe
    return True


def dead_tasks():
    """Identifiants des tâches « en cours » dont le processus n'existe plus."""
    from . import tasks
    return [t.id for t in tasks.all() if t.state == tasks.RUNNING and t.pid and not _pid_alive(t.pid)]


@dataclass
class Probes:
    systemctl: Callable = systemctl
    daemon_pid: Callable = daemon.running_pid
    state: Callable = lambda: core.load_json(daemon.state_path())
    now: Callable = time.time
    package_version: Callable = package_version
    process_code: Callable = process_code
    code_stamp: Callable = daemon.code_stamp
    extensions: Callable = gnome_extensions
    watcher: Callable = watcher_available
    desktop: Callable = lambda: os.environ.get("XDG_CURRENT_DESKTOP", "")
    tray_running: Callable = tray_running
    integration: Callable = integration_status
    profiles: Callable = core.list_profiles
    token_info: Callable = token_info
    claude_bin: Callable = find_claude
    claude_version: Callable = claude_version
    vte: Callable = vte_available
    gtksource: Callable = gtksource_available
    markdown_it: Callable = markdown_it_available
    which: Callable = shutil.which
    local_deb: Callable = local_deb
    settings_problems: Callable = settings.problems
    archive: Callable = archive_info
    phone: Callable = phone_info
    dead_tasks: Callable = dead_tasks
    _cache: dict = field(default_factory=dict, repr=False)

    def once(self, name, *args):
        """Résultat d'une sonde, calculé une seule fois par bilan."""
        key = (name, args)
        if key not in self._cache:
            self._cache[key] = getattr(self, name)(*args)
        return self._cache[key]


# --------------------------------------------------------------------------
# Vérifications
# --------------------------------------------------------------------------

def _ago(seconds):
    seconds = max(0, int(seconds))
    if seconds < 90:
        return "à l'instant"
    if seconds < 3600:
        return f"il y a {seconds // 60} min"
    if seconds < 2 * 86400:
        return f"il y a {seconds // 3600} h"
    return f"il y a {seconds // 86400} j"


def _date(ts):
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y à %H:%M")


def _upstream(version):
    return (version or "").split("-", 1)[0].split("+", 1)[0]


def _service_active(p):
    """(code de retour, état systemd du service) ; code None sans systemctl."""
    rc, out = p.once("systemctl", "is-active", SERVICE)
    return rc, (out or "").strip()


def check_service(p):
    nom = f"Service {SERVICE}"
    rc, state = _service_active(p)
    pid = p.once("daemon_pid")
    if state == "active":
        return Check(nom, OK, f"actif (pid {pid})" if pid else "actif")
    if pid:
        return Check(nom, AVERTISSEMENT, f"le service tourne (pid {pid}) hors de systemd : il ne redémarrera "
                                         "pas tout seul", f"systemctl --user enable --now {SERVICE}")
    if rc is None:
        return Check(nom, AVERTISSEMENT, "systemctl introuvable : état du service inconnu")
    if state == "failed":
        return Check(nom, ERREUR, f"en échec (voir « journalctl --user -u {SERVICE} »)", RESTART)
    return Check(nom, ERREUR, f"arrêté ({state or 'inconnu'}) : pas de relevés, de bascule automatique "
                              "ni d'alertes", f"systemctl --user enable --now {SERVICE}")


def check_state(p):
    nom = "Relevés"
    st = p.once("state") or {}
    updated = st.get("updated_at")
    running = _service_active(p)[1] == "active" or bool(p.once("daemon_pid"))
    if not updated:
        return Check(nom, AVERTISSEMENT, "aucun relevé enregistré pour l'instant",
                     RESTART if running else "claude-accounts collect")
    age = p.now() - updated
    if daemon.state_fresh(st, p.now()):
        return Check(nom, OK, f"dernier relevé {_ago(age)}")
    return Check(nom, AVERTISSEMENT, f"dernier relevé {_ago(age)} : les données affichées sont anciennes",
                 RESTART if running else "claude-accounts collect")


def check_package(p):
    nom = "Version installée"
    installed = p.once("package_version")
    if installed is None:
        return Check(nom, AVERTISSEMENT, f"paquet ccs non installé (ce code : {__version__}, copie de "
                                         "développement)", _deb_command(p))
    if _upstream(installed) != __version__:
        return Check(nom, AVERTISSEMENT, f"paquet ccs {installed} installé, ce code est en {__version__}",
                     _deb_command(p))
    return Check(nom, OK, f"ccs {installed}")


def _deb_command(p):
    deb = p.local_deb(__version__)
    return f"sudo apt install {deb}" if deb else None


def check_daemon_code(p):
    """Code que fait tourner le service ; None si le service ne tourne pas."""
    nom = "Code du service"
    pid = p.once("daemon_pid")
    if not pid:
        return None
    code = p.process_code(pid)
    if code is None:
        return Check(nom, AVERTISSEMENT, f"processus {pid} illisible")
    where = "paquet installé" if code.path == INSTALLED_DIR else code.path
    # Référence : le paquet installé (c'est lui que lance systemd), sinon ce code.
    expected = _upstream(p.once("package_version") or "") or __version__
    if code.version and code.version != expected:
        return Check(nom, AVERTISSEMENT, f"le service fait tourner la version {code.version} ({where}) "
                                         f"au lieu de {expected}", RESTART)
    # Fichiers plus récents que le processus : le service tourne encore avec l'ancien code.
    # Il redémarre seul à son prochain relevé ; on ne signale qu'un retard anormal.
    stamp = p.code_stamp(os.path.join(code.path, "ccs_app"))
    if code.started_at and stamp > code.started_at + 5 and p.now() - stamp > DAEMON_RESTART_GRACE_S:
        return Check(nom, AVERTISSEMENT, f"le service tourne depuis le {_date(code.started_at)} avec un code "
                                         "plus ancien que les fichiers installés", RESTART)
    return Check(nom, OK, f"version {code.version or '?'} ({where})")


def check_extension(p):
    nom = "Extension AppIndicator"
    if p.watcher():
        return Check(nom, OK, "les indicateurs s'affichent dans la barre du haut")
    ext = p.extensions()
    gnome = "gnome" in (p.desktop() or "").lower()
    if ext is None or not gnome:
        return Check(nom, AVERTISSEMENT, "aucun service d'indicateurs détecté sur ce bureau : l'indicateur "
                                         "de CCS restera invisible")
    if not ext.get("installed"):
        return Check(nom, ERREUR, "extension GNOME « Ubuntu AppIndicators » absente : l'indicateur reste "
                                  "invisible", "sudo apt install gnome-shell-extension-appindicator")
    if not ext.get("enabled"):
        return Check(nom, ERREUR, "extension GNOME « Ubuntu AppIndicators » désactivée : l'indicateur "
                                  "reste invisible", f"gnome-extensions enable {EXTENSION}")
    return Check(nom, AVERTISSEMENT, "extension activée mais pas encore chargée : ferme puis rouvre la "
                                     "session")


def check_tray(p):
    nom = "Indicateur"
    if p.tray_running():
        return Check(nom, OK, "lancé")
    return Check(nom, AVERTISSEMENT, "non lancé (il démarre normalement avec la session)",
                 "setsid -f claude-accounts tray >/dev/null 2>&1")


def check_integration(p):
    nom = "Intégration Claude Code"
    st = p.integration() or {}
    line, hook = st.get("statusline"), bool(st.get("hook"))
    if hook and line == "ccs":
        return Check(nom, OK, "ligne d'état et bascule après blocage installées")
    if hook and line == "autre":
        return Check(nom, OK, "bascule après blocage installée ; ta ligne d'état personnelle est conservée")
    missing = ([] if line else ["ligne d'état"]) + ([] if hook else ["bascule après blocage (hook)"])
    if not missing:  # ligne d'état d'un autre outil, pas de hook
        missing = ["bascule après blocage (hook)"]
    return Check(nom, AVERTISSEMENT, "non installé : " + ", ".join(missing), "ccs integrate on")


AUTH_WORDS = ("connexion expirée", "connexion perdue", "révoquée")


def check_profiles(p):
    profiles = p.profiles()
    if not profiles:
        return [Check("Comptes", AVERTISSEMENT, "aucun profil enregistré : enregistre le compte actuel avec "
                                                "« ccs save <nom> »")]
    accounts = {a.get("name"): a for a in (p.once("state") or {}).get("accounts") or [] if isinstance(a, dict)}
    now = p.now()
    out = []
    for prof in profiles:
        nom = f"Compte {prof.name}"
        fix = f"ccs rm {prof.name} && ccs add {prof.name}"
        info = p.token_info(prof)
        error = str((accounts.get(prof.name) or {}).get("error") or "")
        if not info.present:
            out.append(Check(nom, ERREUR, "connexion perdue : reconnecte ce compte", fix))
        elif info.refresh_expires_at and info.refresh_expires_at <= now:
            out.append(Check(nom, ERREUR, f"connexion expirée le {_date(info.refresh_expires_at)}", fix))
        elif any(w in error for w in AUTH_WORDS):
            out.append(Check(nom, ERREUR, "le dernier relevé a été refusé : connexion expirée ou révoquée", fix))
        elif info.refresh_expires_at and info.refresh_expires_at - now < REFRESH_SOON_S:
            out.append(Check(nom, AVERTISSEMENT, f"la connexion expire le {_date(info.refresh_expires_at)}",
                             fix))
        elif error and not error.startswith("HTTP 429"):
            short = SECRET_RE.sub("…", error)[:100]
            out.append(Check(nom, AVERTISSEMENT, f"dernier relevé en échec : {short}"))
        else:
            out.append(Check(nom, OK, "connecté" + (" (compte actif)" if prof.active else "")))
    return out


def check_claude(p):
    nom = "Commande claude"
    path = p.claude_bin()
    if not path:
        return Check(nom, ERREUR, "Claude Code introuvable (ni dans le PATH ni dans ~/.local/bin)",
                     CLAUDE_INSTALL)
    version = p.claude_version(path)
    return Check(nom, OK, f"{path}" + (f" — {version}" if version else ""))


def check_tools(p):
    nom = "Outils de ccs"
    if not p.which("jq"):
        return Check(nom, ERREUR, "jq introuvable : la commande ccs ne peut pas lire les profils",
                     "sudo apt install jq")
    return Check(nom, OK, "jq présent")


def check_settings(p):
    """Réglages édités à la main : clés invalides, remplacées par leurs valeurs par défaut.
    Rien à signaler (None) quand le fichier est correct ou absent."""
    nom = "Réglages"
    bad = p.once("settings_problems")
    if not bad:
        return None
    if bad == [settings.UNREADABLE]:
        return Check(nom, AVERTISSEMENT, "settings.json illisible : les valeurs par défaut sont utilisées "
                                         "(corrige le fichier ou supprime-le)")
    return Check(nom, AVERTISSEMENT, "valeurs invalides ignorées (valeurs par défaut utilisées) : "
                                     + ", ".join(bad))


def check_vte(p):
    nom = "Terminal intégré"
    if p.vte():
        return Check(nom, OK, "disponible (VTE pour GTK 4)")
    return Check(nom, AVERTISSEMENT, "VTE pour GTK 4 absent : les sessions s'ouvriront dans un terminal "
                                     "séparé", "sudo apt install gir1.2-vte-3.91")


def check_chat_deps(p):
    """Bibliothèques du chat (coloration du code, rendu Markdown)."""
    nom = "Chat graphique"
    missing = [(name, pkg) for name, pkg, ok in (
        ("GtkSource 5", "gir1.2-gtksource-5", p.once("gtksource")),
        ("markdown_it", "python3-markdown-it", p.once("markdown_it"))) if not ok]
    if not missing:
        return Check(nom, OK, "GtkSource 5 et markdown_it présents")
    return Check(nom, AVERTISSEMENT,
                 "manquant : " + ", ".join(f"{n} (paquet {pkg})" for n, pkg in missing),
                 "sudo apt install " + " ".join(pkg for _n, pkg in missing))


def _mo(n):
    return f"{n / 1024 ** 2:.1f}".replace(".", ",") + " Mo"


def check_archive(p):
    """Archive des conversations : nombre, taille, dossier en 700, index lisible."""
    nom = "Archive des conversations"
    info = p.once("archive")
    if not info:
        return None
    if not info.get("index_ok", True):
        return Check(nom, AVERTISSEMENT, "index illisible : il sera reconstruit au prochain passage du "
                                         "service (ou supprime index.json dans le dossier d'archive)",
                     f"rm -f '{info.get('dir')}/index.json'" if info.get("dir") else None)
    if info.get("dir") is None:
        return Check(nom, OK, "aucune copie pour l'instant (le service en fait au plus toutes les 30 min)")
    detail = f"{info['count']} conversation{'s' if info['count'] > 1 else ''}, {_mo(info['bytes'])}"
    if info.get("mode") is not None and info["mode"] != 0o700:
        return Check(nom, AVERTISSEMENT, f"{detail} ; dossier en {info['mode']:03o} au lieu de 700",
                     f"chmod 700 '{info['dir']}'")
    return Check(nom, OK, detail + " (dossier en 700)")


def check_gpg(p):
    nom = "Chiffrement (gpg)"
    if p.which("gpg"):
        return Check(nom, OK, "gpg présent : ccs sauvegarde est disponible")
    return Check(nom, AVERTISSEMENT, "gpg introuvable : ccs sauvegarde et ccs restaurer ne marcheront pas",
                 "sudo apt install gnupg")


def check_phone(p):
    nom = "Téléphone (ntfy)"
    info = p.once("phone")
    if not info:
        return None
    if not info.get("enabled"):
        return Check(nom, OK, "désactivé")
    if not info.get("channel"):
        return Check(nom, AVERTISSEMENT, "activé mais sans canal valide : crée-le dans Réglages > Téléphone")
    from urllib.parse import urlparse
    host = urlparse(info.get("server") or "").netloc or "serveur inconnu"
    return Check(nom, OK, f"configuré (serveur {host}, canal secret non affiché)")


def check_tasks(p):
    nom = "File de tâches"
    dead = p.once("dead_tasks")
    if not dead:
        return None
    ids = ", ".join(dead)
    return Check(nom, AVERTISSEMENT, f"tâche en cours dont le processus n'existe plus : {ids}",
                 f"ccs tache annuler {dead[0]}")


CHECKS = (check_service, check_state, check_package, check_daemon_code, check_extension, check_tray,
          check_integration, check_profiles, check_settings, check_claude, check_tools, check_gpg,
          check_archive, check_phone, check_tasks, check_vte, check_chat_deps)
CHECK_NAMES = {check_service: f"Service {SERVICE}", check_state: "Relevés", check_package: "Version installée",
               check_daemon_code: "Code du service", check_extension: "Extension AppIndicator",
               check_tray: "Indicateur", check_integration: "Intégration Claude Code", check_profiles: "Comptes",
               check_settings: "Réglages",
               check_claude: "Commande claude", check_tools: "Outils de ccs", check_vte: "Terminal intégré",
               check_gpg: "Chiffrement (gpg)", check_archive: "Archive des conversations",
               check_phone: "Téléphone (ntfy)", check_tasks: "File de tâches",
               check_chat_deps: "Chat graphique"}


def run_checks(probes=None):
    """Toutes les vérifications, dans l'ordre d'affichage. Une sonde qui plante donne un
    avertissement « vérification impossible » sans arrêter les autres."""
    p = probes or Probes()
    p._cache.clear()
    out = []
    for check in CHECKS:
        try:
            result = check(p)
        except Exception as e:  # noqa: BLE001 — une sonde ne doit jamais arrêter le bilan
            result = Check(CHECK_NAMES[check], AVERTISSEMENT, f"vérification impossible : {e}")
        if result is None:
            continue
        out.extend(result if isinstance(result, list) else [result])
    return out


# --------------------------------------------------------------------------
# Texte (CLI)
# --------------------------------------------------------------------------

GLYPHS = {OK: "✔", AVERTISSEMENT: "⚠", ERREUR: "✖"}
COLORS = {OK: "\033[32m", AVERTISSEMENT: "\033[33m", ERREUR: "\033[31m"}


def exit_code(checks):
    """0 si tout va bien, 1 sinon."""
    return 0 if all(c.statut == OK for c in checks) else 1


def summary(checks):
    errors = sum(c.statut == ERREUR for c in checks)
    warnings = sum(c.statut == AVERTISSEMENT for c in checks)
    if not errors and not warnings:
        return "Tout va bien."
    parts = []
    if errors:
        parts.append(f"{errors} erreur{'s' if errors > 1 else ''}")
    if warnings:
        parts.append(f"{warnings} avertissement{'s' if warnings > 1 else ''}")
    return ", ".join(parts) + "."


def format_text(checks, couleur=False):
    bold, dim, off = ("\033[1m", "\033[2m", "\033[0m") if couleur else ("", "", "")
    width = max((len(c.nom) for c in checks), default=0)
    lines = [f"{bold}Bilan de santé de CCS{off}", ""]
    for c in checks:
        col = COLORS.get(c.statut, "") if couleur else ""
        lines.append(f"  {col}{GLYPHS.get(c.statut, '?')}{off} {c.nom.ljust(width)}  {c.detail}")
        if c.commande:
            lines.append(f"    {' ' * width}{dim}→ {c.commande}{off}")
    lines += ["", f"{bold}{summary(checks)}{off}"]
    return "\n".join(lines) + "\n"


def main(couleur=None, probes=None):
    """`ccs doctor` / `claude-accounts doctor` : affiche le bilan, renvoie le code de sortie."""
    if couleur is None:
        couleur = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    checks = run_checks(probes)
    sys.stdout.write(format_text(checks, couleur))
    return exit_code(checks)
