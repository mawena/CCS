"""Bilan de la semaine : usage des comptes, activité, coût, modèles, projets, bascules.

La semaine du bilan commence quand la plupart des comptes ont commencé leur nouvelle
semaine (heures de réinitialisation hebdomadaires lues dans les relevés), ou à un jour
et une heure fixes (`alerts.weekly_report_day`, 0 = lundi, et `alerts.weekly_report_hour`).
Une notification de synthèse part une fois par semaine, au plus tard deux jours après
ce début (`pending_alert`, appelé par `alerts.pending_alerts`) ; le bilan est calculé
dans un fil, jamais pendant le relevé lui-même.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from . import core, costs, transcripts
from .advisor import SESSION_S, increments, windows
from .alerts import Alert

log = logging.getLogger("ccs.weekly_report")

WEEK = timedelta(days=7)
CLUSTER = timedelta(days=3)        # réinitialisations assez proches pour un même début de semaine
DUE_FOR = timedelta(days=2)        # bilan envoyé au plus tard deux jours après le début de semaine
DEDUP_DAYS = 5                     # un bilan déjà envoyé à moins de 5 jours : pas de second
MIN_DATA = timedelta(days=3)       # relevés couvrant au moins 3 jours de la semaine écoulée
RETRY_AFTER_S = 3600               # nouvel essai une heure après un calcul en échec
SESSION_GAP_S = 30 * 60            # une reprise après 30 min d'inactivité : nouvelle session
DEFAULT_DAY, DEFAULT_HOUR = 0, 9   # sans heure de réinitialisation connue : lundi 9:00
KEY_PREFIX = "weekly_report:"

SWITCH_MODES = (("auto", "automatique"), ("anticipee", "anticipée"), ("manual", "manuelle"),
                ("blocage", "après blocage"))
ALERT_LABELS = {
    "eta": "limite bientôt atteinte", "reset": "compte de nouveau disponible",
    "weekly_ahead": "semaine en avance", "weekly_forecast": "fin de semaine prévue",
    "auth": "connexion expirée", "exhausted": "comptes épuisés", "switch": "bascule automatique",
    "model_advice": "conseil de modèle", "pause_end": "fin de pause", "refus": "bascule refusée",
}


# --------------------------------------------------------------------------
# Début de semaine
# --------------------------------------------------------------------------

def _fixed_anchor(now, day, hour):
    """Dernier `day` (0 = lundi) à `hour` heures, heure locale, au plus tard `now`."""
    local = now.astimezone()
    d = local.date() - timedelta(days=(local.weekday() - day) % 7)
    for _ in range(2):
        cand = datetime(d.year, d.month, d.day, hour).astimezone()
        if cand <= now:
            return cand
        d -= timedelta(days=7)
    return cand


def _majority_anchor(accounts, now):
    """Début de semaine de la plupart des comptes (heure de la semaine stable), ou None."""
    week_s = WEEK.total_seconds()
    now_ts = now.timestamp()
    phases = [(a.weekly.resets_at.timestamp() - week_s) % week_s for a in accounts
              if a.weekly is not None and a.weekly.resets_at is not None and a.weekly.resets_at > now]
    if not phases:
        return None
    need = len(phases) // 2 + 1
    best = None
    for c in phases:
        cluster = sorted((d for d in ((c - p) % week_s for p in phases)
                          if d <= CLUSTER.total_seconds()), reverse=True)
        # Moment où la majorité a commencé sa semaine (dans ce groupe de réinitialisations).
        moment = (c - cluster[need - 1]) % week_s if len(cluster) >= need else c
        score = (len(cluster), -cluster[0], -moment)
        if best is None or score > best[0]:
            best = (score, moment)
    moment = best[1]
    return datetime.fromtimestamp(now_ts - (now_ts - moment) % week_s, timezone.utc).astimezone()


def week_anchor(accounts, now, settings):
    """Début de la semaine en cours (fin de la semaine écoulée)."""
    cfg = settings["alerts"]
    day, hour = cfg.get("weekly_report_day"), cfg.get("weekly_report_hour", DEFAULT_HOUR)
    if not isinstance(hour, int) or not 0 <= hour <= 23:
        hour = DEFAULT_HOUR
    if isinstance(day, int) and 0 <= day <= 6:
        return _fixed_anchor(now, day, hour)
    return _majority_anchor(accounts, now) or _fixed_anchor(now, DEFAULT_DAY, hour)


def week_choices(accounts, now, settings, count=6):
    """[(début, fin)] : la semaine en cours puis les `count` précédentes."""
    anchor = week_anchor(accounts, now, settings)
    return [(anchor, now)] + [(anchor - (i + 1) * WEEK, anchor - i * WEEK) for i in range(count)]


def report_key(anchor):
    return f"{KEY_PREFIX}{anchor.astimezone().date().isoformat()}"


def _already_sent(anchor, sent_keys):
    day = anchor.astimezone().date()
    for key in sent_keys:
        if not str(key).startswith(KEY_PREFIX):
            continue
        try:
            sent = date.fromisoformat(str(key)[len(KEY_PREFIX):])
        except ValueError:
            continue
        if abs((day - sent).days) <= DEDUP_DAYS:
            return True
    return False


# --------------------------------------------------------------------------
# Bilan
# --------------------------------------------------------------------------

@dataclass
class AccountWeek:
    name: str
    weekly_peak: float | None = None   # plus haut % hebdomadaire relevé dans la semaine
    weekly_used: float = 0.0           # points de % consommés dans la semaine
    windows: int = 0                   # fenêtres de 5 h entamées
    session_hits: int = 0              # fenêtres de 5 h menées jusqu'à la limite
    switches_to: int = 0               # bascules vers ce compte


@dataclass
class WeekReport:
    start: datetime
    end: datetime
    accounts: list = field(default_factory=list)
    conversations: int = 0
    sessions: int = 0
    cost: costs.Cost = field(default_factory=costs.Cost.empty)
    by_model: dict = field(default_factory=dict)     # famille -> tokens pondérés
    by_project: dict = field(default_factory=dict)   # projet -> tokens pondérés
    switches: int = 0
    switches_by_mode: dict = field(default_factory=dict)
    alerts: int = 0
    alerts_by_kind: dict = field(default_factory=dict)
    blocages: int = 0
    previous: "WeekReport | None" = None

    def account(self, name):
        return next((a for a in self.accounts if a.name == name), None)

    @property
    def windows(self):
        return sum(a.windows for a in self.accounts)

    @property
    def empty(self):
        return not self.cost.reponses and not self.switches and not any(
            a.weekly_peak for a in self.accounts)


def _account_week(name, kinds, s, e, switches_to):
    acc = AccountWeek(name, switches_to=switches_to)
    weekly = kinds.get("weekly_all") or []
    inside = [pct for ts, pct, _r in weekly if s <= ts < e]
    acc.weekly_peak = max(inside) if inside else None
    acc.weekly_used = sum(d for ts, d in increments(weekly) if s <= ts < e)
    sessions = [row for row in kinds.get("session") or [] if s <= row[0] < e]
    for w in windows(sessions, SESSION_S, e):
        if w.usage >= 1:
            acc.windows += 1
        if w.hit_at is not None:
            acc.session_hits += 1
    return acc


def _sessions(timestamps):
    ts = sorted(timestamps)
    return sum(1 for i, t in enumerate(ts) if i == 0 or t - ts[i - 1] > SESSION_GAP_S)


def aggregate(start, end, samples, events, answers_by_file, projects_dir):
    """Bilan (pur) de [start, end) : relevés {profil: {genre: [(ts, %, reset)]}}, événements
    du store, réponses {chemin du journal: [costs.Answer]}."""
    s, e = start.timestamp(), end.timestamp()
    r = WeekReport(start, end)
    switches = [ev for ev in events if ev.type == "switch" and s <= ev.ts < e
                and (ev.detail or {}).get("mode") != "initial"]
    r.switches = len(switches)
    for ev in switches:
        mode = (ev.detail or {}).get("mode") or "manual"
        r.switches_by_mode[mode] = r.switches_by_mode.get(mode, 0) + 1
    for ev in events:
        if ev.type != "alert" or not s <= ev.ts < e:
            continue
        key = str((ev.detail or {}).get("key") or "")
        if ev.profile == "blocage":
            r.blocages += key.startswith("blocage:")
            continue
        kind = key.split(":", 1)[0]
        if not kind or key.startswith(KEY_PREFIX):
            continue
        r.alerts += 1
        r.alerts_by_kind[kind] = r.alerts_by_kind.get(kind, 0) + 1
    for name, kinds in samples.items():
        r.accounts.append(_account_week(name, kinds, s, e,
                                        sum(1 for ev in switches if ev.profile == name)))
    every = []
    for path, answers in answers_by_file.items():
        answers = [a for a in answers if s <= a.ts < e]
        if not answers:
            continue
        every += answers
        if path.parent.name != "subagents":
            r.conversations += 1
            r.sessions += _sessions(a.ts for a in answers)
        for a in answers:
            w = transcripts.weighted_tokens(a.tokens)
            fam = transcripts.model_family(a.model)
            r.by_model[fam] = r.by_model.get(fam, 0) + w
            proj = transcripts.project_label(a.cwd, path, projects_dir)
            r.by_project[proj] = r.by_project.get(proj, 0) + w
    r.cost = costs.cost_of(every)
    return r


# --------------------------------------------------------------------------
# Textes
# --------------------------------------------------------------------------

def _date(dt):
    local = dt.astimezone()
    return f"{local.day} {core.MONTHS[local.month - 1]}"


def _plural(n, word, plural=None):
    return f"{n:,}".replace(",", " ") + f" {word if n == 1 else plural or word + 's'}"


def fmt_tokens(n):
    """Comme `transcripts.fmt_tokens`, avec les milliards (« 2,4 Md »)."""
    return f"{core.fr(n / 1e9)} Md" if n >= 1e9 else transcripts.fmt_tokens(n)


def _shares(data, limit):
    total = sum(data.values())
    if total <= 0:
        return []
    rows = sorted(data.items(), key=lambda kv: -kv[1])[:limit]
    return [(name, 100 * v / total) for name, v in rows]


def _alert_label(kind):
    if kind.startswith("session") and kind[len("session"):].isdigit():
        return f"session à {kind[len('session'):]} %"
    return ALERT_LABELS.get(kind, kind)


def _delta(cur, prev, percent=True):
    if prev is None:
        return ""
    if percent:
        if not prev:
            return " (nouveau)" if cur else ""
        change = 100 * (cur - prev) / prev
        return " (=)" if abs(change) < 0.5 else f" ({change:+.0f} %)"
    diff = cur - prev
    return " (=)" if not diff else f" ({diff:+d})"


def _dollars(cost):
    if cost.inconnu and not cost.dollars:
        return "tarif inconnu"
    sign = "≥" if cost.inconnu else "≈"
    return f"{sign} {costs.format_dollars(cost.dollars)}"


def title(report):
    return f"Bilan de la semaine du {_date(report.start)} au {_date(report.end)}"


def sections(report):
    """[(titre, [lignes])] du bilan, pour `format_text` et l'application."""
    out = []
    accounts = []
    for a in report.accounts:
        if a.weekly_peak is None and not a.windows and not a.switches_to:
            accounts.append(f"{a.name} : aucun relevé cette semaine")
            continue
        parts = []
        if a.weekly_peak is not None:
            parts.append(f"semaine à {a.weekly_peak:.0f} % au plus ({a.weekly_used:.0f} points consommés)")
        parts.append(_plural(a.windows, "fenêtre de 5 h", "fenêtres de 5 h"))
        if a.session_hits:
            parts.append(_plural(a.session_hits, "limite de session atteinte",
                                 "limites de session atteintes"))
        if a.switches_to:
            parts.append(_plural(a.switches_to, "bascule vers ce compte", "bascules vers ce compte"))
        accounts.append(f"{a.name} : " + ", ".join(parts))
    if accounts:
        out.append(("Comptes", accounts))
    c = report.cost
    if not c.reponses:
        out.append(("Activité", ["Aucune activité de Claude Code enregistrée sur ce PC."]))
    else:
        out.append(("Activité", [
            f"{_plural(report.conversations, 'conversation')}, {_plural(report.sessions, 'session')}, "
            f"{_plural(c.reponses, 'réponse')}",
            f"{fmt_tokens(c.total_tokens)} tokens · {_dollars(c)} au tarif de l'API"]))
        out.append(("Modèles", [" · ".join(f"{name.capitalize()} {pct:.0f} %"
                                           for name, pct in _shares(report.by_model, 5))]))
        out.append(("Projets", [" · ".join(f"{name} {pct:.0f} %"
                                           for name, pct in _shares(report.by_project, 5))]))
    events = []
    if report.switches:
        modes = [(report.switches_by_mode.get(k, 0), label) for k, label in SWITCH_MODES]
        modes += [(n, k) for k, n in report.switches_by_mode.items() if k not in dict(SWITCH_MODES)]
        detail = ", ".join(f"{n} {label if n == 1 or label == 'après blocage' else label + 's'}"
                           for n, label in modes if n)
        events.append(f"{_plural(report.switches, 'bascule')} ({detail})")
    else:
        events.append("Aucune bascule")
    if report.alerts:
        kinds = sorted(report.alerts_by_kind.items(), key=lambda kv: (-kv[1], kv[0]))
        detail = ", ".join(f"{n} {_alert_label(k)}" for k, n in kinds)
        events.append(f"{_plural(report.alerts, 'alerte')} ({detail})")
    if report.blocages:
        events.append(_plural(report.blocages, "blocage") + " sur une limite pendant une session")
    out.append(("Bascules et alertes", events))
    prev = report.previous
    if prev is not None:
        lines = [
            f"tokens : {fmt_tokens(c.total_tokens)}"
            f"{_delta(c.total_tokens, prev.cost.total_tokens)}",
            f"équivalent API : {_dollars(c)}{_delta(c.dollars, prev.cost.dollars)}",
            f"conversations : {report.conversations}{_delta(report.conversations, prev.conversations, False)}",
            f"fenêtres de 5 h : {report.windows}{_delta(report.windows, prev.windows, False)}",
            f"bascules : {report.switches}{_delta(report.switches, prev.switches, False)}",
        ]
        for a in report.accounts:
            before = prev.account(a.name)
            if a.weekly_peak is not None and before is not None and before.weekly_peak is not None:
                lines.append(f"{a.name} : semaine à {a.weekly_peak:.0f} % "
                             f"({a.weekly_peak - before.weekly_peak:+.0f} points)")
        out.append(("Par rapport à la semaine précédente", lines))
    return out


