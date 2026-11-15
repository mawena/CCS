"""Avatars des auteurs de commits, comme GiGit : GitHub pour les adresses `noreply` de GitHub,
Gravatar sinon ; images gardées en cache sur disque, initiales quand il n'y en a pas.

`fetch` fait un appel réseau : l'interface l'appelle hors de son fil, et seulement si le
réglage `git.avatars` est vrai.
"""

import hashlib
import os
import re
import time
import urllib.error
import urllib.request

from . import core

_NOREPLY_ID = re.compile(r"^(\d+)\+([^@]+)@users\.noreply\.github\.com$")
_NOREPLY = re.compile(r"^([^@+]+)@users\.noreply\.github\.com$")
MISSING_TTL = 7 * 86400      # un avatar absent est redemandé après 7 jours
MAX_BYTES = 512 * 1024


def _clean(email):
    return (email or "").strip().lower()


def _md5(email):
    return hashlib.md5(_clean(email).encode("utf-8")).hexdigest()


def url_for(email, size=64):
    e = _clean(email)
    m = _NOREPLY_ID.match(e)
    if m:
        return f"https://avatars.githubusercontent.com/u/{m.group(1)}?s={size}"
    m = _NOREPLY.match(e)
    if m:
        return f"https://github.com/{m.group(1)}.png?size={size}"
    return f"https://www.gravatar.com/avatar/{_md5(e)}?s={size}&d=404"


def initials(name):
    words = [w for w in (name or "").split() if w]
    if not words:
        return "?"
    return "".join(w[0] for w in words[:2]).upper()


def cache_path(email):
    return core.paths().store / "avatars" / f"{_md5(email)}.png"


def fetch(email, urlopen=None):
    """Chemin de l'image en cache (téléchargée au besoin), ou None. Ne lève jamais."""
    if not _clean(email):
        return None
    path = cache_path(email)
    missing = path.with_suffix(".none")
    if path.exists():
        return path
    try:
        if missing.exists() and time.time() - missing.stat().st_mtime < MISSING_TTL:
            return None
    except OSError:
        pass
    opener = urlopen or urllib.request.urlopen
    req = urllib.request.Request(url_for(email), headers={"User-Agent": "CCS"})
    try:
        with opener(req, timeout=10) as resp:
            data = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            _touch(missing)
        return None
    except Exception:
        return None
    if not data or len(data) > MAX_BYTES:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        if missing.exists():
            missing.unlink()
    except OSError:
        return None
    return path


def _touch(path):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        os.utime(path, None)
    except OSError:
        pass
