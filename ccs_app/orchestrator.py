"""Orchestrateur : enchaîne et décale les fenêtres de 5 h de tous les comptes.

Fonctions pures (`now` toujours passé, heure locale pour la plage active) :
- démarrer chaque compte à son créneau décalé, puis enchaîner ses fenêtres ;
- basculer vers le quota qui va expirer ;
- mettre en réserve un compte en avance sur sa semaine ;
- publier un planning.
"""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .autoswitch import MANUAL_RESPECT_S, STALE_S, Decision
from .forecast import SESSION_WINDOW, effective_percent, window_open

RETRY = timedelta(minutes=15)
FAILURE_WINDOW = timedelta(hours=3)
FAILURE_LIMIT = 3
BACKOFF = timedelta(hours=1)
WAKE_MARGIN = timedelta(seconds=30)


def _hhmm(text):
    h, m = (int(x) for x in text.split(":"))
    return h, m


@lru_cache(maxsize=2)
def _system_tz(path, mtime):
    with open(path, "rb") as f:
        return ZoneInfo.from_file(f)


def local_tz():
    """Fuseau horaire du poste, avec ses règles de changement d'heure (variable TZ,
    sinon /etc/localtime) ; à défaut, le décalage courant seulement."""
    name = os.environ.get("TZ", "").lstrip(":")
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
    try:
        return _system_tz("/etc/localtime", os.stat("/etc/localtime").st_mtime_ns)
    except (OSError, ValueError):
        return datetime.now().astimezone().tzinfo


def _at(day, hhmm, tz):
    """Instant (UTC) de l'heure locale réelle `hhmm` le jour `day` : une heure qui
    n'existe pas (passage à l'heure d'été) devient la première heure valide, une
    heure doublée (retour à l'heure d'hiver) prend sa première occurrence."""
    h, m = hhmm
    naive = datetime(day.year, day.month, day.day, h, m)
    for _ in range(24 * 60):
        local = naive.replace(tzinfo=tz)  # fold=0 : première occurrence
        utc = local.astimezone(timezone.utc)
        if utc.astimezone(tz).replace(tzinfo=None) == naive:
            return utc
        naive += timedelta(minutes=1)  # heure inexistante : on avance jusqu'à la première valide
    return local.astimezone(timezone.utc)


def _period(day, hours, tz):
    """(début, fin) en UTC de la période commencée le jour local `day`."""
    start = _at(day, _hhmm(hours["start"]), tz)
    end_day = day
    if _hhmm(hours["end"]) <= _hhmm(hours["start"]):
        end_day = day + timedelta(days=1)
    return start, _at(end_day, _hhmm(hours["end"]), tz)


def period_bounds(now, hours, tz=None):
    """(début, fin) de la période active qui contient `now`, sinon None (en UTC).

    Une plage dont la fin précède le début passe minuit : 01:30 appartient à
    la période commencée la veille. Bornes en heure locale réelle de `tz`
    (par défaut celle du poste), changements d'heure compris.
    """
    tz = tz or local_tz()
    today = now.astimezone(tz).date()
    days = hours.get("days", range(7))
    for back in (0, 1):
        day = today - timedelta(days=back)
        start, end = _period(day, hours, tz)
        if start <= now < end and day.weekday() in days:
            return start, end
    return None


def next_period_start(now, hours, tz=None):
    """Début de la prochaine période active strictement après `now` (None si aucun jour actif)."""
    tz = tz or local_tz()
    today = now.astimezone(tz).date()
    days = hours.get("days", range(7))
    for ahead in range(9):
        day = today + timedelta(days=ahead)
        start = _at(day, _hhmm(hours["start"]), tz)
        if start > now and day.weekday() in days:
            return start
    return None


def next_edge(now, hours, tz=None):
    """Prochaine borne de plage après `now` : fin de la période en cours, sinon
    début de la prochaine (None si aucun jour actif)."""
    bounds = period_bounds(now, hours, tz)
    if bounds is not None:
        return bounds[1]
    return next_period_start(now, hours, tz)


