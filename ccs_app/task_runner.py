"""Exécution d'une tâche de la file (`tasks`) : `claude -p` sans fenêtre, journal, suivi.

- Commande : `claude -p --output-format stream-json --verbose [--model m] [--permission-mode p]
  [--resume <session_id>] -- <message>` dans le dossier de la tâche ; droits via `launch_options`.
- Si `gagarine` existe, la tâche passe par sa file : `gagarine file --priorite fond
  "ccs tâche <id>" 1 1 -- sh -c 'exec "$@" >> journal 2>&1' journal claude …`. Gagarine fait hériter
  sa sortie au travail et renvoie son code, mais écrit ses propres messages d'attente sur la même
  sortie : c'est donc `sh` qui écrit la sortie de `claude` dans le journal, et celle de gagarine
  est jetée.
- Journal : ~/.claude-accounts/tasks/<id>.jsonl, ajouté à chaque lancement (`extra["offset"]`
  marque le début du dernier) ; une ligne `{"type": "ccs", …}` note chaque lancement.
- Fin d'un lancement (`poll`) : `Result` (session, limite atteinte, durée, coût). Après une limite,
  `prepare` bascule de compte (jamais pendant une pause : `tasks.decide` n'y arrive pas) et
  `tasks.tick` relance par `--resume <session_id>` avec « continue ».
"""

import json
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import core, launch_options, tasks

CONTINUE_MESSAGE = "continue"
QUEUE_RAM_GO = "1"
QUEUE_CORES = "1"
LIMIT_RE = re.compile(r"usage limit|limit reached|rate[ _-]?limit|limite d'usage|"
                      r"hit your (?:usage )?limit|resets? at|quota exceeded", re.I)
SESSION_VARS = ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT",
                "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ATTENDED",
                "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN")
STOP_WAIT_S = 10

_PROCS = {}      # identifiant de tâche -> Popen lancé par ce processus (le service)


@dataclass
class Result:
    ok: bool = False
    limit: bool = False
    cancelled: bool = False
    session_id: str | None = None
    duration: float = 0.0
    cost: float | None = None
    total: bool = False            # `cost` est celui de toute la conversation (journal de Claude Code)
    error: str | None = None
    code: int | None = None


# --------------------------------------------------------------------------
# Commande
# --------------------------------------------------------------------------

def claude_bin():
    from . import sessions
    return sessions._claude_bin()


def gagarine_bin():
    return shutil.which("gagarine")


def claude_argv(task, resume=False, claude=None):
    """Argv de `claude` pour la tâche ; `resume` : reprise de sa conversation avec « continue »."""
    session = task.session_id if resume else None
    if resume and not session:
        raise ValueError("pas de conversation à reprendre")
    message = CONTINUE_MESSAGE if resume else task.message
    args = launch_options.claude_args(task.model, tasks.RIGHTS[task.rights], resume=session)
    return [claude or claude_bin(), "-p", "--output-format", "stream-json", "--verbose", *args, "--", message]


def build_command(task, resume=False, claude=None, gagarine=None, journal=None):
    """Argv complet : par la file de Gagarine si `gagarine` est donné, sinon direct ; dans les
    deux cas `sh` écrit la sortie de `claude` dans le journal."""
    journal = str(journal or tasks.journal_path(task.id))
    inner = ["sh", "-c", 'exec "$@" >>"$0" 2>&1', journal, *claude_argv(task, resume, claude)]
    if not gagarine:
        return inner
    return [gagarine, "file", "--priorite", "fond", f"ccs tâche {task.id}", QUEUE_RAM_GO, QUEUE_CORES, "--", *inner]


def environment():
    p = core.paths()
    env = {k: v for k, v in os.environ.items() if k not in SESSION_VARS}
    env["PATH"] = f"{p.home}/.local/bin:{env.get('PATH', '/usr/bin:/bin')}"
    env["NO_COLOR"] = "1"
    return env


# --------------------------------------------------------------------------
# Journal
# --------------------------------------------------------------------------

def _note(task_id, **fields):
    p = tasks.journal_path(task_id)
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps({"type": "ccs", **fields}, ensure_ascii=False) + "\n")
    os.chmod(p, 0o600)