def format_text(report):
    """Texte de `ccs semaine`."""
    lines = [title(report)]
    for head, rows in sections(report):
        lines += ["", head] + [f"• {row}" for row in rows]
    return "\n".join(lines)


def notification(report, key):
    """Notification de synthèse (courte)."""
    period = f"Du {_date(report.start)} au {_date(report.end)}"
    c = report.cost
    if not c.reponses:
        body = f"{period} : aucune activité de Claude Code enregistrée sur ce PC."
    else:
        prev = report.previous
        delta = _delta(c.dollars, prev.cost.dollars) if prev is not None else ""
        body = (f"{period} : {fmt_tokens(c.total_tokens)} tokens "
                f"({_dollars(c)} à l'API{delta.replace(' (', ', ').rstrip(')')}), "
                f"{_plural(report.conversations, 'conversation')}, "
                f"{_plural(report.windows, 'fenêtre de 5 h', 'fenêtres de 5 h')}, "
                f"{_plural(report.switches, 'bascule')}.")
    peaks = [f"{a.name} {a.weekly_peak:.0f} %" for a in report.accounts if a.weekly_peak is not None]
    if peaks:
        body += " Semaine : " + ", ".join(peaks) + "."
    top = _shares(report.by_project, 1)
    if top:
        body += f" Projet principal : {top[0][0]} ({top[0][1]:.0f} %)."
    return Alert(key, "Bilan de la semaine", body, 0)


