"""Profils, jetons OAuth et API d'usage (même format de stockage que `ccs`).

Chaque profil vit dans ~/.claude-accounts/<nom>/ : oauth.json (claudeAiOauth +
organizationUuid), account.json (oauthAccount), usage.json (dernier usage).
"""

import fcntl
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
DEFAULT_SCOPES = ["user:profile", "user:inference", "user:sessions:claude_code"]
USER_AGENT = "ccs/0.1"

# Marge avant expiration à partir de laquelle on renouvelle le jeton.
EXPIRY_MARGIN_MS = 2 * 60 * 1000

LIMIT_LABELS = {
    "session": "Session (5 h)",
    "weekly_all": "Semaine · tous modèles",
    "weekly_opus": "Semaine · Opus",
    "weekly_sonnet": "Semaine · Sonnet",
}
# Ancien format de réponse : clé -> kind du nouveau format.
LEGACY_KINDS = [
    ("five_hour", "session"),
    ("seven_day", "weekly_all"),
    ("seven_day_opus", "weekly_opus"),
    ("seven_day_sonnet", "weekly_sonnet"),
]

DAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
          "juil.", "août", "sept.", "oct.", "nov.", "déc."]


class UsageError(Exception):
    pass


# --------------------------------------------------------------------------
# Chemins (relus à chaque appel : HOME, CLAUDE_CONFIG_DIR, CCS_HOME)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Paths:
    home: Path
    config_dir: Path
    creds: Path
    global_json: Path
    store: Path


def paths():
    home = Path(os.environ.get("HOME") or Path.home())
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        config_dir = Path(os.environ["CLAUDE_CONFIG_DIR"])
        global_json = config_dir / ".claude.json"
    else:
        config_dir = home / ".claude"
        global_json = home / ".claude.json"
    store = Path(os.environ.get("CCS_HOME") or home / ".claude-accounts")
    return Paths(home, config_dir, config_dir / ".credentials.json", global_json, store)


# --------------------------------------------------------------------------
# Fichiers
# --------------------------------------------------------------------------

def load_json(path):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


