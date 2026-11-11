"""Mémoire des sessions Claude Code ouvertes : RAM occupée et inactivité.

La RAM d'une session est la somme du PSS (mémoire réellement partagée au prorata,
`/proc/<pid>/smaps_rollup`) du processus `claude` et de tous ses descendants (outils,
serveurs MCP, terminal) ; à défaut de PSS (noyau ou droits), le RSS de `/proc/<pid>/status`.
Un processus qui disparaît en cours de lecture compte pour 0, sans lever.

L'inactivité part de la dernière écriture du journal de la conversation ou du dernier
changement d'état de la session, le plus récent des deux ; une session qui travaille n'est
jamais inactive. Rien n'est jamais fermé ici : la fermeture reste un geste de Charles.

Tous les chemins de `/proc` sont injectables (`proc`) pour les tests.
"""

import os
import time
from dataclasses import dataclass

from . import core, sessions

DEFAULTS = {"idle_hours": 2}
PROC = "/proc"


def idle_hours(settings=None):
    """Seuil d'inactivité (heures) du réglage `sessions.idle_hours`, repli 2 h."""
    raw = (settings or {}).get("sessions")
    raw = raw if isinstance(raw, dict) else {}
    try:
        value = float(raw.get("idle_hours", DEFAULTS["idle_hours"]))
    except (TypeError, ValueError):
        return float(DEFAULTS["idle_hours"])
    return value if value > 0 else float(DEFAULTS["idle_hours"])


# --------------------------------------------------------------------------
# Mesure de la RAM
# --------------------------------------------------------------------------

def _kb(path, key):
    """Valeur (ko) de la ligne « key: N kB » d'un fichier de /proc, ou None."""
    try:
        with open(path) as fh:
            for line in fh:
                if line.startswith(key):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def process_bytes(pid, proc=PROC):
    """Mémoire d'un seul processus en octets : PSS, sinon RSS, sinon 0."""
    kb = _kb(f"{proc}/{pid}/smaps_rollup", "Pss:")
    if kb is None:
        kb = _kb(f"{proc}/{pid}/status", "VmRSS:")
    return (kb or 0) * 1024


def children_map(proc=PROC):
    """{pid parent: [pids enfants]} d'après /proc/<pid>/stat (processus disparus ignorés)."""
    out = {}
    try:
        names = os.listdir(proc)
    except OSError:
        return out
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(f"{proc}/{name}/stat") as fh:
                ppid = int(fh.read().rsplit(")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            continue
        out.setdefault(ppid, []).append(int(name))
    return out


def descendants(pid, children):
    """`pid` et tous ses descendants (sans boucle, même si /proc est incohérent)."""
    found, todo, known = [], [pid], set()
    while todo:
        p = todo.pop()
        if p in known:
            continue
        known.add(p)
        found.append(p)
        todo.extend(children.get(p, ()))
    return found


def session_bytes(pid, proc=PROC, children=None):
    """RAM de la session : processus `claude` et descendants, en octets (0 s'il a disparu)."""
    if children is None:
        children = children_map(proc)
    return sum(process_bytes(p, proc) for p in descendants(pid, children))


# --------------------------------------------------------------------------
# Inactivité
# --------------------------------------------------------------------------

def journal_mtime(session):
    """Date de la dernière écriture du journal de la conversation, ou 0."""
    path = sessions.journal_path(session)
    try:
        return os.stat(path).st_mtime if path else 0.0
    except OSError:
        return 0.0


def idle_seconds(session, now, mtime=0.0):
    """Secondes d'inactivité : 0 pendant un tour de travail, sinon depuis le plus récent de
    la dernière écriture du journal et du dernier changement d'état."""
    if session.state == "busy":
        return 0.0
    last = max(mtime or 0.0, session.state_since or 0.0)
    if not last:
        last = session.started_at or now
    return max(0.0, now - last)


# --------------------------------------------------------------------------
# Instantané
# --------------------------------------------------------------------------

@dataclass
class SessionMemory:
    pid: int
    ram: int            # octets
    idle_s: float
    idle: bool          # inactive depuis au moins le seuil


@dataclass
class Summary:
    total: int           # RAM de toutes les sessions
    count: int           # sessions mesurées
    idle_count: int
    idle_total: int      # RAM des sessions inactives au-delà du seuil


def snapshot(found, now=None, settings=None, proc=PROC, mtime=journal_mtime):
    """{pid: SessionMemory} pour les sessions `found` (une seule lecture de /proc)."""
    now = time.time() if now is None else now
    limit = idle_hours(settings) * 3600
    children = children_map(proc)
    out = {}
    for s in found:
        idle = idle_seconds(s, now, mtime(s))
        out[s.pid] = SessionMemory(s.pid, session_bytes(s.pid, proc, children), idle, idle >= limit)
    return out


def summary(snap):
    """Totaux d'un instantané."""
    idle = [m for m in snap.values() if m.idle]
    return Summary(sum(m.ram for m in snap.values()), len(snap), len(idle), sum(m.ram for m in idle))


# --------------------------------------------------------------------------
# Textes
# --------------------------------------------------------------------------

def fmt_bytes(n):
    """« 820 Mo », « 1,4 Go » (unités de 1024, virgule décimale)."""
    n = max(0, int(n or 0))
    if n >= 1024 ** 3:
        return f"{core.fr(n / 1024 ** 3)} Go"
    return f"{round(n / 1024 ** 2)} Mo"


def fmt_idle(seconds):
    """« inactive depuis 25 min », « inactive depuis 3 h 12 » ; « » en dessous d'une minute."""
    minutes = int(seconds // 60)
    if minutes < 1:
        return ""
    if minutes >= 60:
        return f"inactive depuis {minutes // 60} h {minutes % 60:02d}"
    return f"inactive depuis {minutes} min"


def banner_text(total):
    """Bandeau « 2 sessions inactives occupent 1,4 Go » ; None s'il n'y en a pas."""
    if total.idle_count < 1:
        return None
    many = total.idle_count > 1
    return (f"{total.idle_count} session{'s' if many else ''} inactive{'s' if many else ''} "
            f"{'occupent' if many else 'occupe'} {fmt_bytes(total.idle_total)}")


def line_text(mem):
    """« 1,2 Go · inactive depuis 3 h 12 » pour une carte ou `ccs sessions`."""
    parts = [fmt_bytes(mem.ram)]
    idle = fmt_idle(mem.idle_s)
    if idle:
        parts.append(idle)
    return " · ".join(parts)
