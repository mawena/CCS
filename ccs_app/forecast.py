"""Prévisions et recommandations (fonctions pures : `now` est toujours passé)."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import core

SESSION_WINDOW = timedelta(hours=5)
WEEK = timedelta(days=7)
TREND_WINDOW = timedelta(minutes=45)
MIN_TREND_SPAN_S = 10 * 60
STABLE_RATE = 0.01  # %/min
TRANSIENT_ERRORS = ("HTTP 429", "HTTP 5", "réseau")


@dataclass
class AccountState:
    name: str
    active: bool
    limits: list
    fetched_at: float | None
    error: str | None

    def _kind(self, kind):
        return next((lim for lim in self.limits if lim.kind == kind), None)

    @property
    def session(self):
        return self._kind("session")

    @property
    def weekly(self):
        return self._kind("weekly_all")

    @property
    def blocking_error(self):
        """Erreur qui rend le compte inutilisable (connexion révoquée…), par opposition
        aux erreurs passagères (429, 5xx, réseau) où les dernières données restent
        valables selon leur âge."""
        if not self.error or self.error.startswith(TRANSIENT_ERRORS):
            return None
        return self.error

    @property
    def max_percent(self):
        return max((lim.percent for lim in self.limits), default=0.0)

    def max_effective(self, now):
        return max((effective_percent(lim, now) for lim in self.limits), default=0.0)

    def other_max_effective(self, now):
        """Plus haut pourcentage parmi les limites autres que la session."""
        return max((effective_percent(lim, now) for lim in self.limits if lim.kind != "session"),
                   default=0.0)


def effective_percent(limit, now):
    """Pourcentage tenant compte d'une réinitialisation déjà passée."""
    if limit is None:
        return 0.0
    if limit.resets_at is not None and limit.resets_at <= now:
        return 0.0
    return limit.percent


# --------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------

@dataclass
class SessionForecast:
    rate_per_min: float | None
    eta: datetime | None
    verdict: str  # "limit" | "ok" | "stable" | "unknown"
    minutes_before_reset: float | None


def _slope(points):
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    den = sum((x - mx) ** 2 for x, _ in points)
    return sum((x - mx) * (y - my) for x, y in points) / den if den else 0.0


def session_forecast(samples, limit, now):
    unknown = SessionForecast(None, None, "unknown", None)
    if limit is None:
        return unknown
    start = now - TREND_WINDOW
    if limit.resets_at is not None:
        start = max(start, limit.resets_at - SESSION_WINDOW)
    t0 = start.timestamp()
    points = [(ts, pct) for ts, pct in samples if ts >= t0 and ts <= now.timestamp()]
    if len(points) < 2 or points[-1][0] - points[0][0] < MIN_TREND_SPAN_S:
        return unknown
    rate = _slope([(ts / 60, pct) for ts, pct in points])
    if rate <= STABLE_RATE:
        return SessionForecast(rate, None, "stable", None)
    remaining = max(0.0, 100.0 - effective_percent(limit, now))
    eta = now + timedelta(minutes=remaining / rate)
    if limit.resets_at is not None and limit.resets_at <= eta:
        return SessionForecast(rate, eta, "ok", None)
    before = (limit.resets_at - eta).total_seconds() / 60 if limit.resets_at else None
    return SessionForecast(rate, eta, "limit", before)


# --------------------------------------------------------------------------
# Semaine
# --------------------------------------------------------------------------

@dataclass
class WeeklyPace:
    elapsed_frac: float
    ideal: float
    margin: float
    per_day_budget: float
    days_left: float


def weekly_pace(limit, now):
    if limit is None or limit.resets_at is None or limit.resets_at <= now:
        return None
    left = limit.resets_at - now
    days_left = left.total_seconds() / 86400
    elapsed = min(1.0, max(0.0, 1 - left / WEEK))
    ideal = 100 * elapsed
    return WeeklyPace(elapsed, ideal, ideal - limit.percent,
                      max(0.0, 100 - limit.percent) / days_left, days_left)


# En tout début de semaine, le rythme moyen n'a pas de sens (une heure de
# travail suffirait à « prévoir » l'épuisement) : pas de prévision avant 12 h.
WEEKLY_MIN_ELAPSED_DAYS = 0.5


@dataclass
class WeeklyForecast:
    rate_per_day: float | None       # rythme moyen depuis le début de la semaine (%/jour)
    eta: datetime | None             # 100 % atteint à ce rythme
    verdict: str                     # "limit" (avant la réinitialisation) | "ok" | "unknown"
    days_before_reset: float | None  # avance de l'épuisement sur la réinitialisation

    def as_dict(self):
        return {"verdict": self.verdict, "eta": self.eta.isoformat() if self.eta else None,
                "rate_per_day": self.rate_per_day, "days_before_reset": self.days_before_reset}


