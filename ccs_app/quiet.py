"""Ne pas déranger : plages de silence, silence temporaire, notifications retenues et résumé.

Deux sources de silence se cumulent :
- la **plage** des réglages (`alerts.quiet` : début, fin, jours, « allow_waiting »), qui peut
  passer minuit, en heure locale réelle (mêmes règles que la plage de l'orchestrateur) ;
- le **silence temporaire** (`~/.claude-accounts/quiet.json` : `{"since", "until"}`, `until`
  nul = jusqu'à reprise manuelle), posé par « 1h », « 4h », « demain » ; levé tout seul à
  l'échéance. Fichier illisible : pas de silence.

`notify.send` interroge `should_hold` : pendant un silence les notifications sont retenues
(comptées par genre dans `quiet_held.json`, partagé par le service et les hooks), sauf
- « attend ta réponse » et son rappel quand `allow_waiting` (réglage, vrai par défaut) ;
- `blocage:*` : une session bloquée par la limite d'usage, signalée par le hook StopFailure
  (rare, une seule fois pour toutes les sessions bloquées en même temps, et l'utilisateur doit
  taper « continue » : même nature qu'une attente) ;
- le résumé de fin de silence lui-même, et les notifications passagères des raccourcis
  (`transient`, action directe de l'utilisateur).
À la fin du silence, le service appelle `flush` : une seule notification de résumé.
"""

import fcntl
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone

from . import core, orchestrator, pause

CHOICES = ("1h", "4h", "demain")
RESUME = ("off", "reprendre")
DURATIONS = {"1h": timedelta(hours=1), "4h": timedelta(hours=4)}
TOMORROW_HHMM = (8, 0)  # « demain » sans plage de silence : 08:00
USAGE = "usage : ccs silence [1h|4h|demain|off|status]"

# Genres de notification retenue : (clé, singulier, pluriel), dans l'ordre du résumé.
KINDS = (
    ("terminee", "session terminée", "sessions terminées"),
    ("attente", "session en attente de réponse", "sessions en attente de réponse"),
    ("seuil", "alerte de seuil", "alertes de seuil"),
    ("bascule", "bascule automatique", "bascules automatiques"),
    ("reset", "compte de nouveau disponible", "comptes de nouveau disponibles"),
    ("auth", "connexion expirée", "connexions expirées"),
    ("autre", "autre notification", "autres notifications"),
)
_SEUIL = {"eta", "weekly_forecast", "weekly_ahead", "exhausted"}
_PASS = {"blocage", "silence"}  # jamais retenus (voir l'en-tête)


@dataclass
class QuietState:
    source: str                  # "plage" ou "temporaire"
    until: datetime | None       # fin du silence (None : jusqu'à reprise manuelle)
    allow_waiting: bool = True

    def as_dict(self):
        return {"active": True, "until": self.until.isoformat() if self.until else None,
                "source": self.source}


def quiet_path():
    return core.paths().store / "quiet.json"


def held_path():
    return core.paths().store / "quiet_held.json"


