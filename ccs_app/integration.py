"""Intégration dans Claude Code : ligne d'état et bascule après blocage (hook).

`ccs integrate on|off` modifie ~/.claude/settings.json sur demande explicite :
écriture atomique, sauvegarde unique `settings.json.ccs-backup`, une
`statusLine` existante n'est jamais remplacée, seules nos entrées sont
ajoutées ou retirées.
"""

import fcntl
import json
import os
import shlex
import shutil
import sys
import time
from datetime import datetime, timezone

from . import autoswitch, core, daemon, limit_events, notify, pause
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


def _real(path):
    """Cible réelle d'un settings.json qui serait un lien (dépôt de dotfiles)."""
    return path.resolve() if path.is_symlink() else path


def _load(path):
    path = _real(path)
    try:
        text = path.read_text() if path.exists() else ""
    except OSError as e:
        raise IntegrationError(f"{path} illisible : {e}") from e
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as e:
        raise IntegrationError(f"{path} n'est pas un JSON valide : rien n'a été modifié ({e})") from e
    if not isinstance(data, dict):
        raise IntegrationError(f"{path} : contenu inattendu, rien n'a été modifié")
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict) or not isinstance(hooks.get("StopFailure", []), list) \
            or not all(isinstance(g, dict) for g in hooks.get("StopFailure", [])):
        raise IntegrationError(f"{path} : section « hooks » inattendue, rien n'a été modifié")
    return data


def _write(path, data):
    path = _real(path)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    if path.exists():
        # Sauvegarde de l'état juste avant chaque écriture de CCS.
        shutil.copy2(path, path.with_name(path.name + ".ccs-backup"))
    core.atomic_write_json(path, data)
    os.chmod(path, mode)


def _ours(entry, *args):
    """Entrée écrite par CCS : exactement « <…>/claude-accounts <args> »."""
    if not isinstance(entry, dict):
        return False
    try:
        tokens = shlex.split(str(entry.get("command", "")))
    except ValueError:
        return False
    return (len(tokens) == 1 + len(args) and os.path.basename(tokens[0]) == MARK
            and tuple(tokens[1:]) == args)


def install(bin_path=None):
    bin_path = bin_path or default_bin()
    path = settings_path()
    data = _load(path)
    msgs = []
    current = data.get("statusLine")
    if current is None:
        data["statusLine"] = {"type": "command", "command": f"{shlex.quote(bin_path)} statusline",
                              "padding": 0}
        msgs.append("Ligne d'état installée.")
    elif _ours(current, "statusline"):
        msgs.append("Ligne d'état déjà installée.")
    else:
        msgs.append("Ligne d'état existante conservée (la tienne n'est pas remplacée).")
    groups = data.setdefault("hooks", {}).setdefault("StopFailure", [])
    if any(_ours(h, "hook", "stop-failure") for g in groups for h in g.get("hooks") or []):
        msgs.append("Bascule après blocage déjà installée.")
    else:
        groups.append({"matcher": "rate_limit", "hooks": [
            {"type": "command", "command": f"{shlex.quote(bin_path)} hook stop-failure", "timeout": 60}]})
        msgs.append("Bascule après blocage installée (hook StopFailure).")
    _write(path, data)
    return msgs


def uninstall():
    path = settings_path()
    data = _load(path)
    if _ours(data.get("statusLine"), "statusline"):
        del data["statusLine"]
    hooks = data.get("hooks") or {}
    groups = hooks.get("StopFailure") or []
    kept = []
    for g in groups:
        g = dict(g, hooks=[h for h in g.get("hooks") or [] if not _ours(h, "hook", "stop-failure")])
        if g["hooks"]:
            kept.append(g)
    if kept:
        hooks["StopFailure"] = kept
    else:
        hooks.pop("StopFailure", None)
    if "hooks" in data and not hooks:
        del data["hooks"]
    if _real(path).exists():
        _write(path, data)
    return ["Intégration retirée."]