# --------------------------------------------------------------------------
# Chargement
# --------------------------------------------------------------------------

def _history_exists():
    return (core.paths().store / "history.db").exists()


def has_data(start, end, store=None, profiles=None):
    """Relevés couvrant au moins 3 jours de [start, end) (sans créer d'historique)."""
    from .store import Store
    if store is None and not _history_exists():
        return False
    own = store is None
    store = store or Store()
    try:
        names = [p.name for p in (core.list_profiles() if profiles is None else profiles)]
        limit = (end - MIN_DATA).timestamp()
        for name in names:
            rows = store.samples(name, "weekly_all", start.timestamp())
            if rows and rows[0][0] <= limit and rows[0][0] < end.timestamp():
                return True
        return False
    finally:
        if own:
            store.close()


def build_report(start, end, store=None, projects_dir=None, profiles=None, previous=True):
    """Bilan de [start, end) d'après le store et les journaux, avec la semaine précédente."""
    from .store import Store
    own = store is None
    store = store or Store()
    try:
        profiles = core.list_profiles() if profiles is None else profiles
        since = (start - timedelta(days=1)).timestamp()   # point de départ des hausses
        samples = {p.name: {k: [row for row in store.samples(p.name, k, since)
                                if row[0] < end.timestamp()]
                            for k in ("session", "weekly_all")} for p in profiles}
        events = store.events(start.timestamp())
        projects_dir = projects_dir or core.paths().config_dir / "projects"
        answers = costs.period_answers(projects_dir, start.timestamp(), end.timestamp())
        report = aggregate(start, end, samples, events, answers, projects_dir)
        if previous:
            report.previous = build_report(start - WEEK, start, store, projects_dir, profiles, False)
        return report
    finally:
        if own:
            store.close()


