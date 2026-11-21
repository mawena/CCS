"""Marqueurs « limite atteinte », un par conversation.

Le hook StopFailure (`integration.stop_failure`) les écrit ; le terminal intégré les lit
pour relancer la conversation bloquée d'un de ses onglets, puis les consomme.

~/.claude-accounts/limits/<session_id>.json (600, dossier 700) :
    {"session_id": "…", "ts": 1793000000.0, "from": "perso", "to": "pro",
     "switched": true, "outcome": "switched"}

`outcome` : « pending » (bascule en cours de décision), « switched » (bascule faite),
« already » (compte déjà changé par une autre session ou le service), « failed »
(`ccs use` a échoué), « exhausted » (aucun autre compte disponible), « paused » (CCS en
pause : ni bascule ni reprise immédiate), « planned » (relance prévue à `resume_at`, quand la
limite sera levée : voir `limit_resume`), « lifted » (limite levée à `lifted_at` : l'interface qui
tient la conversation la relance, puis consomme le marker).

Champs facultatifs : `cwd` (dossier de la conversation), `resume_at` / `lifted_at` (epoch).
"""

import dataclasses
import json
import os
import re
import time
from dataclasses import dataclass

from . import core

KEEP_S = 24 * 3600
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
OUTCOMES = ("pending", "switched", "already", "failed", "exhausted", "paused", "planned", "lifted")
# Fins sans reprise immédiate : `limit_resume` prévoit la relance à la levée de la limite.
WAITING = ("failed", "exhausted", "paused", "planned")
RESUMABLE = ("switched", "already", "lifted")


@dataclass(frozen=True)
class LimitEvent:
    session_id: str
    ts: float
    source: str | None = None     # compte quitté
    target: str | None = None     # compte choisi
    switched: bool = False        # le compte actif a changé : « continue » peut reprendre
    outcome: str = "pending"
    cwd: str | None = None
    resume_at: float | None = None   # relance prévue (outcome « planned »)
    lifted_at: float | None = None   # limite levée (outcome « lifted »)

    @property
    def last_ts(self):
        """Dernier instant connu de l'événement (pour l'âge et le ménage)."""
        return max(t for t in (self.ts, self.resume_at, self.lifted_at) if t is not None)

    def as_dict(self):
        return {"session_id": self.session_id, "ts": self.ts, "from": self.source, "to": self.target,
                "switched": self.switched, "outcome": self.outcome, "cwd": self.cwd,
                "resume_at": self.resume_at, "lifted_at": self.lifted_at}

    @classmethod
    def from_dict(cls, data):
        """Événement lu dans un marqueur, ou None si le contenu est inattendu."""
        if not isinstance(data, dict):
            return None
        sid, ts = data.get("session_id"), data.get("ts")
        if not isinstance(sid, str) or not SAFE_ID.match(sid) or isinstance(ts, bool) \
                or not isinstance(ts, (int, float)):
            return None
        text = lambda v: v if isinstance(v, str) and v else None  # noqa: E731
        stamp = lambda v: float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None  # noqa: E731
        outcome = data.get("outcome")
        return cls(sid, float(ts), text(data.get("from")), text(data.get("to")),
                   bool(data.get("switched")), outcome if outcome in OUTCOMES else "pending",
                   text(data.get("cwd")), stamp(data.get("resume_at")), stamp(data.get("lifted_at")))


def directory():
    return core.paths().store / "limits"


def path(session_id):
    """Fichier du marqueur, ou None pour un identifiant inutilisable comme nom de fichier."""
    if not isinstance(session_id, str) or not SAFE_ID.match(session_id):
        return None
    return directory() / f"{session_id}.json"


def prune(now=None, keep=KEEP_S):
    """Retire les marqueurs de plus de `keep` secondes (conversations jamais reprises ici). Un
    marqueur dont la relance est prévue plus tard (limite de la semaine) est gardé jusque-là."""
    now = time.time() if now is None else now
    try:
        entries = list(os.scandir(directory()))
    except OSError:
        return
    for e in entries:
        try:
            if not e.name.endswith(".json") or e.stat().st_mtime >= now - keep:
                continue
            event = _read(e.path)
            if event is None or event.last_ts < now - keep:
                os.unlink(e.path)
        except OSError:
            pass


def _read(p):
    try:
        with open(p) as f:
            return LimitEvent.from_dict(json.load(f))
    except (OSError, ValueError):
        return None


def record(session_id, ts, source=None, target=None, switched=False, outcome="pending", cwd=None,
           resume_at=None, lifted_at=None):
    """Écrit (ou remplace) le marqueur de la conversation. Ne lève jamais : le hook ne doit
    pas échouer pour un marqueur. Renvoie True si le marqueur est écrit."""
    p = path(session_id)
    if p is None:
        return False
    try:
        core.atomic_write_json(p, {"session_id": session_id, "ts": float(ts), "from": source,
                                   "to": target, "switched": bool(switched), "outcome": outcome,
                                   "cwd": cwd, "resume_at": resume_at, "lifted_at": lifted_at})
        prune()
        return True
    except (OSError, ValueError, TypeError):
        return False


def update(event, **changes):
    """Réécrit le marqueur de `event` avec `changes` (champs de LimitEvent), seulement s'il décrit
    toujours le même événement (un plus récent, écrit par le hook, est gardé). Renvoie le nouvel
    événement, ou None."""
    p = path(event.session_id)
    if p is None:
        return None
    current = _read(p)
    if current is None or current.ts != event.ts:
        return None
    new = dataclasses.replace(current, **changes)
    try:
        core.atomic_write_json(p, new.as_dict())
    except (OSError, ValueError, TypeError):
        return None
    return new


def load_all():
    """{session_id: LimitEvent} des marqueurs présents (fichiers illisibles ignorés)."""
    out = {}
    try:
        entries = list(os.scandir(directory()))
    except OSError:
        return out
    for e in entries:
        if not e.name.endswith(".json"):
            continue
        event = _read(e.path)
        if event is not None and e.name == f"{event.session_id}.json":
            out[event.session_id] = event
    return out


def consume(session_id, ts):
    """Retire le marqueur s'il décrit toujours l'événement `ts` (un plus récent est gardé)."""
    p = path(session_id)
    if p is None:
        return False
    try:
        with open(p) as f:
            event = LimitEvent.from_dict(json.load(f))
        if event is None or event.ts != float(ts):
            return False
        os.unlink(p)
        return True
    except (OSError, ValueError):
        return False
