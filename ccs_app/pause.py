"""Mode pause : bascule automatique et orchestrateur suspendus jusqu'à une échéance.

L'état vit dans ~/.claude-accounts/pause.json : {"since": ts, "until": ts | null}
(null : jusqu'à reprise manuelle). Le service le relit à chaque relevé et lève
la pause à l'échéance. Les bascules manuelles, alertes et warm-up programmés
continuent pendant une pause.
"""

import fcntl
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import core

# Choix proposés par l'indicateur, l'application et « ccs pause » (libellés : choices()).
DURATIONS = {"1h": timedelta(hours=1), "4h": timedelta(hours=4)}
CHOICES = ("1h", "4h", "demain", "manuel")
RESUME = ("reprendre", "off")


@dataclass
class PauseState:
    since: datetime | None
    until: datetime | None  # None : jusqu'à reprise manuelle

    def as_dict(self, now):
        return {"since": self.since.isoformat() if self.since else None,
                "until": self.until.isoformat() if self.until else None,
                "label": label(self, now)}


def pause_path():
    return core.paths().store / "pause.json"


@contextmanager
def _locked():
    """Une levée automatique ne doit pas effacer une pause posée au même instant."""
    path = core.paths().store / ".pause.lock"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(path, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _dt(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(value)
    return datetime.fromtimestamp(value, timezone.utc)


def _read():
    data = core.load_json(pause_path())
    if "since" not in data:
        return None  # fichier absent, vide ou illisible : pas de pause
    try:
        since = _dt(data["since"])
        until = None if data.get("until") is None else _dt(data["until"])
    except (ValueError, OverflowError, OSError):
        return None
    return PauseState(since, until)


def pause_state(now):
    """Pause en cours à `now`, sinon None (une pause échue ne compte plus)."""
    st = _read()
    if st is None or (st.until is not None and st.until <= now):
        return None
    return st


def set_pause(until, now=None):
    """Met en pause jusqu'à `until` (datetime), ou jusqu'à reprise manuelle (None)."""
    now = now or datetime.now(timezone.utc)
    with _locked():
        core.atomic_write_json(pause_path(), {
            "since": now.timestamp(), "until": until.timestamp() if until else None})
    return PauseState(now, until)


def clear_pause():
    with _locked():
        try:
            os.unlink(pause_path())
        except FileNotFoundError:
            pass


def expire(now):
    """Lève la pause arrivée à échéance ; renvoie la pause levée (pour l'annoncer)."""
    with _locked():
        st = _read()
        if st is None or st.until is None or st.until > now:
            return None
        try:
            os.unlink(pause_path())
        except FileNotFoundError:
            return None
        return st


# --------------------------------------------------------------------------
# Choix proposés à l'utilisateur
# --------------------------------------------------------------------------

def _hours(hours):
    if hours is None:
        from .settings import load_settings
        hours = load_settings()["orchestrator"]["active_hours"]
    return hours


def until_for(choice, now, hours=None, tz=None):
    """Échéance d'un choix : « 1h », « 4h », « demain » (début de la plage horaire
    suivante) ou « manuel » (None : jusqu'à reprise manuelle)."""
    from .orchestrator import next_period_start
    if choice in DURATIONS:
        return now + DURATIONS[choice]
    if choice == "manuel":
        return None
    if choice == "demain":
        hours = _hours(hours)
        start = next_period_start(now, hours, tz)
        if start is None:  # aucun jour actif : lendemain à l'heure de début de plage
            start = next_period_start(now, dict(hours, days=range(7)), tz)
        return start
    raise ValueError(f"choix de pause inconnu : {choice}")


def apply(choice, now=None, hours=None):
    """Applique un choix (ou « reprendre » / « off ») ; renvoie la pause posée ou None."""
    now = now or datetime.now(timezone.utc)
    if choice in RESUME:
        clear_pause()
        return None
    return set_pause(until_for(choice, now, hours), now)


def _when(dt, now):
    local = dt.astimezone()
    days = (local.date() - now.astimezone().date()).days
    if days == 0:
        return f"{local:%H:%M}"
    if days == 1:
        return f"demain {local:%H:%M}"
    return f"au {core.DAYS[local.weekday()]} {local.day} {core.MONTHS[local.month - 1]} à {local:%H:%M}"


def label(st, now):
    """« jusqu'à 14:00 », « jusqu'à demain 08:00 », « jusqu'à reprise manuelle »."""
    if st is None:
        return ""
    if st.until is None:
        return "jusqu'à reprise manuelle"
    when = _when(st.until, now)
    return f"jusqu'{when}" if when.startswith("au ") else f"jusqu'à {when}"


def choices(now, hours=None):
    """[(choix, libellé)] pour un menu de pause."""
    tomorrow = until_for("demain", now, hours)
    return [("1h", "1 heure"), ("4h", "4 heures"),
            ("demain", f"Jusqu'à {_when(tomorrow, now)}" if tomorrow else "Jusqu'à demain"),
            ("manuel", "Jusqu'à reprise manuelle")]


# --------------------------------------------------------------------------
# Commande « ccs pause » (à brancher dans cli.py)
# --------------------------------------------------------------------------

USAGE = "usage : ccs pause [1h|4h|demain|manuel|off|status]"


def command(choice="status", now=None, hours=None):
    """(code de sortie, message) ; le service doit ensuite être réveillé
    (daemon.request_refresh) pour que l'état partagé suive."""
    now = now or datetime.now(timezone.utc)
    if choice in (None, "", "status"):
        st = pause_state(now)
        if st is None:
            return 0, "Pas de pause : bascule automatique et orchestrateur actifs selon les réglages."
        return 0, f"En pause {label(st, now)} : bascule automatique et orchestrateur suspendus."
    if choice in RESUME:
        was = pause_state(now)
        clear_pause()
        return 0, ("Pause levée : la bascule automatique et l'orchestrateur reprennent."
                   if was else "Pas de pause en cours : la bascule automatique et l'orchestrateur "
                               "reprennent déjà selon les réglages.")
    if choice not in CHOICES:
        return 2, USAGE
    st = apply(choice, now, hours)
    return 0, f"Bascule automatique et orchestrateur en pause {label(st, now)}."
