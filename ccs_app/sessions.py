"""Sessions Claude Code ouvertes sur le PC (lecture seule de ~/.claude/sessions).

Chaque session interactive écrit une fiche `<pid>.json` : nom, dossier, état
(busy / idle / waiting…), motif d'attente, dates. Les fichiers `.key` voisins
ne sont jamais lus.
"""

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import core, transcripts

REPORT_MIN_BUSY_S = 60
INJECTED_PREFIXES = ("Base directory for this skill", "Caveat:", "This session is being continued")
STATE_LABELS = {"busy": "travaille", "waiting": "attend ta réponse", "idle": "au repos"}


@dataclass
class Session:
    pid: int
    session_id: str
    name: str
    cwd: str
    project: str
    state: str           # "busy" | "waiting" | "idle"
    waiting_for: str | None
    started_at: float    # secondes
    state_since: float   # secondes
    kind: str
    entrypoint: str
    proc_start: str | None = None  # date de démarrage du processus (champ 22 de /proc/<pid>/stat)


def sessions_dir():
    return core.paths().config_dir / "sessions"


def projects_dir():
    return core.paths().config_dir / "projects"


def _comm(pid):
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except OSError:
        return None


def _proc_start(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def _is_claude(pid, proc_start=None):
    """Le processus s'appelle `claude` et, si la fiche le précise, a démarré au même
    instant : un pid recyclé n'est jamais pris pour une session."""
    if _comm(pid) != "claude":
        return False
    return proc_start is None or _proc_start(pid) == str(proc_start)


def project_name(cwd):
    if not cwd:
        return "?"
    if Path(cwd) == core.paths().home:
        return "~"
    return Path(cwd).name or cwd


def _state(d):
    status = d.get("status") or ""
    if status == "busy":
        return "busy"
    if status == "waiting" or d.get("waitingFor"):
        return "waiting"
    return "idle"


def state_label(s):
    label = STATE_LABELS[s.state]
    return f"{label} ({s.waiting_for})" if s.state == "waiting" and s.waiting_for else label


def list_sessions():
    d = sessions_dir()
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            pid = int(data["pid"])
            ms = lambda key: float(data.get(key) or 0) / 1000  # noqa: E731
            proc_start = data.get("procStart")
            if not _is_claude(pid, proc_start):
                continue
            out.append(Session(
                pid=pid, session_id=str(data.get("sessionId") or ""), name=str(data.get("name") or pid),
                cwd=str(data.get("cwd") or ""), project=project_name(data.get("cwd")), state=_state(data),
                waiting_for=data.get("waitingFor"), started_at=ms("startedAt"),
                state_since=ms("statusUpdatedAt") or ms("updatedAt"),
                kind=str(data.get("kind") or ""), entrypoint=str(data.get("entrypoint") or ""),
                proc_start=str(proc_start) if proc_start is not None else None))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue  # fiche absente, illisible ou d'un format inconnu
    out.sort(key=lambda s: s.started_at)
    return out


def project_slug(cwd):
    """Nom du dossier de Claude Code pour un projet : tout non-alphanumérique → « - »."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def transcript_path(cwd, session_id):
    return projects_dir() / project_slug(cwd) / f"{session_id}.jsonl"


@dataclass
class ConversationUsage:
    weighted: float
    model: str
    messages: int


def conversation_usage(session):
    rows = transcripts.scan_file(transcript_path(session.cwd, session.session_id))
    by_model = {}
    for r in rows:
        by_model[r.model] = by_model.get(r.model, 0) + r.weighted
    model = max(by_model, key=by_model.get) if by_model else "?"
    return ConversationUsage(sum(by_model.values()), model, len(rows))


@dataclass
class Conversation:
    session_id: str
    updated: float
    title: str


def _first_prompt(path):
    try:
        with open(path, errors="replace") as fh:
            for raw in fh:
                if '"user"' not in raw:
                    continue
                try:
                    d = json.loads(raw)
                    content = d["message"]["content"]
                except (ValueError, KeyError, TypeError):
                    continue
                if d.get("type") != "user" or d.get("isMeta"):
                    continue  # messages injectés par Claude Code (skills, commandes)
                if isinstance(content, list):
                    content = next((c.get("text") for c in content
                                    if isinstance(c, dict) and c.get("type") == "text"), None)
                if (isinstance(content, str) and content.strip() and not content.startswith("<")
                        and not content.startswith(INJECTED_PREFIXES)):
                    line = content.strip().splitlines()[0]
                    return line[:70] + ("…" if len(line) > 70 else "")
    except OSError:
        pass
    return "(sans titre)"


def recent_conversations(cwd, limit=8):
    d = projects_dir() / project_slug(cwd)
    if not d.is_dir():
        return []
    files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    return [Conversation(f.stem, f.stat().st_mtime, _first_prompt(f)) for f in files]


def _cwd_of(path):
    try:
        with open(path, errors="replace") as fh:
            for _, raw in zip(range(50), fh):
                if '"cwd"' in raw:
                    try:
                        return json.loads(raw).get("cwd")
                    except ValueError:
                        continue
    except OSError:
        pass
    return None


def recent_projects(limit=8):
    """[(dossier, date)] des projets où Claude Code a servi récemment."""
    d = projects_dir()
    if not d.is_dir():
        return []
    out = []
    for proj in sorted((p for p in d.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime,
                       reverse=True):
        files = sorted(proj.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        cwd = next((c for c in (_cwd_of(f) for f in files[:3]) if c), None)
        if cwd and os.path.isdir(cwd):  # projet encore présent sur le disque
            out.append((cwd, files[0].stat().st_mtime))
        if len(out) >= limit:
            break
    return out


def transitions(prev, cur, now):
    """Sessions qui viennent de finir (« done ») ou d'attendre (« waiting »)
    après avoir travaillé au moins REPORT_MIN_BUSY_S secondes."""
    out = []
    for s in cur:
        p = prev.get(s.pid)
        if p is None or p.state != "busy" or s.state == "busy":
            continue
        if (s.state_since or now) - p.state_since < REPORT_MIN_BUSY_S:
            continue
        out.append((s, "waiting" if s.state == "waiting" else "done"))
    return out


def _claude_bin():
    extra = f"{core.paths().home}/.local/bin"
    return shutil.which("claude", path=f"{extra}:{os.environ.get('PATH', '')}") or "claude"


def terminal_command(cwd, resume=None):
    term = shutil.which("gnome-terminal") or shutil.which("x-terminal-emulator") or "x-terminal-emulator"
    cmd = shlex.join([_claude_bin(), "--resume", resume]) if resume else shlex.quote(_claude_bin())
    return [term, f"--working-directory={cwd}", "--", "bash", "-lc", cmd]


def open_terminal(cwd, resume=None, start_claude=True):
    if start_claude:
        args = terminal_command(cwd, resume)
    else:
        term = shutil.which("gnome-terminal") or "x-terminal-emulator"
        args = [term, f"--working-directory={cwd}"]
    subprocess.Popen(args, start_new_session=True, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def open_folder(cwd):
    subprocess.Popen(["gio", "open", cwd], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def terminate(pid, proc_start=None):
    """Termine une session Claude Code (SIGTERM) ; refuse tout autre processus.

    Le pidfd fige le processus visé : la vérification et l'envoi du signal portent
    forcément sur le même processus, même si le pid est recyclé entre-temps."""
    try:
        fd = os.pidfd_open(pid)
    except OSError:
        return False
    try:
        if not _is_claude(pid, proc_start):
            return False
        signal.pidfd_send_signal(fd, signal.SIGTERM)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)