def _events(task_id, offset=0):
    try:
        with open(tasks.journal_path(task_id), "rb") as f:
            f.seek(max(0, offset))
            data = f.read()
    except OSError:
        return []
    out = []
    for raw in data.splitlines():
        try:
            ev = json.loads(raw)
        except ValueError:
            ev = {"type": "raw", "text": raw.decode("utf-8", "replace")}
        if isinstance(ev, dict):
            out.append(ev)
    return out


def _text_of(ev):
    """Texte d'un message : blocs `text` d'un message Claude, ou chaîne."""
    msg = ev.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def is_limit_event(ev):
    """L'événement dit-il que la limite d'usage est atteinte ?"""
    if ev.get("error") == "rate_limit":
        return True
    if ev.get("type") == "result" and ev.get("is_error"):
        return bool(LIMIT_RE.search(str(ev.get("result") or "")))
    if ev.get("type") == "assistant" and ev.get("error") in ("rate_limit", "billing_error"):
        return True
    info = ev.get("rate_limit_info")
    if ev.get("type") == "rate_limit_event" and isinstance(info, dict):
        return info.get("status") in ("rejected", "blocked")
    if ev.get("type") == "raw":
        return bool(LIMIT_RE.search(ev.get("text", "")))
    return False


def analyze(task_id, offset=0):
    """Ce que dit la fin du journal depuis `offset` : (session_id, résultat, limite, texte d'erreur)."""
    session, final, limit = None, None, False
    for ev in _events(task_id, offset):
        if isinstance(ev.get("session_id"), str):
            session = ev["session_id"]
        if is_limit_event(ev):
            limit = True
        if ev.get("type") == "result":
            final = ev
    return session, final, limit


def readable(line):
    """Ligne de journal lisible (« texte de Claude », « ▸ outil »…), ou « » à ne pas afficher."""
    try:
        ev = json.loads(line)
    except ValueError:
        return line.strip()
    if not isinstance(ev, dict):
        return ""
    kind = ev.get("type")
    if kind == "ccs":
        return f"— {ev.get('text') or ('reprise' if ev.get('resume') else 'démarrage')}"
    if kind == "assistant":
        parts = []
        content = (ev.get("message") or {}).get("content")
        for b in content if isinstance(content, list) else []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and b.get("text", "").strip():
                parts.append(b["text"].strip())
            elif b.get("type") == "tool_use":
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                arg = next((str(v) for v in inp.values() if isinstance(v, str)), "")
                parts.append(f"▸ {b.get('name', 'outil')} {' '.join(arg.split())[:80]}".rstrip())
        return "\n".join(parts)
    if kind == "result":
        text = str(ev.get("result") or "").strip()
        return ("✗ " if ev.get("is_error") else "✓ ") + (text.splitlines()[0][:200] if text else "terminé")
    if kind == "raw":
        return ev.get("text", "")
    return ""


def session_cost(session_id):
    """Coût équivalent (dollars) de toute la conversation d'après son journal Claude Code, ou None."""
    from . import costs
    if not session_id or not re.match(r"^[A-Za-z0-9_-]+$", session_id):
        return None
    root = core.paths().config_dir / "projects"
    try:
        found = next(iter(root.glob(f"*/{session_id}.jsonl")), None)
    except OSError:
        found = None
    if found is None:
        return None
    return costs.conversation_cost(found).dollars


# --------------------------------------------------------------------------
# Processus
# --------------------------------------------------------------------------

def _alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def start(task, now, resume=False, attempts=0, popen=None, claude=None, gagarine="auto", env=None):
    """Lance la tâche (ou sa reprise) ; la marque « en cours ». `gagarine` : « auto » (celui du
    PATH s'il existe), None (sans file) ou un chemin. Lève OSError, ValueError."""
    if gagarine == "auto":
        gagarine = gagarine_bin()
    argv = build_command(task, resume, claude, gagarine)
    p = tasks.journal_path(task.id)
    if not resume and p.exists():
        p.unlink()
    _note(task.id, resume=resume, attempt=attempts, ts=now.timestamp(),
          text=f"reprise ({attempts}) par « continue »" if resume else "démarrage")
    offset = p.stat().st_size
    proc = (popen or subprocess.Popen)(argv, cwd=task.cwd, env=env or environment(), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       start_new_session=True)
    _PROCS[task.id] = proc
    extra = dict(task.extra, offset=offset, run_started=now.timestamp(), queued=bool(gagarine))
    return tasks.update(task.id, state=tasks.RUNNING, pid=proc.pid, started=task.started or now.timestamp(),
                        account=core.active_profile_name(), attempts=attempts, retry_at=None, note="",
                        extra=extra)