# --------------------------------------------------------------------------
# Notification hebdomadaire (appelée à chaque relevé du service)
# --------------------------------------------------------------------------

_RUNNING = object()
_NO_DATA = object()
_JOBS = {}       # clé -> _RUNNING | _NO_DATA | ("échec", ts) | WeekReport
_LOCK = threading.Lock()


def clear_jobs():
    with _LOCK:
        _JOBS.clear()


def _thread(work):
    threading.Thread(target=work, name="ccs-bilan", daemon=True).start()


def pending_alert(accounts, settings, now, sent_keys, build=None, has_data=None, run=None):
    """Notification du bilan de la semaine écoulée, une fois par semaine.

    Sans calcul ni lecture tant que le bilan n'est pas dû ; une fois dû, le bilan est
    calculé dans un fil et la notification part au relevé suivant."""
    cfg = settings["alerts"]
    if not cfg.get("weekly_report", True):
        return None
    anchor = week_anchor(accounts, now, settings)
    if not anchor <= now < anchor + DUE_FOR or _already_sent(anchor, sent_keys):
        return None
    key = report_key(anchor)
    start = anchor - WEEK
    with _LOCK:
        for old in [k for k in _JOBS if k != key]:
            del _JOBS[old]
        job = _JOBS.get(key)
        retry = isinstance(job, tuple) and now.timestamp() - job[1] >= RETRY_AFTER_S
        if job is None or retry:
            _JOBS[key] = job = _RUNNING
            launch = True
        else:
            launch = False
    if launch:
        check = has_data or (lambda s, e: globals()["has_data"](s, e))
        make = build or (lambda s, e: build_report(s, e))
        stamp = now.timestamp()

        def work():
            try:
                result = make(start, anchor) if check(start, anchor) else _NO_DATA
            except Exception:  # noqa: BLE001 — journaux ou historique illisibles : nouvel essai plus tard
                log.exception("bilan de la semaine impossible")
                result = ("échec", stamp)
            with _LOCK:
                _JOBS[key] = result
        (run or _thread)(work)
        with _LOCK:
            job = _JOBS.get(key)
    if isinstance(job, WeekReport):
        return notification(job, key)
    return None
