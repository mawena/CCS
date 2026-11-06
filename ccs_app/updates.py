"""Nouvelle version de CCS : dernière release GitHub, au plus une vérification par jour.

Le cache ~/.claude-accounts/updates.json garde l'heure de la dernière
vérification, la dernière version publiée et la dernière version annoncée
(une seule notification par version). Aucune authentification ; une erreur
réseau ou un refus de GitHub (403, 429) n'est jamais fatal.
"""

import http.client
import json
import threading
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass

from . import __version__, core
from .alerts import Alert

RELEASES_URL = "https://api.github.com/repos/mawena/CCS/releases/latest"
PROJECT_URL = "https://github.com/mawena/CCS/"
USER_AGENT = "ccs"
TIMEOUT_S = 5
MAX_BYTES = 1 << 20
CHECK_INTERVAL_S = 86400
# Hors ligne (GitHub jamais atteint) : nouvel essai une heure plus tard.
OFFLINE_RETRY_S = 3600


# --------------------------------------------------------------------------
# Versions (SemVer)
# --------------------------------------------------------------------------

def parse_version(text):
    """« v0.5.0 », « 1.2.3-rc.1+build » → ((1, 2, 3), ("rc", 1)) ; None si illisible."""
    if not isinstance(text, str):
        return None
    t = text.strip()
    if t[:1] in ("v", "V"):
        t = t[1:]
    t = t.split("+", 1)[0]
    main, dash, pre = t.partition("-")
    parts = main.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    if dash and (not pre or any(not x for x in pre.split("."))):
        return None
    ids = tuple(int(x) if x.isdigit() else x for x in pre.split(".")) if pre else ()
    return tuple(int(p) for p in parts), ids


def _cmp(a, b):
    return (a > b) - (a < b)


def compare(a, b):
    """-1, 0 ou 1 selon la précédence SemVer (une préversion précède sa version)."""
    pa, pb = parse_version(a), parse_version(b)
    if pa is None or pb is None:
        raise ValueError(f"version illisible : {a if pa is None else b}")
    if pa[0] != pb[0]:
        return _cmp(pa[0], pb[0])
    xa, xb = pa[1], pb[1]
    if not xa or not xb:
        return _cmp(not xa, not xb)
    for x, y in zip(xa, xb):
        if x == y:
            continue
        if isinstance(x, int) and isinstance(y, int):
            return _cmp(x, y)
        if isinstance(x, int) or isinstance(y, int):
            return -1 if isinstance(x, int) else 1  # numérique avant alphanumérique
        return _cmp(x, y)
    return _cmp(len(xa), len(xb))


def is_newer(latest, current):
    try:
        return compare(latest, current) > 0
    except ValueError:
        return False


# --------------------------------------------------------------------------
# GitHub
# --------------------------------------------------------------------------

@dataclass
class Release:
    version: str  # sans « v »
    url: str      # page de la release, toujours sur github.com/mawena/CCS
    name: str


class FetchError(Exception):
    def __init__(self, message, offline=False):
        super().__init__(message)
        self.offline = offline


def _safe_url(url, version):
    """Jamais d'autre lien que la page du projet (la réponse vient du réseau)."""
    if isinstance(url, str) and url.startswith(PROJECT_URL) and url.isprintable() and " " not in url:
        return url
    return f"{PROJECT_URL}releases/tag/v{version}"


def parse_release(data):
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name")
    if parse_version(tag) is None:
        return None
    version = tag.strip().lstrip("vV")
    name = data.get("name") if isinstance(data.get("name"), str) else ""
    return Release(version, _safe_url(data.get("html_url"), version),
                   (name.strip() or f"v{version}")[:80])


def fetch_latest(opener=None, timeout=TIMEOUT_S):
    """Dernière release publiée ; FetchError (jamais d'autre exception) en cas d'échec."""
    opener = opener or urllib.request.urlopen
    req = urllib.request.Request(RELEASES_URL, headers={
        "User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with opener(req, timeout=timeout) as r:
            data = json.loads(r.read(MAX_BYTES))
    except urllib.error.HTTPError as e:  # 403 / 429 (limite), 404… : GitHub a répondu
        raise FetchError(f"HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise FetchError(f"réseau : {e.reason}", offline=True) from e
    except (OSError, http.client.HTTPException) as e:  # délai dépassé, connexion coupée…
        raise FetchError(f"réseau : {e}", offline=True) from e
    except ValueError as e:
        raise FetchError("réponse illisible") from e
    release = parse_release(data)
    if release is None:
        raise FetchError("aucune version publiée lisible")
    return release


# --------------------------------------------------------------------------
# Cache et annonce
# --------------------------------------------------------------------------

def cache_path():
    return core.paths().store / "updates.json"


def _load():
    return core.load_json(cache_path())


def _save(cache):
    core.atomic_write_json(cache_path(), cache)


def check_due(now_ts, cache=None):
    c = _load() if cache is None else cache
    last = c.get("checked_at")
    if not isinstance(last, (int, float)) or last > now_ts:
        return True  # jamais vérifié, ou horloge revenue en arrière
    return now_ts - last >= (OFFLINE_RETRY_S if c.get("offline") else CHECK_INTERVAL_S)


def refresh(now_ts, fetch=None):
    """Interroge GitHub si la dernière vérification date d'un jour ; renvoie le cache."""
    fetch = fetch or fetch_latest
    c = _load()
    if not check_due(now_ts, c):
        return c
    try:
        c.update(latest=asdict(fetch()), error=None, offline=False)
    except FetchError as e:
        c.update(error=str(e), offline=e.offline)  # dernière version connue conservée
    c["checked_at"] = now_ts
    _save(c)
    return c


def available(current=None, cache=None):
    """Release plus récente que la version installée, d'après le cache (aucun réseau)."""
    current = current or __version__
    latest = (_load() if cache is None else cache).get("latest")
    if not isinstance(latest, dict) or not is_newer(latest.get("version"), current):
        return None
    v = latest["version"]
    return Release(v, _safe_url(latest.get("url"), v), str(latest.get("name") or f"v{v}"))


def notification(release, current):
    return Alert(f"update:{release.version}", f"CCS {release.version} est disponible",
                 f"Version installée : {current}. Nouveautés et paquet : {release.url}", 0)


_running = threading.Lock()


def run(now_ts, notifier, settings, current=None, fetch=None):
    """Vérifie (au plus une fois par jour) puis annonce une seule fois chaque version ;
    renvoie l'alerte envoyée ou None."""
    if not settings["updates"]["enabled"]:
        return None
    current = current or __version__
    if not _running.acquire(blocking=False):
        return None  # vérification déjà en cours
    try:
        c = refresh(now_ts, fetch)
        release = available(current, c)
        if release is None or c.get("notified") == release.version \
                or not settings["alerts"]["enabled"]:
            return None
        alert = notification(release, current)
        notifier(alert)
        c["notified"] = release.version
        _save(c)
        return alert
    finally:
        _running.release()


def hook(daemon, states, settings, now):
    """Module du service : la partie réseau tourne dans un fil, le relevé n'attend jamais."""
    if not settings["updates"]["enabled"]:
        return None
    ts = now.timestamp()
    if not check_due(ts):
        run(ts, daemon.notifier, settings)  # cache seul : pas de réseau
        return None
    t = threading.Thread(target=run, args=(ts, daemon.notifier, settings), daemon=True,
                         name="ccs-updates")
    t.start()
    return t