def stop(task):
    """Arrête le processus de la tâche (groupe entier : file Gagarine, sh, claude)."""
    proc = _PROCS.pop(task.id, None)
    pid = proc.pid if proc is not None else task.pid
    if not pid or not _alive(pid):
        if proc is not None:
            proc.poll()
        return
    for sig, wait in ((signal.SIGTERM, STOP_WAIT_S), (signal.SIGKILL, 3)):
        try:
            os.killpg(pid, sig)
        except (ProcessLookupError, PermissionError):
            break
        end = time.monotonic() + wait
        while time.monotonic() < end:
            if proc is not None:
                if proc.poll() is not None:
                    return
            elif not _alive(pid):
                return
            time.sleep(0.1)


def poll(task, now):
    """None tant que le lancement tourne ; sinon son `Result`."""
    proc = _PROCS.get(task.id)
    code = None
    if proc is not None:
        code = proc.poll()
        if code is None:
            return None
        _PROCS.pop(task.id, None)
    elif _alive(task.pid):
        return None            # lancé avant un redémarrage du service : on attend sa fin
    offset = int(task.extra.get("offset") or 0)
    session, final, limit = analyze(task.id, offset)
    started = task.extra.get("run_started") or task.started or now.timestamp()
    res = Result(session_id=session, duration=max(0.0, now.timestamp() - started), code=code, limit=limit)
    if final is not None:
        if isinstance(final.get("duration_ms"), (int, float)):
            res.duration = final["duration_ms"] / 1000
        if isinstance(final.get("total_cost_usd"), (int, float)):
            res.cost = float(final["total_cost_usd"])
    total = session_cost(session or task.session_id)
    if total is not None:
        res.cost, res.total = total, True
    clean = final is not None and not final.get("is_error") and code in (0, None)
    res.ok = clean
    res.limit = limit and not clean
    if not clean and not res.limit:
        res.error = _error_text(final, code)
    return res


def _error_text(final, code):
    text = str((final or {}).get("result") or "").strip()
    if text:
        return " ".join(text.split())[:300]
    if code == 137:
        return "arrêtée par la limite mémoire de la file Gagarine"
    return f"claude s'est arrêté sans résultat (code {code})" if code is not None else "claude s'est arrêté sans résultat"


# --------------------------------------------------------------------------
# Compte
# --------------------------------------------------------------------------

def prepare(task, state, settings, now, switch=None, active=None):
    """Prépare le lancement : bascule vers un compte utilisable si le compte actif est au-dessus du
    seuil de bascule, ou, pour une reprise après limite, s'il n'a pas changé depuis. Jamais pendant
    une pause (`tasks.decide` ne propose rien alors). Renvoie (ok, message d'attente).
    `switch(decision)` : exécute la bascule (défaut : `autoswitch.execute`)."""
    from . import autoswitch, pause
    from .daemon import states_from_state
    from .settings import load_settings
    if pause.pause_state(now) is not None:
        return False, "CCS est en pause"
    active = active or core.active_profile_name()
    full = settings if settings and "auto_switch" in settings else load_settings()
    states = states_from_state(state)
    me = next((a for a in states if a.name == active), None)
    resuming = task.state == tasks.WAITING
    if resuming and task.account and active != task.account:
        return True, ""                      # déjà basculé (hook StopFailure, service)
    over = me is not None and any(_pct_over(lim, now, full) for lim in me.limits)
    if not resuming and not over:
        return True, ""
    reserve = set(((state or {}).get("orchestrator") or {}).get("reserve") or [])
    decision = autoswitch.rescue(states, active, full, now, reserve)
    if decision.action != "switch":
        return False, f"aucun compte disponible ({decision.reason})"
    if switch is None:
        from .store import Store
        store = Store()
        try:
            done = autoswitch.execute(decision, store, now, mode="blocage" if resuming else "auto")
        finally:
            store.close()
    else:
        done = switch(decision)
    return (True, "") if done else (False, f"bascule vers {decision.target} impossible")


def _pct_over(lim, now, full):
    from .forecast import effective_percent
    return effective_percent(lim, now) >= full["auto_switch"]["threshold"]