@contextmanager
def _locked():
    path = core.paths().store / ".quiet.lock"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(path, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _settings(settings=None):
    if settings is None:
        from .settings import load_settings
        settings = load_settings()
    return settings


def _cfg(settings=None):
    return _settings(settings)["alerts"]["quiet"]


# ---- silence temporaire ------------------------------------------------------

def _dt(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(value)
    return datetime.fromtimestamp(value, timezone.utc)


def _read_temp():
    """(depuis, jusqu'à | None) ou None si absent / illisible."""
    data = core.load_json(quiet_path())
    if "since" not in data:
        return None
    try:
        since = _dt(data["since"])
        until = None if data.get("until") is None else _dt(data["until"])
    except (ValueError, OverflowError, OSError):
        return None
    return since, until


def set_quiet(until, now=None):
    """Silence temporaire jusqu'à `until` (datetime), ou jusqu'à reprise manuelle (None)."""
    now = now or datetime.now(timezone.utc)
    with _locked():
        core.atomic_write_json(quiet_path(), {
            "since": now.timestamp(), "until": until.timestamp() if until else None})
    return until


def clear_quiet():
    with _locked():
        try:
            os.unlink(quiet_path())
        except FileNotFoundError:
            pass


def expire(now):
    """Supprime le fichier d'un silence temporaire échu ; vrai si un silence a été levé."""
    with _locked():
        st = _read_temp()
        if st is None or st[1] is None or st[1] > now:
            return False
        try:
            os.unlink(quiet_path())
        except FileNotFoundError:
            return False
        return True


def _temp_state(now):
    st = _read_temp()
    if st is None or (st[1] is not None and st[1] <= now):
        return None
    return st[1]


# ---- plage de silence --------------------------------------------------------

def _hours(cfg):
    return {"start": cfg["start"], "end": cfg["end"], "days": cfg["days"]}


def plage_end(now, settings=None, tz=None):
    """Fin de la plage de silence qui contient `now`, sinon None (plage éteinte comprise)."""
    cfg = _cfg(settings)
    if not cfg["enabled"]:
        return None
    b = orchestrator.period_bounds(now, _hours(cfg), tz)
    return b[1] if b else None


def quiet_state(now, settings=None, tz=None):
    """Silence en cours à `now` (plage et/ou silence temporaire), sinon None. Plusieurs
    sources : la fin est la plus tardive (le silence ne s'arrête pas au milieu de la plage)."""
    cfg = _cfg(settings)
    found = []
    try:
        if cfg["enabled"]:
            end = plage_end(now, settings, tz)
            if end is not None:
                found.append(("plage", end))
        temp = _read_temp()
        if temp is not None and (temp[1] is None or temp[1] > now):
            found.append(("temporaire", temp[1]))
    except (ValueError, KeyError, TypeError):  # réglages inattendus : pas de silence
        return None
    if not found:
        return None
    source, until = max(found, key=lambda f: datetime.max.replace(tzinfo=timezone.utc)
                        if f[1] is None else f[1])
    return QuietState(source, until, cfg["allow_waiting"])


def state_dict(now, settings=None):
    """Clé `quiet` de state.json : {active, until, source, held} (held : retenues)."""
    st = quiet_state(now, settings)
    out = st.as_dict() if st else {"active": False, "until": None, "source": None}
    out["held"] = sum(held_counts().values())
    return out


def next_wake(now, settings=None):
    """Instant où le service doit se réveiller pour envoyer le résumé : fin du silence en cours."""
    st = quiet_state(now, settings)
    return st.until if st else None


# ---- choix proposés ----------------------------------------------------------

def until_for(choice, now, settings=None, tz=None):
    """Échéance d'un choix : « 1h », « 4h », « demain » (fin de la plage de silence en cours
    ou prochaine ; sans plage : prochain 08:00 local)."""
    if choice in DURATIONS:
        return now + DURATIONS[choice]
    if choice != "demain":
        raise ValueError(f"choix de silence inconnu : {choice}")
    cfg = _cfg(settings)
    tz = tz or orchestrator.local_tz()
    if cfg["enabled"]:
        hours = _hours(cfg)
        end = plage_end(now, settings, tz)
        if end is not None:
            return end
        start = orchestrator.next_period_start(now, hours, tz)
        if start is not None:
            b = orchestrator.period_bounds(start, hours, tz)
            if b:
                return b[1]
    day = now.astimezone(tz).date()
    for ahead in range(3):
        at = orchestrator._at(day + timedelta(days=ahead), TOMORROW_HHMM, tz)
        if at > now:
            return at
    return now + timedelta(hours=24)


def apply(choice, now=None, settings=None):
    """Applique un choix (ou « off » / « reprendre ») ; renvoie la fin posée ou None."""
    now = now or datetime.now(timezone.utc)
    if choice in RESUME:
        clear_quiet()
        return None
    return set_quiet(until_for(choice, now, settings), now)


def label(st, now):
    """« jusqu'à 08:00 », « jusqu'à demain 08:00 », « jusqu'à reprise manuelle »."""
    if st is None:
        return ""
    if st.until is None:
        return "jusqu'à reprise manuelle"
    return pause.label(pause.PauseState(None, st.until), now)


def choices(now, settings=None):
    """[(choix, libellé)] pour un menu de silence."""
    tomorrow = until_for("demain", now, settings)
    return [("1h", "1 heure"), ("4h", "4 heures"),
            ("demain", f"Jusqu'à {pause._when(tomorrow, now)}")]


def command(args, now=None, settings=None):
    """`ccs silence [1h|4h|demain|off|status]` → (code de sortie, texte). Le service doit
    ensuite être réveillé (`daemon.request_refresh`) pour que l'état partagé suive."""
    now = now or datetime.now(timezone.utc)
    args = list(args or [])
    choice = args[0] if args else "status"
    if len(args) > 1:
        return 2, USAGE
    if choice == "status":
        st = quiet_state(now, settings)
        if st is None:
            return 0, "Pas de silence : les notifications arrivent normalement."
        held = sum(held_counts().values())
        origin = "plage de silence" if st.source == "plage" else "silence temporaire"
        extra = f" {held} notification(s) retenue(s)." if held else ""
        return 0, f"Silence ({origin}) {label(st, now)}.{extra}"
    if choice in RESUME:
        was = quiet_state(now, settings)
        clear_quiet()
        still = quiet_state(now, settings)
        if still is not None:
            return 0, (f"Silence temporaire levé ; la plage de silence continue "
                       f"{label(still, now)}.")
        return 0, ("Silence levé : les notifications reprennent." if was else
                   "Pas de silence en cours : les notifications arrivent déjà normalement.")
    if choice not in CHOICES:
        return 2, USAGE
    until = apply(choice, now, settings)
    st = QuietState("temporaire", until)
    return 0, f"Silence {label(st, now)} : les notifications sont retenues puis résumées."


# ---- notifications retenues --------------------------------------------------

def kind(alert):
    """Genre d'une notification, d'après sa clé."""
    prefix = str(alert.key).split(":", 1)[0]
    if prefix in ("attente", "rappel"):
        return "attente"
    if prefix == "session":
        return "terminee"
    if prefix.startswith("session") or prefix in _SEUIL:
        return "seuil"
    if prefix in ("switch", "refus"):
        return "bascule"
    if prefix in ("reset", "auth", "blocage", "silence"):
        return prefix
    return "autre"


def should_hold(alert, now=None, settings=None):
    """Genre à retenir (str) si `alert` doit l'être maintenant, sinon None."""
    now = now or datetime.now(timezone.utc)
    k = kind(alert)
    if k in _PASS:
        return None
    st = quiet_state(now, settings)
    if st is None or (k == "attente" and st.allow_waiting):
        return None
    return k


def held_counts():
    data = core.load_json(held_path()).get("counts")
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items()
            if isinstance(v, int) and not isinstance(v, bool) and v > 0}


def hold(alert, now=None):
    """Compte la notification retenue (par genre) ; renvoie son genre."""
    k = kind(alert)
    with _locked():
        counts = held_counts()
        counts[k] = counts.get(k, 0) + 1
        core.atomic_write_json(held_path(), {"counts": counts})
    return k


def take_held():
    """Retenues comptées jusqu'ici, remises à zéro."""
    with _locked():
        counts = held_counts()
        try:
            os.unlink(held_path())
        except FileNotFoundError:
            pass
    return counts


def summary_text(counts):
    parts = []
    known = {k for k, _s, _p in KINDS}
    for k, one, many in KINDS:
        n = sum(v for key, v in counts.items() if key == k or (k == "autre" and key not in known))
        if n:
            parts.append(f"{n} {one if n == 1 else many}")
    return "Pendant le silence : " + ", ".join(parts) + "." if parts else ""


def summary_alert(counts, now):
    from .alerts import Alert
    body = summary_text(counts)
    if not body:
        return None
    return Alert(f"silence:{now.timestamp():.0f}", "Fin du silence", body, 0)


def flush(now, notifier, settings=None):
    """Silence fini : envoie le résumé unique des notifications retenues. Renvoie l'alerte
    envoyée, ou None (silence encore en cours, ou rien de retenu)."""
    if quiet_state(now, settings) is not None or not held_counts():
        return None
    expire(now)
    alert = summary_alert(take_held(), now)
    if alert is not None:
        notifier(alert)
    return alert