def _fresh(a, now):
    return (not a.blocking_error and a.limits and a.fetched_at is not None
            and now.timestamp() - a.fetched_at <= STALE_S)


def participants(accounts, now, cfg):
    return sorted(a.name for a in accounts
                  if _fresh(a, now) and a.other_max_effective(now) < cfg["max_weekly_start"])


def first_slots(accounts, now, cfg):
    bounds = period_bounds(now, cfg["active_hours"])
    if bounds is None:
        return {}
    start, end = bounds
    by_name = {a.name: a for a in accounts}

    def rank(name):
        # Fenêtres déjà ouvertes dans la période d'abord (dans leur ordre
        # d'ouverture), puis le compte actif, puis les autres : le décalage
        # s'aligne sur ce que l'utilisateur a réellement démarré.
        a = by_name[name]
        if window_open(a, now) and a.session.resets_at - SESSION_WINDOW >= start:
            return (0, (a.session.resets_at - SESSION_WINDOW).timestamp(), name)
        return (1 if a.active else 2, 0, name)
    names = sorted(participants(accounts, now, cfg), key=rank)
    step = SESSION_WINDOW / len(names) if names and cfg["stagger"] else timedelta(0)
    # Une fenêtre encore ouverte, démarrée avant le début de la plage (tôt le
    # matin par l'utilisateur), sert de point de départ : les créneaux se calent
    # sur ce démarrage réel et non sur le début de plage.
    opened = [by_name[n].session.resets_at - SESSION_WINDOW
              for n in names if window_open(by_name[n], now)]
    anchor = min([start] + opened)
    slots = {}
    for k, name in enumerate(names):
        slot = anchor + step * k
        if slot < end:
            slots[name] = slot
    return slots


def starts_due(accounts, now, cfg, store):
    """Comptes au repos dont le créneau est arrivé (une tentative / 15 min)."""
    first, _ = _schedule(accounts, now, cfg)
    by_name = {a.name: a for a in accounts}
    due = []
    for name, start in first.items():
        if start > now or window_open(by_name[name], now):
            continue
        history = store.events((now - SESSION_WINDOW).timestamp(), type="warmup", profile=name)
        if any(e.ts >= (now - RETRY).timestamp() for e in history):
            continue  # tentative récente (quel que soit le mode), l'API ne la reflète pas encore
        mine = [e for e in history if e.detail.get("mode") == "orchestrateur"]
        if any(e.detail.get("ok") is True for e in mine):
            continue  # fenêtre démarrée il y a moins de 5 h : on attend sa fin
        failures = [e for e in mine if e.detail.get("ok") is False
                    and e.ts >= (now - FAILURE_WINDOW).timestamp()]
        if len(failures) >= FAILURE_LIMIT and failures[-1].ts >= (now - BACKOFF).timestamp():
            continue  # échecs répétés : une tentative par heure seulement
        due.append(name)
    return due


def reserve_set(accounts, paces, cfg):
    """Comptes en avance de plus de `reserve_points` sur le rythme de la semaine."""
    out = set()
    for a in accounts:
        pace = paces.get(a.name)
        if pace is not None and pace.margin < -cfg["reserve_points"]:
            out.add(a.name)
    return out


