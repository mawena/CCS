"""Fiche « où j'en étais » d'une conversation Claude Code.

Lue dans le journal (normal ou archivé), sans aucun appel à Claude : dernière demande
de l'utilisateur (le texte tapé, pas les résultats d'outils), début de la dernière
réponse, fichiers modifiés (outils d'écriture), dernière liste de tâches, dossier,
branche git, compte actif à ce moment (journal des bascules) s'il est connu, date.
"""

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime

from . import archive, conversations, core, preview, sessions

REPLY_MAX = 400
REQUEST_MAX = 600
FILES_MAX = 12
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
MAX_LINE_BYTES = 4_000_000
STATUS_MARKS = {"completed": "[x]", "in_progress": "[~]", "pending": "[ ]"}
USAGE = "usage : ccs fiche <identifiant>"


@dataclass
class Fiche:
    session_id: str = ""
    title: str = ""
    cwd: str = ""
    branch: str = ""
    when: float | None = None          # dernière activité (secondes)
    last_request: str = ""
    last_reply: str = ""
    files: list = field(default_factory=list)   # fichiers modifiés, le plus récent en dernier
    todos: list = field(default_factory=list)   # [(état, texte)]
    account: str | None = None
    archived: bool = False

    @property
    def project(self):
        return sessions.project_name(self.cwd) if self.cwd else ""


def _short(text, limit):
    line = " ".join(str(text).split())
    return line if len(line) <= limit else line[:limit - 1].rstrip() + "…"


def _written_path(name, inp):
    if not isinstance(inp, dict):
        return None
    path = inp.get("file_path") if name != "NotebookEdit" else inp.get("notebook_path")
    return path if isinstance(path, str) and path else None


def _todos(inp):
    out = []
    for t in (inp or {}).get("todos") or []:
        if isinstance(t, dict) and isinstance(t.get("content"), str):
            status = t.get("status") if t.get("status") in STATUS_MARKS else "pending"
            out.append((status, _short(t["content"], 160)))
    return out


def _wanted(raw):
    if b'"type":"user"' not in raw and b'"type":"assistant"' not in raw \
            and b'"type": "user"' not in raw and b'"type": "assistant"' not in raw:
        return False
    return len(raw) <= MAX_LINE_BYTES or b'"tool_result"' not in raw


def _scan(fh, fiche):
    """Parcourt le journal une fois, en flux, et remplit la fiche."""
    files = {}          # chemin -> numéro d'ordre de la dernière modification
    n = 0
    for raw in fh:
        if not raw.endswith(b"\n"):
            break  # ligne en cours d'écriture
        if not _wanted(raw):
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(d, dict) or d.get("isSidechain"):
            continue
        kind = d.get("type")
        ts = preview._ts(d.get("timestamp"))
        if ts:
            fiche.when = ts
        if d.get("gitBranch"):
            fiche.branch = d["gitBranch"]
        if d.get("cwd") and not fiche.cwd:
            fiche.cwd = d["cwd"]
        msg = d.get("message") or {}
        if kind == "user":
            _user(d, msg, fiche)
        elif kind == "assistant" and msg.get("model") != "<synthetic>":
            for b in msg.get("content") if isinstance(msg.get("content"), list) else ():
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and isinstance(b.get("text"), str) and b["text"].strip() \
                        and not d.get("isApiErrorMessage"):
                    fiche.last_reply = b["text"].strip()
                elif b.get("type") == "tool_use":
                    name = b.get("name")
                    if name in WRITE_TOOLS:
                        path = _written_path(name, b.get("input"))
                        if path:
                            n += 1
                            files[path] = n
                    elif name == "TodoWrite":
                        fiche.todos = _todos(b.get("input"))
    fiche.files = sorted(files, key=files.get)
    fiche.last_reply = _short(fiche.last_reply, REPLY_MAX)


