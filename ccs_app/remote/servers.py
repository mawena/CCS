"""Serveurs CCS connus de cette machine (bureau GTK, `ccs tui`) : adresse, utilisateur et jeton
d'application obtenu par appairage (mot de passe Ubuntu + code, une seule fois). Le mot de passe
n'est jamais gardé. Fichier `~/.claude-accounts/serveurs.json`, en 0600."""

import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from .. import core

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


@dataclass
class Server:
    name: str
    url: str
    user: str
    token: str


def path():
    return core.paths().store / "serveurs.json"


def normalize_url(url):
    """https:// obligatoire, sauf pour un essai sur cette machine."""
    url = (url or "").strip().rstrip("/")
    if "://" not in url:
        url = "https://" + url
    p = urlparse(url)
    if p.scheme == "http" and p.hostname not in LOCAL_HOSTS:
        raise ValueError("Adresse en http : seul https est accepté (le mot de passe circulerait en clair).")
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError(f"Adresse invalide : {url}")
    return url


def _name_for(url):
    return urlparse(url).netloc


def load():
    try:
        with open(path(), encoding="utf-8") as f:
            data = json.load(f)
        return [Server(**{k: str(d[k]) for k in ("name", "url", "user", "token")})
                for d in data if isinstance(d, dict)]
    except (OSError, ValueError, TypeError, KeyError):
        return []


def save(items):
    p = path()
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump([asdict(s) for s in items], f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def add(server):
    save([s for s in load() if s.name != server.name] + [server])


def remove(name):
    items = load()
    keep = [s for s in items if s.name != name]
    if len(keep) == len(items):
        return False
    save(keep)
    return True


def get(name_or_url):
    for s in load():
        if name_or_url in (s.name, s.url):
            return s
    return None


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "CCS"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"status": "error", "message": f"Erreur du serveur ({e.code})."}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"status": "error", "message": f"Serveur injoignable : {e}"}


def _saved(url, user, result):
    if result.get("status") == "ok" and result.get("token"):
        server = Server(_name_for(url), url, result.get("user") or user, result["token"])
        add(server)
        return server
    return result


def pair(url, user, password, code, name, post=None):
    """Appairage : Server enregistré, ou le dict du serveur (`code`, `enroll`, `refused`…)."""
    post = post or _post
    url = normalize_url(url)
    return _saved(url, user, post(url + "/api/pair", {"user": user, "password": password, "code": code,
                                                      "name": name}))


def finish_enroll(url, user, pending, code, name, post=None):
    post = post or _post
    url = normalize_url(url)
    return _saved(url, user, post(url + "/api/enroll", {"pending": pending, "code": code}))
