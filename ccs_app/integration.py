"""Intégration dans Claude Code : ligne d'état et bascule après blocage (hook).

`ccs integrate on|off` modifie ~/.claude/settings.json sur demande explicite :
écriture atomique, sauvegarde unique `settings.json.ccs-backup`, une
`statusLine` existante n'est jamais remplacée, seules nos entrées sont
ajoutées ou retirées.
"""

import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone

from . import autoswitch, core, daemon, notify
from .alerts import Alert
from .settings import load_settings
from .store import Store

MARK = "claude-accounts"


class IntegrationError(Exception):
    pass


def settings_path():
    return core.paths().config_dir / "settings.json"


def default_bin():
    return shutil.which("claude-accounts") or "/usr/bin/claude-accounts"


def _load(path):
    if not path.exists() or not path.read_text().strip():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError as e:
        raise IntegrationError(f"{path} n'est pas un JSON valide : rien n'a été modifié ({e})") from e
    if not isinstance(data, dict):
        raise IntegrationError(f"{path} : contenu inattendu, rien n'a été modifié")
    return data


def _write(path, data):
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    core.atomic_write_json(path, data)
    os.chmod(path, mode)


def _ours(entry):
    return MARK in str((entry or {}).get("command", ""))


def install(bin_path=None):
    bin_path = bin_path or default_bin()
    path = settings_path()
    data = _load(path)
    backup = path.with_name(path.name + ".ccs-backup")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)
    msgs = []
    current = data.get("statusLine")
    if current is None:
        data["statusLine"] = {"type": "command", "command": f"{bin_path} statusline", "padding": 0}
        msgs.append("Ligne d'état installée.")
    elif _ours(current):
        msgs.append("Ligne d'état déjà installée.")
    else:
        msgs.append("Ligne d'état existante conservée (la tienne n'est pas remplacée).")
    groups = data.setdefault("hooks", {}).setdefault("StopFailure", [])
    if any(_ours(h) for g in groups for h in g.get("hooks") or []):
        msgs.append("Bascule après blocage déjà installée.")
    else:
        groups.append({"matcher": "rate_limit", "hooks": [
            {"type": "command", "command": f"{bin_path} hook stop-failure", "timeout": 60}]})
        msgs.append("Bascule après blocage installée (hook StopFailure).")
    _write(path, data)
    return msgs


def uninstall():
    path = settings_path()
    data = _load(path)
    if _ours(data.get("statusLine")):
        del data["statusLine"]
    hooks = data.get("hooks") or {}
    groups = hooks.get("StopFailure") or []
    kept = []
    for g in groups:
        g = dict(g, hooks=[h for h in g.get("hooks") or [] if not _ours(h)])
        if g["hooks"]:
            kept.append(g)
    if kept:
        hooks["StopFailure"] = kept
    else:
        hooks.pop("StopFailure", None)
    if "hooks" in data and not hooks:
        del data["hooks"]
    if path.exists():
        _write(path, data)
    return ["Intégration retirée."]


def status():
    try:
        data = _load(settings_path())
    except IntegrationError:
        data = {}
    sl = data.get("statusLine")
    hook = any(_ours(h) for g in (data.get("hooks") or {}).get("StopFailure") or []
               for h in g.get("hooks") or [])
    return {"statusline": None if sl is None else "ccs" if _ours(sl) else "autre", "hook": hook}


# --------------------------------------------------------------------------
# Ligne d'état
# --------------------------------------------------------------------------

def _hm(iso):
    dt = core.parse_dt(iso)
    return f"{dt.astimezone():%H:%M}" if dt else ""


def statusline_text(state, now):
    active = (state or {}).get("active")
    acc = next((a for a in (state or {}).get("accounts") or [] if a.get("name") == active), None)
    if not acc or not acc.get("limits"):
        return "CCS : pas encore de données"
    lims = {l["kind"]: l for l in acc["limits"]}
    s, w = lims.get("session"), lims.get("weekly_all")
    pct = s["percent"] if s else max(l["percent"] for l in acc["limits"])
    glyph = "○" if pct < 25 else "◔" if pct < 50 else "◑" if pct < 75 else "◕" if pct < 95 else "●"
    parts = [f"{glyph} {active} {pct:.0f} %" + (f" ↻{_hm(s['resets_at'])}" if s and s.get("resets_at") else "")]
    fc = acc.get("forecast") or {}
    if fc.get("verdict") == "limit" and fc.get("eta"):
        parts.append(f"⏱{_hm(fc['eta'])}")
    if w:
        parts.append(f"sem. {w['percent']:.0f} %")
    best = (state.get("best") or {}).get("name")
    if best and best != active and pct >= 80:
        parts.append(f"→ {best}")
    n = len(state.get("accounts") or [])
    if n > 1:
        parts.append(f"{n} comptes")
    return " · ".join(parts)


# --------------------------------------------------------------------------
# Hook StopFailure (limite atteinte pendant une session)
# --------------------------------------------------------------------------

def _fresh_state():
    st = core.load_json(daemon.state_path())
    if daemon.state_fresh(st):
        return st
    if daemon.request_refresh():
        deadline = time.time() + 15
        while time.time() < deadline:
            time.sleep(0.5)
            st = core.load_json(daemon.state_path())
            if daemon.state_fresh(st):
                return st
    else:
        daemon.collect_once()
    return core.load_json(daemon.state_path())


def stop_failure(payload, notifier=notify.send):
    if (payload or {}).get("error") != "rate_limit":
        return "ignoré : pas une limite d'usage"
    now = datetime.now(timezone.utc)
    st = _fresh_state()
    states = daemon.states_from_state(st)
    active = core.active_profile_name()
    reserve = set(((st.get("orchestrator") or {}).get("reserve")) or [])
    decision = autoswitch.rescue(states, active, load_settings(), now, reserve)
    cwd = payload.get("cwd") or ""
    project = os.path.basename(cwd.rstrip("/")) or "une session"
    if decision.action == "switch" and autoswitch.execute(decision, Store(), now, mode="blocage"):
        notifier(Alert(f"blocage:{now.timestamp():.0f}", f"Limite atteinte dans {project}",
                       f"Basculé sur {decision.target}. Tape « continue » dans la session pour reprendre.", 2))
        return f"basculé sur {decision.target}"
    notifier(Alert(f"blocage:{now.timestamp():.0f}", f"Limite atteinte dans {project}",
                   f"Aucun autre compte disponible ({decision.reason}).", 2))
    return decision.reason


def read_stdin_json():
    try:
        return json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}