def _user(d, msg, fiche):
    if d.get("isMeta") or d.get("isCompactSummary"):
        return
    origin = d.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return
    content = msg.get("content")
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
    parts = []
    for b in blocks if isinstance(blocks, list) else ():
        if not isinstance(b, dict) or b.get("type") != "text" or not isinstance(b.get("text"), str):
            continue
        if b["text"].strip().startswith(preview.INTERRUPTED):
            continue
        text = preview.user_text(b["text"])
        if text:
            parts.append(text)
    if parts:
        fiche.last_request = _short("\n\n".join(parts), REQUEST_MAX)


def account_at(when, store=None):
    """Compte actif à la date `when`, d'après le journal des bascules (None si inconnu)."""
    if not when:
        return None
    try:
        if store is None:
            from .store import Store
            store = Store()
        periods = store.active_periods(when - 1, when + 1)
    except Exception:  # base absente ou illisible : la fiche s'en passe
        return None
    for start, end, profile in periods:
        if start <= when < end:
            return profile
    return periods[0][2] if periods else None


def build(conv, store=None, with_account=True):
    """Fiche d'une `conversations.Conversation` (journal normal ou archivé).
    OSError si le journal est illisible."""
    fiche = Fiche(session_id=conv.session_id, title=conv.title, cwd=conv.cwd,
                  branch=conv.git_branch, archived=bool(getattr(conv, "archived", False)))
    with archive.open_journal(conv.path) as fh:
        _scan(fh, fiche)
    fiche.cwd = fiche.cwd or conv.cwd
    fiche.branch = fiche.branch or conv.git_branch
    fiche.when = fiche.when or conv.updated_at or None
    if with_account:
        fiche.account = account_at(fiche.when, store)
    return fiche


def _date(ts):
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y à %H:%M") if ts else "?"


def _short_path(path, cwd):
    if cwd and path.startswith(cwd.rstrip("/") + "/"):
        return path[len(cwd.rstrip("/")) + 1:]
    home = str(core.paths().home)
    return "~" + path[len(home):] if path.startswith(home + "/") else path


def format_text(f):
    """Texte de la fiche pour la ligne de commande."""
    lines = [f"Où j'en étais — {f.title or f.session_id}", ""]
    lines.append(f"Dernière activité : {_date(f.when)}" + (" (conversation archivée)" if f.archived else ""))
    if f.cwd:
        lines.append(f"Dossier : {f.cwd}")
    if f.branch:
        lines.append(f"Branche : {f.branch}")
    if f.account:
        lines.append(f"Compte actif alors : {f.account}")
    lines += ["", "Ta dernière demande :", f"  {f.last_request or '(aucune)'}", "",
              "Début de la dernière réponse :", f"  {f.last_reply or '(aucune)'}"]
    if f.files:
        shown = f.files[-FILES_MAX:]
        lines += ["", f"Fichiers modifiés ({len(f.files)}) :"]
        if len(f.files) > len(shown):
            lines.append(f"  … {len(f.files) - len(shown)} de plus avant")
        lines += [f"  {_short_path(p, f.cwd)}" for p in shown]
    if f.todos:
        done = sum(1 for s, _ in f.todos if s == "completed")
        lines += ["", f"Liste de tâches ({done}/{len(f.todos)}) :"]
        lines += [f"  {STATUS_MARKS[s]} {t}" for s, t in f.todos]
    return "\n".join(lines)


def command(args, out=None, err=None, store=None):
    """« ccs fiche <identifiant> » : affiche la fiche et renvoie le code de sortie
    (0 réussi, 1 conversation ou journal introuvable, 2 mauvais arguments)."""
    out, err = out or sys.stdout, err or sys.stderr
    args = list(args or [])
    if len(args) != 1 or args[0].startswith("-"):
        print(USAGE, file=err)
        return 2
    try:
        conv = conversations.find(conversations.scan(), args[0])
        fiche = build(conv, store=store)
    except (LookupError, OSError) as e:
        print(f"Erreur : {e}", file=err)
        return 1
    print(format_text(fiche), file=out)
    return 0