def weekly_forecast(limit, now):
    """Date où la limite hebdomadaire sera atteinte au rythme moyen de la semaine."""
    pace = weekly_pace(limit, now)
    if pace is None:
        return None
    elapsed_days = max(0.0, (WEEK - (limit.resets_at - now)).total_seconds() / 86400)
    used = limit.percent
    rate = used / elapsed_days if elapsed_days > 0 else None
    if used >= 100:
        return WeeklyForecast(rate, now, "limit", pace.days_left)
    if elapsed_days < WEEKLY_MIN_ELAPSED_DAYS:
        return WeeklyForecast(None, None, "unknown", None)
    if rate <= 0:
        return WeeklyForecast(0.0, None, "ok", None)
    eta = now + timedelta(days=(100 - used) / rate)
    if eta >= limit.resets_at:
        return WeeklyForecast(rate, eta, "ok", None)
    return WeeklyForecast(rate, eta, "limit", (limit.resets_at - eta).total_seconds() / 86400)


def fmt_when(dt, now):
    """« aujourd'hui à 14:00 », « demain à 09:30 », « jeu. 12 nov. à 18:00 »."""
    local = dt.astimezone()
    days = (local.date() - now.astimezone().date()).days
    if days == 0:
        day = "aujourd'hui"
    elif days == 1:
        day = "demain"
    else:
        day = f"{core.DAYS[local.weekday()]} {local.day} {core.MONTHS[local.month - 1]}"
    return f"{day} à {local:%H:%M}"


def fmt_days(days):
    if days >= 1:
        return f"{core.fr(days)} j"
    hours = round(days * 24)
    return f"{hours} h" if hours >= 1 else "moins d'une heure"


def weekly_forecast_text(wf, now):
    """Texte de la prévision de fin de semaine (forme de state.json), ou None."""
    if not wf or wf.get("verdict") not in ("limit", "ok"):
        return None
    rate = wf.get("rate_per_day")
    pace = f" ({rate:.0f} %/jour)" if rate else ""
    if wf["verdict"] == "ok":
        return f"✓ Semaine : tient jusqu'à la réinitialisation au rythme actuel{pace}"
    eta = core.parse_dt(wf.get("eta"))
    if eta is None:
        return None
    if eta <= now:
        return "⚠ Semaine : limite atteinte"
    before = wf.get("days_before_reset")
    tail = f", {fmt_days(before)} avant la réinitialisation" if before else ""
    return f"⚠ Semaine : limite prévue {fmt_when(eta, now)} au rythme actuel{pace}{tail}"


# --------------------------------------------------------------------------
# Capacité et meilleur compte
# --------------------------------------------------------------------------

def _has_data(a):
    return bool(a.limits)


def capacity(accounts, now):
    """Capacité restante tous comptes confondus, en « sessions complètes »."""
    total = 0.0
    for a in accounts:
        if not _has_data(a):
            continue
        s = effective_percent(a.session, now)
        w = a.other_max_effective(now)
        total += min(100 - s, 100 - w) / 100
    return total


@dataclass
class Recommendation:
    name: str
    reason: str


def window_open(a, now):
    """Fenêtre de 5 h en cours : une heure de fin à venir, même à 0 % (l'API
    renvoie 0 % juste après un démarrage par requête minimale)."""
    s = a.session
    return s is not None and s.resets_at is not None and s.resets_at > now


def best_account(accounts, now, exclude=frozenset(), max_session=90, max_weekly=95,
                 reserve=frozenset()):
    """Meilleur compte ; ceux en réserve (semaine en avance) ne servent qu'en dernier."""
    if reserve:
        others = [a for a in accounts if a.name not in reserve]
        rec = best_account(others, now, exclude, max_session, max_weekly)
        if rec:
            return rec
        return best_account([a for a in accounts if a.name in reserve], now, exclude,
                            max_session, max_weekly)
    open_, idle = [], []
    for a in accounts:
        if a.name in exclude or not _has_data(a):
            continue
        s = effective_percent(a.session, now)
        w = a.other_max_effective(now)
        if s >= max_session or w >= max_weekly:
            continue
        (open_ if window_open(a, now) else idle).append((a, s, w))
    if open_:
        a, s, _ = min(open_, key=lambda x: x[0].session.resets_at)
        lost = core.fmt_reset(a.session.resets_at, now).replace("réinitialisation", "perdus")
        return Recommendation(a.name, f"fenêtre ouverte, {100 - s:.0f} % restants, {lost}")
    if idle:
        a, _, w = min(idle, key=lambda x: x[2])
        return Recommendation(a.name, f"au repos, semaine à {w:.0f} %")
    return None
