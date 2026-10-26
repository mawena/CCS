"""Sessions Claude Code ouvertes sur le PC (lecture seule de ~/.claude/sessions).

Chaque session interactive écrit une fiche `<pid>.json` : nom, dossier, état
(busy / idle / waiting…), motif d'attente, dates. Les fichiers `.key` voisins
ne sont jamais lus.
"""

import json
import os
import re
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import core, transcripts

REPORT_MIN_BUSY_S = 60
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


def sessions_dir():
    return core.paths().config_dir / "sessions"


def projects_dir():
    return core.paths().config_dir / "projects"


def _is_claude(pid):
    """Le pid existe et c'est bien Claude Code (pas un pid recyclé)."""
    try:
        with open(f"/proc/{pid}/comm") as f:
            comm = f.read().strip()
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmd = f.read()
    except OSError:
        return False
    return comm == "claude" or b"claude" in cmd.split(b"\0")[0]


def _project(cwd):
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
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if not _is_claude(pid):
            continue
        ms = lambda key: (data.get(key) or 0) / 1000  # noqa: E731
        out.append(Session(
            pid=pid, session_id=str(data.get("sessionId") or ""), name=str(data.get("name") or pid),
            cwd=str(data.get("cwd") or ""), project=_project(data.get("cwd")), state=_state(data),
            waiting_for=data.get("waitingFor"), started_at=ms("startedAt"),
            state_since=ms("statusUpdatedAt") or ms("updatedAt"),
            kind=str(data.get("kind") or ""), entrypoint=str(data.get("entrypoint") or "")))
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
                if d.get("type") != "user":
                    continue
                if isinstance(content, list):
                    content = next((c.get("text") for c in content
                                    if isinstance(c, dict) and c.get("type") == "text"), None)
                if isinstance(content, str) and content.strip() and not content.startswith("<"):
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
    cmd = _claude_bin() + (f" --resume {resume}" if resume else "")
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


def terminate(pid):
    """Termine une session Claude Code (SIGTERM) ; refuse tout autre processus."""
    if not _is_claude(pid):
        return False
    os.kill(pid, signal.SIGTERM)
    return True