def status():
    try:
        data = _load(settings_path())
    except IntegrationError:
        data = {}
    sl = data.get("statusLine")
    hook = any(_ours(h, "hook", "stop-failure") for g in (data.get("hooks") or {}).get("StopFailure") or []
               for h in g.get("hooks") or [])
    return {"statusline": None if sl is None else "ccs" if _ours(sl, "statusline") else "autre",
            "hook": hook}


# --------------------------------------------------------------------------
# Ligne d'état
# --------------------------------------------------------------------------

def _hm(iso):
    dt = core.parse_dt(iso)
    return f"{dt.astimezone():%H:%M}" if dt else ""


def statusline_text(state, now, payload=None, settings=None):
    """Ligne d'état ; « ⏸ » en tête pendant une pause de CCS.

    `payload` : contexte JSON envoyé par Claude Code (dont le `model` de la session).
    Avec un modèle cher et le compte actif au-delà du seuil du conseil de modèle, la
    ligne ajoute « → sonnet ? » ; avec un contexte lourd (`transcript_path` du contexte),
    elle termine par « ⚠ contexte 182 k » ; rien sinon."""
    hint = ""
    model = payload.get("model") if isinstance(payload, dict) else None
    if model:
        from . import model_advice
        try:
            hint = model_advice.statusline_hint(state, model, settings or load_settings(), now)
        except Exception:  # noqa: BLE001 — réglages illisibles : la ligne reste, sans l'indice
            hint = ""
    text = _statusline(state, now, hint)
    warning = _context_warning(payload, settings)
    if warning:
        text = f"{text} · {warning}"
    return f"⏸ {text}" if (state or {}).get("pause") else text


def _context_warning(payload, settings=None):
    """« ⚠ contexte 182 k » quand la conversation de la session dépasse le seuil de contexte
    lourd (journal donné par `transcript_path` dans le contexte de Claude Code) ; « » sinon,
    et jamais d'erreur : la ligne d'état s'affiche dans chaque session."""
    path = payload.get("transcript_path") if isinstance(payload, dict) else None
    if not path or not isinstance(path, str):
        return ""
    try:
        from . import context_alert
        settings = settings or load_settings()
        if not context_alert.config(settings)["enabled"]:
            return ""
        return context_alert.statusline_hint(context_alert.read_context(path), settings)
    except Exception:  # noqa: BLE001 — journal ou réglages illisibles : pas d'avertissement
        return ""


def _statusline(state, now, hint=""):
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
    if hint:
        parts.append(hint)
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

RECENT_SWITCH_S = 120


def _fresh_state():
    """État à jour : demandé au service s'il tourne, sinon relevé seul (aucune
    décision ni alerte, pour ne pas croiser une bascule automatique)."""
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
        daemon.observe_once()
    return core.load_json(daemon.state_path())


def _hook_lock():
    path = core.paths().store / "hook.lock"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    f = open(path, "w")
    fcntl.flock(f, fcntl.LOCK_EX)
    return f


def _paused(now):
    """Pause de CCS en cours, ou None (une pause illisible ne fait jamais échouer le hook)."""
    try:
        return pause.pause_state(now)
    except (OSError, ValueError, TypeError, OverflowError):
        return None