@contextmanager
def store_lock():
    """Empêche deux renouvellements simultanés du même jeton (rotation)."""
    store = paths().store
    store.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(store / ".lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


# --------------------------------------------------------------------------
# Profils
# --------------------------------------------------------------------------

@dataclass
class Profile:
    name: str
    email: str
    org: str
    plan: str
    active: bool


def account_key(acc):
    return f"{acc.get('accountUuid')}|{acc.get('organizationUuid')}" if acc else None


def live_account():
    return load_json(paths().global_json).get("oauthAccount") or None


def live_logged_in():
    oauth = load_json(paths().creds).get("claudeAiOauth") or {}
    return bool(oauth.get("refreshToken"))


def list_profiles():
    store = paths().store
    if not store.is_dir():
        return []
    live = account_key(live_account())
    out = []
    for d in sorted(p for p in store.iterdir() if p.is_dir()):
        acc = load_json(d / "account.json")
        if not acc.get("accountUuid"):
            continue
        oauth = load_json(d / "oauth.json").get("claudeAiOauth") or {}
        out.append(Profile(
            name=d.name,
            email=acc.get("emailAddress", "?"),
            org=acc.get("organizationName", ""),
            plan=oauth.get("subscriptionType") or "?",
            active=live is not None and account_key(acc) == live,
        ))
    out.sort(key=lambda p: not p.active)
    return out


def active_profile_name():
    for p in list_profiles():
        if p.active:
            return p.name
    return None


def claude_running():
    r = subprocess.run(["pgrep", "-u", str(os.getuid()), "-x", "claude"],
                       capture_output=True)
    return r.returncode == 0


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

def http_json(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        **({"Content-Type": "application/json"} if body is not None else {}),
        **(headers or {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise UsageError(f"HTTP {e.code} : {detail}") from e
    except urllib.error.URLError as e:
        raise UsageError(f"réseau : {e.reason}") from e
    except (OSError, ValueError) as e:
        raise UsageError(f"réseau : {e}") from e


def refresh_tokens(oauth):
    try:
        data = http_json("POST", TOKEN_URL, {
            "grant_type": "refresh_token",
            "refresh_token": oauth["refreshToken"],
            "client_id": CLIENT_ID,
            "scope": " ".join(oauth.get("scopes") or DEFAULT_SCOPES),
        })
    except UsageError as e:
        if "invalid_grant" in str(e):
            raise UsageError("connexion expirée ou révoquée : supprime ce profil puis rajoute le compte") from e
        raise
    now = time.time() * 1000
    new = dict(oauth)
    new["accessToken"] = data["access_token"]
    new["refreshToken"] = data.get("refresh_token") or oauth["refreshToken"]
    new["expiresAt"] = int(now + data["expires_in"] * 1000)
    if data.get("refresh_token_expires_in"):
        new["refreshTokenExpiresAt"] = int(now + data["refresh_token_expires_in"] * 1000)
    if data.get("scope"):
        new["scopes"] = data["scope"].split()
    return new


def access_token(name, force_refresh=False):
    """Jeton d'accès valide pour le profil, renouvelé si besoin.

    Le compte actif est lu dans le fichier de connexion vivant (sa copie dans
    le profil peut être périmée). On ne renouvelle jamais son jeton pendant
    qu'une session Claude Code tourne : elle le fait elle-même.
    """
    p = paths()
    with store_lock():
        active = active_profile_name() == name
        pfile = p.store / name / "oauth.json"
        oauth = (load_json(p.creds) if active else load_json(pfile)).get("claudeAiOauth") or {}
        if not oauth.get("refreshToken"):
            raise UsageError("aucun jeton enregistré pour ce profil")
        fresh = oauth.get("expiresAt", 0) - time.time() * 1000 > EXPIRY_MARGIN_MS
        if fresh and not force_refresh:
            return oauth["accessToken"]
        if active and claude_running():
            raise UsageError("jeton expiré ; Claude Code le renouvellera à sa prochaine requête")
        new = refresh_tokens(oauth)
        if active:
            creds = load_json(p.creds)
            creds["claudeAiOauth"] = new
            atomic_write_json(p.creds, creds)
        prof = load_json(pfile)
        prof["claudeAiOauth"] = new
        atomic_write_json(pfile, prof)
        return new["accessToken"]


@dataclass
class UsageResult:
    usage: dict | None
    fetched_at: float | None
    error: str | None


def _get_usage(token):
    return http_json("GET", USAGE_URL, headers={
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
    })


def fetch_usage(name):
    """Usage du profil ; en cas d'erreur, dernier usage connu + message."""
    cache = paths().store / name / "usage.json"
    try:
        try:
            data = _get_usage(access_token(name))
        except UsageError as e:
            if not str(e).startswith("HTTP 401") or active_profile_name() == name:
                raise
            data = _get_usage(access_token(name, force_refresh=True))
        now = time.time()
        atomic_write_json(cache, {"fetchedAt": now, "data": data})
        return UsageResult(data, now, None)
    except UsageError as e:
        c = load_json(cache)
        return UsageResult(c.get("data"), c.get("fetchedAt"), str(e))


# --------------------------------------------------------------------------
# Limites
# --------------------------------------------------------------------------

@dataclass
class Limit:
    kind: str
    label: str
    percent: float
    resets_at: datetime | None


def label_for(kind, scope=None):
    label = LIMIT_LABELS.get(kind) or kind.replace("_", " ").capitalize()
    return f"{label} · {scope}" if scope else label


def parse_dt(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_limits(usage):
    if not usage:
        return []
    out = []
    for lim in usage.get("limits") or []:
        kind = lim.get("kind") or "inconnu"
        out.append(Limit(kind, label_for(kind, lim.get("scope")),
                         float(lim.get("percent") or 0), parse_dt(lim.get("resets_at"))))
    if not out:
        for key, kind in LEGACY_KINDS:
            w = usage.get(key)
            if w and w.get("utilization") is not None:
                out.append(Limit(kind, label_for(kind), float(w["utilization"]),
                                 parse_dt(w.get("resets_at"))))
    return out


# --------------------------------------------------------------------------
# Formats
# --------------------------------------------------------------------------

def fmt_reset(dt, now=None):
    if not dt:
        return ""
    now = now or datetime.now(timezone.utc)
    secs = (dt - now).total_seconds()
    if secs <= 0:
        return "réinitialisé"
    if secs < 24 * 3600:
        h, m = int(secs // 3600), int(secs % 3600 // 60)
        return f"réinitialisation dans {h} h {m:02d}" if h else f"réinitialisation dans {m} min"
    local = dt.astimezone()
    return (f"réinitialisation {DAYS[local.weekday()]} {local.day} "
            f"{MONTHS[local.month - 1]} à {local:%H:%M}")


def fr(value, digits=1):
    """Nombre à la française (virgule décimale)."""
    return f"{value:.{digits}f}".replace(".", ",")


def fmt_time(ts):
    if not ts:
        return ""
    return datetime.fromtimestamp(ts).strftime("%H:%M")


# --------------------------------------------------------------------------
# ccs
# --------------------------------------------------------------------------

def ccs_bin():
    if os.environ.get("CCS_BIN"):
        return os.environ["CCS_BIN"]
    sibling = Path(__file__).resolve().parent.parent / "bin" / "ccs"
    if sibling.exists():
        return str(sibling)
    return shutil.which("ccs") or "/usr/bin/ccs"


def run_ccs(args):
    p = paths()
    env = dict(os.environ, NO_COLOR="1",
               PATH=f"{p.home}/.local/bin:{os.environ.get('PATH', '/usr/bin:/bin')}")
    return subprocess.run([ccs_bin(), *args], capture_output=True, text=True, env=env)
