"""Jetons de `ccs-auth` : sessions du navigateur, appareils retenus (dispense du code 30 jours)
et jetons d'application (bureau, `ccs tui`). Seule l'empreinte SHA-256 d'un jeton est gardée :
lire le fichier ne permet pas de se connecter."""

import hashlib
import json
import os
import secrets
import time

IDLE = 12 * 3600
MAX_AGE = 7 * 86400
DEVICE_AGE = 30 * 86400
KINDS = ("session", "device", "app")


def session_hash(token):
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


class TokenStore:
    def __init__(self, path, clock=time.time):
        self.path = path
        self.clock = clock
        self._data = {}
        self._mtime = None

    # ---- fichier ---------------------------------------------------------------------

    def _load(self):
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            self._data, self._mtime = {}, None
            return
        if self._mtime == (st.st_mtime_ns, st.st_size):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self._data = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self._data = {}
        self._mtime = (st.st_mtime_ns, st.st_size)

    def _save(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False)
        os.replace(tmp, self.path)
        st = os.stat(self.path)
        self._mtime = (st.st_mtime_ns, st.st_size)

    def _expired(self, entry, now):
        kind = entry.get("kind")
        created = entry.get("created", 0)
        if kind == "session":
            return now - entry.get("last_used", created) > IDLE or now - created > MAX_AGE
        if kind == "device":
            return now - created > DEVICE_AGE
        return False

    def _purge(self, now):
        dead = [h for h, e in self._data.items() if not isinstance(e, dict) or self._expired(e, now)]
        for h in dead:
            del self._data[h]
        return bool(dead)

    # ---- création --------------------------------------------------------------------

    def _new(self, kind, user, name=""):
        self._load()
        now = self.clock()
        self._purge(now)
        token = secrets.token_urlsafe(32)
        self._data[session_hash(token)] = {"kind": kind, "user": user, "name": name,
                                           "created": now, "last_used": now}
        self._save()
        return token

    def new_session(self, user):
        return self._new("session", user)

    def new_device(self, user):
        return self._new("device", user)

    def new_app(self, user, name):
        return self._new("app", user, name)

    # ---- vérification ----------------------------------------------------------------

    def _check(self, token, kind, touch):
        if not isinstance(token, str) or not token:
            return None
        self._load()
        now = self.clock()
        h = session_hash(token)
        entry = self._data.get(h)
        if not isinstance(entry, dict) or entry.get("kind") != kind:
            return None
        if self._expired(entry, now):
            del self._data[h]
            self._save()
            return None
        if touch:
            entry["last_used"] = now
            self._save()
        return entry.get("user")

    def check_session(self, token):
        return self._check(token, "session", touch=True)

    def check_device(self, token, user):
        return self._check(token, "device", touch=False) == user

    def check_app(self, token):
        return self._check(token, "app", touch=True)

    def end_session(self, token):
        self._load()
        if self._data.pop(session_hash(token), None) is not None:
            self._save()

    # ---- liste et révocation ---------------------------------------------------------

    def list_tokens(self, user):
        self._load()
        now = self.clock()
        if self._purge(now):
            self._save()
        return [{"id": h[:12], "kind": e.get("kind"), "name": e.get("name", ""),
                 "created": e.get("created"), "last_used": e.get("last_used")}
                for h, e in self._data.items() if e.get("user") == user]

    def revoke(self, user, token_id):
        self._load()
        for h, e in list(self._data.items()):
            if h[:12] == token_id and e.get("user") == user:
                del self._data[h]
                self._save()
                return True
        return False