def stop_failure(payload, notifier=notify.send):
    """Hook StopFailure (matcher rate_limit) : une seule bascule même si plusieurs
    sessions sont bloquées en même temps, aucune si le compte vient de changer ni
    pendant une pause de CCS.

    Laisse aussi un marqueur par conversation (`limit_events`) : le terminal intégré s'en
    sert pour relancer la conversation bloquée d'un de ses onglets."""
    if not isinstance(payload, dict):
        payload = {}
    if payload.get("error", "rate_limit") != "rate_limit":
        return "ignoré : pas une limite d'usage"
    session_id = payload.get("session_id")

    def mark(outcome, source=None, target=None, switched=False):
        limit_events.record(session_id, time.time(), source, target, switched, outcome)

    mark("pending")
    cwd = str(payload.get("cwd") or "")
    project = os.path.basename(cwd.rstrip("/")) or "une session"
    title = f"Limite atteinte dans {project}"
    with _hook_lock():
        now = datetime.now(timezone.utc)
        store = Store()
        before = core.active_profile_name()
        paused = _paused(now)
        if paused is not None:
            # Pause : ni bascule ni reprise automatique ; une notification pour toutes les
            # sessions bloquées en même temps.
            mark("paused", before)
            if not store.events(now.timestamp() - RECENT_SWITCH_S, type="alert", profile="blocage"):
                store.add_event(now.timestamp(), "alert", "blocage", {"key": "pause"})
                notifier(Alert(f"blocage:{now.timestamp():.0f}", title,
                               f"CCS est en pause {pause.label(paused, now)} : pas de bascule automatique.", 2))
            return "en pause"
        recent = [e for e in store.events(now.timestamp() - RECENT_SWITCH_S, type="switch")]
        if recent:
            # Une autre session bloquée (ou le service) vient de basculer : on ne rebascule pas.
            mark("already", recent[-1].detail.get("from"), recent[-1].profile, True)
            if not store.events(now.timestamp() - RECENT_SWITCH_S, type="alert", profile="blocage"):
                store.add_event(now.timestamp(), "alert", "blocage", {"key": "deja"})
                notifier(Alert(f"blocage:{now.timestamp():.0f}", title,
                               f"Compte déjà changé pour {recent[-1].profile}. Tape « continue » "
                               "dans la session pour reprendre.", 2))
            return "déjà basculé"
        st = _fresh_state()
        now = datetime.now(timezone.utc)
        after = core.active_profile_name()
        if after != before:
            mark("already", before, after, True)
            notifier(Alert(f"blocage:{now.timestamp():.0f}", title,
                           f"Compte déjà changé pour {after}. Tape « continue » dans la session pour reprendre.", 2))
            return "déjà basculé"
        states = daemon.states_from_state(st)
        reserve = set(((st.get("orchestrator") or {}).get("reserve")) or [])
        decision = autoswitch.rescue(states, after, load_settings(), now, reserve)
        store.add_event(now.timestamp(), "alert", "blocage", {"key": f"blocage:{now.timestamp():.0f}"})
        if decision.action == "switch":
            if autoswitch.execute(decision, store, now, mode="blocage"):
                mark("switched", after, decision.target, True)
                notifier(Alert(f"blocage:{now.timestamp():.0f}", title,
                               f"Basculé sur {decision.target}. Tape « continue » dans la session pour reprendre.", 2))
                return f"basculé sur {decision.target}"
            mark("failed", after, decision.target)
            notifier(Alert(f"blocage:{now.timestamp():.0f}", title,
                           f"Bascule vers {decision.target} impossible : ouvre « CCS » "
                           "pour voir l'erreur.", 2))
            return "bascule impossible"
        mark("exhausted", after)
        notifier(Alert(f"blocage:{now.timestamp():.0f}", title,
                       f"Aucun autre compte disponible — {decision.reason}.", 2))
        return decision.reason


STDIN_TIMEOUT_S = 2.0


def read_stdin_json(timeout=STDIN_TIMEOUT_S):
    """Contexte JSON envoyé par Claude Code sur l'entrée standard ({} s'il est absent,
    vide ou illisible). Jamais d'attente sur un terminal ; au plus `timeout` secondes
    si rien n'arrive sur un tube resté ouvert."""
    stdin = sys.stdin
    try:
        if stdin is None or stdin.isatty():
            return {}
        try:
            fd = stdin.fileno()
        except (AttributeError, OSError, ValueError):
            fd = None  # flux sans descripteur (tests) : lecture directe
        if fd is not None:
            import select
            if not select.select([fd], [], [], timeout)[0]:
                return {}
        data = json.loads(stdin.read() or "{}")
    except (ValueError, OSError):  # JSON ou encodage illisible, entrée fermée
        return {}
    return data if isinstance(data, dict) else {}
