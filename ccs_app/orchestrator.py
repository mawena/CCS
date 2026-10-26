"""Orchestrateur : enchaîne et décale les fenêtres de 5 h de tous les comptes.

Fonctions pures (`now` toujours passé, heure locale pour la plage active) :
- démarrer chaque compte à son créneau décalé, puis enchaîner ses fenêtres ;
- basculer vers le quota qui va expirer ;
- mettre en réserve un compte en avance sur sa semaine ;
- publier un planning.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from .autoswitch import MANUAL_RESPECT_S, STALE_S, Decision
from .forecast import SESSION_WINDOW, effective_percent, window_open

RETRY = timedelta(minutes=15)
WAKE_MARGIN = timedelta(seconds=30)


def _hhmm(text):
    h, m = (int(x) for x in text.split(":"))
    return h, m


def period_bounds(now, hours):
    """(début, fin) de la période active qui contient `now`, sinon None.

    Une plage dont la fin précède le début passe minuit : 01:30 appartient à
    la période commencée la veille.
    """
    local = now.astimezone()
    sh, sm = _hhmm(hours["start"])
    eh, em = _hhmm(hours["end"])
    days = hours.get("days", range(7))
    for back in (0, 1):
        day = local - timedelta(days=back)
        start = day.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = start.replace(hour=eh, minute=em)
        if end <= start:
            end += timedelta(days=1)
        if start <= local < end and start.weekday() in days:
            return start, end
    return None


def _fresh(a, now):
    return (not a.error and a.limits and a.fetched_at is not None
            and now.timestamp() - a.fetched_at <= STALE_S)


def participants(accounts, now, cfg):
    return sorted(a.name for a in accounts
                  if _fresh(a, now) and a.other_max_effective(now) < cfg["max_weekly_start"])


def first_slots(accounts, now, cfg):
    bounds = period_bounds(now, cfg["active_hours"])
    if bounds is None:
        return {}
    start, end = bounds
    names = participants(accounts, now, cfg)
    step = SESSION_WINDOW / len(names) if names and cfg["stagger"] else timedelta(0)
    slots = {}
    for k, name in enumerate(names):
        slot = start + step * k
        if slot < end:
            slots[name] = slot
    return slots


def starts_due(accounts, now, cfg, store):
    """Comptes au repos dont le créneau est arrivé (une tentative / 15 min)."""
    slots = first_slots(accounts, now, cfg)
    by_name = {a.name: a for a in accounts}
    due = []
    for name, slot in slots.items():
        if now < slot or window_open(by_name[name], now):
            continue
        recent = store.events((now - RETRY).timestamp(), type="warmup", profile=name)
        if any(e.detail.get("mode") == "orchestrateur" for e in recent):
            continue
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
                    active, act_reset.timestamp() if act_reset else None)


@dataclass
class PlanWindow:
    name: str
    start: datetime
    end: datetime
    kind: str  # "current" | "planned"


def plan(accounts, now, cfg):
    bounds = period_bounds(now, cfg["active_hours"])
    slots = first_slots(accounts, now, cfg)
    out = []
    for a in sorted(accounts, key=lambda x: x.name):
        nxt = None
        if window_open(a, now):
            reset = a.session.resets_at
            out.append(PlanWindow(a.name, reset - SESSION_WINDOW, reset, "current"))
            nxt = reset
        elif a.name in slots:
            nxt = max(now, slots[a.name])
        if bounds is None or a.name not in slots or nxt is None:
            continue
        while nxt < bounds[1]:
            out.append(PlanWindow(a.name, nxt, nxt + SESSION_WINDOW, "planned"))
            nxt += SESSION_WINDOW
    return out


def next_wake(accounts, now, cfg):
    """Prochain instant utile : fin d'une fenêtre ou créneau de démarrage (+30 s)."""
    times = []
    for a in accounts:
        if window_open(a, now):
            times.append(a.session.resets_at)
    for name, slot in first_slots(accounts, now, cfg).items():
        if slot > now:
            times.append(slot)
    future = [t for t in times if t > now]
    return min(future) + WAKE_MARGIN if future else None

