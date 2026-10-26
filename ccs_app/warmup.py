"""Démarrage anticipé de la fenêtre de 5 h : une requête minimale à heure fixe.

La requête passe par `claude -p` avec un CLAUDE_CONFIG_DIR temporaire qui ne
contient que le compte visé : le compte actif et ~/.claude ne sont pas touchés.
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
from datetime import timedelta
from pathlib import Path

from . import core
from .forecast import window_open

SLOT_TOLERANCE = timedelta(minutes=10)
TIMEOUT_S = 120
# Jeton valide au moins ce temps : claude n'aura pas à le renouveler.
MIN_VALIDITY_MS = 30 * 60 * 1000


def _slot_dt(local_now, hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    return local_now.replace(hour=h, minute=m, second=0, microsecond=0)


def due(settings, accounts, now, store):
    """[(profil, "HH:MM")] dont le créneau vient d'arriver et la fenêtre est au repos."""
    local = now.astimezone()
    today = local.date().isoformat()
    by_name = {a.name: a for a in accounts}
    out = []
    for name, slots in (settings.get("warmup") or {}).items():
        acc = by_name.get(name)
        if acc is None or not acc.limits or window_open(acc, now):
            continue
        done = {(e.detail.get("date"), e.detail.get("time"))
                for e in store.events(now.timestamp() - 86400, type="warmup", profile=name)}
        for slot in slots:
            try:
                start = _slot_dt(local, slot["time"])
            except (KeyError, ValueError):
                continue
            if local.weekday() not in slot.get("days", range(7)):
                continue
            if timedelta(0) <= local - start <= SLOT_TOLERANCE and (today, slot["time"]) not in done:
                out.append((name, slot["time"]))
                break
    return out


def _claude_bin():
    extra = f"{core.paths().home}/.local/bin"
    return shutil.which("claude", path=f"{extra}:{os.environ.get('PATH', '')}") or "claude"


def _profile_oauth(name):
    """claudeAiOauth à jour pour le profil (fichier vivant si actif)."""
    p = core.paths()
    core.access_token(name)  # renouvelle si besoin, sous verrou
    if core.active_profile_name() == name:
        return core.load_json(p.creds).get("claudeAiOauth") or {}
    return core.load_json(p.store / name / "oauth.json").get("claudeAiOauth") or {}


def _save_rotated(name, oauth):
    p = core.paths()
    with core.store_lock():
        if core.active_profile_name() == name:
            creds = core.load_json(p.creds)
            creds["claudeAiOauth"] = oauth
            core.atomic_write_json(p.creds, creds)
        pfile = p.store / name / "oauth.json"
        prof = core.load_json(pfile)
        prof["claudeAiOauth"] = oauth
        core.atomic_write_json(pfile, prof)


def run(name, slot_time, store, now):
    local = now.astimezone()
    detail = {"date": local.date().isoformat(), "time": slot_time}
    tmp = Path(tempfile.mkdtemp(prefix="ccs-warmup-"))
    oauth = {}
    try:
        os.chmod(tmp, 0o700)
        oauth = _profile_oauth(name)
        if oauth.get("expiresAt", 0) - now.timestamp() * 1000 < MIN_VALIDITY_MS:
            core.access_token(name, force_refresh=True)
            oauth = _profile_oauth(name)
        account = core.load_json(core.paths().store / name / "account.json")
        core.atomic_write_json(tmp / ".credentials.json", {"claudeAiOauth": oauth})
        core.atomic_write_json(tmp / ".claude.json",
                               {"oauthAccount": account, "hasCompletedOnboarding": True})
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(tmp))
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        env.pop("ANTHROPIC_API_KEY", None)
        r = subprocess.run([_claude_bin(), "-p", "ok", "--model", "haiku"], env=env,
                           capture_output=True, text=True, timeout=TIMEOUT_S, cwd=tmp)
        ok = r.returncode == 0
        detail.update(ok=ok, message=(r.stderr or "").strip()[:200] if not ok else "")
    except (OSError, subprocess.SubprocessError, core.UsageError) as e:
        detail.update(ok=False, message=str(e)[:200])
    finally:
        # Même interrompu, claude a pu faire tourner le jeton : on le récupère.
        after = core.load_json(tmp / ".credentials.json").get("claudeAiOauth") or {}
        if after.get("refreshToken") and after["refreshToken"] != oauth.get("refreshToken"):
            _save_rotated(name, after)
        shutil.rmtree(tmp, ignore_errors=True)
    store.add_event(now.timestamp(), "warmup", name, detail)
    return detail["ok"]


def hook(daemon, states, settings, now):
    for name, slot in due(settings, states, now, daemon.store):
        # Marqué tout de suite pour ne pas relancer au tick suivant.
        daemon.store.add_event(now.timestamp(), "warmup", name,
                               {"date": now.astimezone().date().isoformat(), "time": slot,
                                "ok": None, "message": "en cours"})
        threading.Thread(target=run, args=(name, slot, daemon.store, now), daemon=True).start()