def expiring_decision(accounts, active, now, cfg, events, reserve=frozenset()):
    """Bascule anticipée vers un compte qui va perdre une part importante de son quota."""
    if not cfg["expiring_switch"] or active is None:
        return None
    if period_bounds(now, cfg["active_hours"]) is None:
        return None  # rien en dehors de la plage horaire
    act = next((a for a in accounts if a.name == active), None)
    if act is None or not _fresh(act, now):
        return None
    ts = now.timestamp()
    switches = [e for e in events if e.type == "switch"]
    automatic = [e for e in switches if e.detail.get("mode") in ("auto", "anticipee")]
    if automatic and ts - automatic[-1].ts < cfg["expiring_cooldown_min"] * 60:
        return None
    last = switches[-1] if switches else None
    if last and last.detail.get("mode") == "manual" and ts - last.ts < MANUAL_RESPECT_S:
        return None
    act_reset = act.session.resets_at if window_open(act, now) else None
    best = None
    for a in accounts:
        if a.name == active or a.name in reserve or not _fresh(a, now) or not window_open(a, now):
            continue
        reset = a.session.resets_at
        left = 100 - effective_percent(a.session, now)
        if (reset - now > timedelta(minutes=cfg["expiring_within_min"])
                or left < cfg["expiring_min_left"]
                or a.other_max_effective(now) >= cfg["max_weekly_start"]
                or (act_reset is not None and act_reset <= reset)):
            continue
        if best is None or reset < best[1]:
            best = (a, reset, left)
    if best is None:
        return None
    a, reset, left = best
    minutes = max(1, round((reset - now).total_seconds() / 60))
    return Decision("switch", a.name,
                    f"{a.name} va perdre {left:.0f} % de quota dans {minutes} min",
                    active, act_reset.timestamp() if act_reset else None,
                    {"lost": round(left, 1), "minutes": minutes, "expiring": a.name})


@dataclass
class PlanWindow:
    name: str
    start: datetime
    end: datetime
    kind: str  # "current" | "planned"


def _schedule(accounts, now, cfg):
    """Calendrier simulé de la période : ({compte: prochain démarrage}, fenêtres).

    Un démarrage n'a lieu que si aucune fenêtre d'un autre compte participant
    n'a démarré depuis moins de 5 h ÷ N : le décalage se rétablit à partir des
    démarrages réels (y compris ceux de l'utilisateur), pas d'une grille fixe.
    """
    current = []
    for a in sorted(accounts, key=lambda x: x.name):
        if window_open(a, now):
            reset = a.session.resets_at
            current.append(PlanWindow(a.name, reset - SESSION_WINDOW, reset, "current"))
    bounds = period_bounds(now, cfg["active_hours"])
    if bounds is None:
        return {}, current
    end = bounds[1]
    slots = first_slots(accounts, now, cfg)
    order = list(slots)
    step = SESSION_WINDOW / len(order) if order and cfg["stagger"] else timedelta(0)
    # Fenêtres connues de tous les comptes encore utilisables cette semaine, même
    # si leur dernier relevé a échoué : elles comptent pour l'écart.
    weekly_ok = {a.name for a in accounts
                 if a.other_max_effective(now) < cfg["max_weekly_start"]}
    starts = [w.start for w in current if w.name in weekly_ok]
    cand = {}
    for name in order:
        own = next((w for w in current if w.name == name), None)
        cand[name] = own.end if own else max(now, slots[name])
    first, planned = {}, []
    for _ in range(200):
        if not cand:
            break
        name = min(cand, key=lambda n: (cand[n], order.index(n)))
        t = cand[name]
        if t >= end:
            del cand[name]
            continue
        need = max((st + step for st in starts if st > t - step and st <= t), default=t)
        if need > t:
            cand[name] = need
            continue
        first.setdefault(name, t)
        planned.append(PlanWindow(name, t, t + SESSION_WINDOW, "planned"))
        starts.append(t)
        cand[name] = t + SESSION_WINDOW
    return first, sorted(current + planned, key=lambda w: (w.name, w.start))


def plan(accounts, now, cfg):
    return _schedule(accounts, now, cfg)[1]


def next_wake(accounts, now, cfg):
    """Prochain instant utile : fin d'une fenêtre ou démarrage prévu (+30 s)."""
    first, _ = _schedule(accounts, now, cfg)
    times = [a.session.resets_at for a in accounts if window_open(a, now)]
    times += list(first.values())
    future = [t for t in times if t > now]
    return min(future) + WAKE_MARGIN if future else None
