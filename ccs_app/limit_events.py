"""Marqueurs « limite atteinte », un par conversation.

Le hook StopFailure (`integration.stop_failure`) les écrit ; le terminal intégré les lit
pour relancer la conversation bloquée d'un de ses onglets, puis les consomme.

~/.claude-accounts/limits/<session_id>.json (600, dossier 700) :
    {"session_id": "…", "ts": 1793000000.0, "from": "perso", "to": "pro",
     "switched": true, "outcome": "switched"}

`outcome` : « pending » (bascule en cours de décision), « switched » (bascule faite),
« already » (compte déjà changé par une autre session ou le service), « failed »
(`ccs use` a échoué), « exhausted » (aucun autre compte disponible).
"""

import json
import os
import re
import time
from dataclasses import dataclass

from . import core

KEEP_S = 24 * 3600
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
OUTCOMES = ("pending", "switched", "already", "failed", "exhausted")


@dataclass(frozen=True)
class LimitEvent:
    session_id: str
    ts: float
    source: str | None = None     # compte quitté
    target: str | None = None     # compte choisi
    switched: bool = False        # le compte actif a changé : « continue » peut reprendre
    outcome: str = "pending"

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
        outcome = data.get("outcome")
        return cls(sid, float(ts), text(data.get("from")), text(data.get("to")),
                   bool(data.get("switched")), outcome if outcome in OUTCOMES else "pending")


def directory():
    return core.paths().store / "limits"


def path(session_id):
    """Fichier du marqueur, ou None pour un identifiant inutilisable comme nom de fichier."""
    if not isinstance(session_id, str) or not SAFE_ID.match(session_id):
        return None
    return directory() / f"{session_id}.json"


def prune(now=None, keep=KEEP_S):
    """Retire les marqueurs de plus de `keep` secondes (conversations jamais reprises ici)."""
    now = time.time() if now is None else now
    try:
        entries = list(os.scandir(directory()))
    except OSError:
        return
    for e in entries:
        try:
            if e.name.endswith(".json") and e.stat().st_mtime < now - keep:
                os.unlink(e.path)
        except OSError:
            pass


def record(session_id, ts, source=None, target=None, switched=False, outcome="pending"):
    """Écrit (ou remplace) le marqueur de la conversation. Ne lève jamais : le hook ne doit
    pas échouer pour un marqueur. Renvoie True si le marqueur est écrit."""
    p = path(session_id)
    if p is None:
        return False
    try:
        core.atomic_write_json(p, {"session_id": session_id, "ts": float(ts), "from": source,
                                   "to": target, "switched": bool(switched), "outcome": outcome})
        prune()
        return True
    except (OSError, ValueError, TypeError):
        return False


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
        try:
            with open(e.path) as f:
                event = LimitEvent.from_dict(json.load(f))
        except (OSError, ValueError):
            continue
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
