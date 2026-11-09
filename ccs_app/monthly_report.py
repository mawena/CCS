"""Rapport mensuel : usage, équivalent API, modèles, projets et évolution sur un mois civil.

Le mois est un mois civil en heure locale (du 1er à 0 h au 1er du mois suivant à 0 h). Le mois
en cours est arrêté à « maintenant » et comparé au même nombre de jours du mois précédent.
L'agrégation (comptes, activité, coût, modèles, bascules) est celle du bilan de la semaine
(`weekly_report.aggregate`) ; les journaux ne sont lus qu'une fois pour toute la plage
(mois demandé et tendance), grâce au cache de `costs`. Une notification de synthèse part le
1er du mois (`pending_alert`, appelé par `alerts.pending_alerts`), calculée dans un fil.
"""

import argparse
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import advisor, core, costs, weekly_report
from .alerts import Alert

log = logging.getLogger("ccs.monthly_report")

MONTH_NAMES = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
               "septembre", "octobre", "novembre", "décembre"]
KEY_PREFIX = "monthly_report:"
DEFAULT_HOUR = 9                   # `alerts.monthly_report_hour`
DUE_DAYS = 2                       # envoyé le 1er, ou le 2 si le PC dormait
MIN_DATA = timedelta(days=7)       # relevés couvrant au moins 7 jours du mois écoulé
RETRY_AFTER_S = 3600
TOP_PROJECTS = 10
TREND_MONTHS = 5                   # mois précédents lus pour la tendance
TREND_MIN = 3                      # tendance affichée à partir de 3 mois d'activité
MAX_MONTHS_BACK = 120


# --------------------------------------------------------------------------
# Bornes de mois (heure locale)
# --------------------------------------------------------------------------

def month_start(year, month):
    """1er du mois à 0 h, heure locale (mois hors de 1..12 ramenés dans l'année)."""
    year, month = year + (month - 1) // 12, (month - 1) % 12 + 1
    return datetime(year, month, 1).astimezone()


def shift(start, months):
    """Début du mois situé `months` mois après (ou avant, si négatif) celui de `start`."""
    local = start.astimezone()
    return month_start(local.year, local.month + months)


def month_of(dt):
    """Début du mois civil (heure locale) qui contient `dt`."""
    local = dt.astimezone()
    return month_start(local.year, local.month)


def month_choices(now, count=11):
    """[(début, fin)] : le mois en cours (arrêté à `now`) puis les `count` précédents."""
    current = month_of(now)
    out = [(current, now)]
    for i in range(1, count + 1):
        out.append((shift(current, -i), shift(current, -i + 1)))
    return out


def month_label(start):
    local = start.astimezone()
    return f"{MONTH_NAMES[local.month - 1]} {local.year}"


def short_label(start):
    local = start.astimezone()
    return f"{core.MONTHS[local.month - 1]} {local.year}"


def report_key(start):
    local = start.astimezone()
    return f"{KEY_PREFIX}{local.year:04d}-{local.month:02d}"


# --------------------------------------------------------------------------
# Rapport
# --------------------------------------------------------------------------

@dataclass
class TrendPoint:
    start: datetime
    tokens: int = 0
    dollars: float = 0.0
    inconnu: bool = False
    conversations: int = 0
    partial: bool = False


@dataclass
class MonthReport:
    start: datetime
    end: datetime
    full_end: datetime
    base: weekly_report.WeekReport        # même agrégation que le bilan de la semaine
    projects: list = field(default_factory=list)   # [(projet, costs.Cost)], les plus chers d'abord
    paid: float | None = None             # $ par mois payés pour les formules des comptes
    paid_label: str = ""
    previous: "MonthReport | None" = None
    trend: list = field(default_factory=list)      # [TrendPoint], le plus ancien d'abord

    @property
    def partial(self):
        return self.end < self.full_end

    @property
    def cost(self):
        return self.base.cost

    @property
    def empty(self):
        return self.base.empty


def _plans_paid(profiles, settings):
    """(prix mensuel payé, libellé) des formules détectées, ou (None, "")."""
    cfg = settings.get("advisor", {})
    try:
        plans, _uncertain, _unknown = advisor.detect_plans(profiles, cfg.get("profile_plans") or {})
        if not plans:
            return None, ""
        prices, _custom = advisor.plan_prices(settings)
        combo = advisor.combo_of(list(plans.values()), prices)
    except Exception:  # noqa: BLE001 — formule illisible : le rapport se passe de la comparaison
        log.exception("formules des comptes illisibles")
        return None, ""
    return (combo.price, combo.label) if combo.price > 0 else (None, "")


def _in(answers_by_file, s, e):
    """{journal: [réponses dans [s, e)]}, sans les journaux vides."""
    out = {}
    for path, answers in answers_by_file.items():
        kept = [a for a in answers if s <= a.ts < e]
        if kept:
            out[path] = kept
    return out


def _project_costs(answers_by_file, projects_dir, limit=TOP_PROJECTS):
    """Coût de chaque projet, [(projet, Cost)], les plus chers d'abord."""
    from . import transcripts
    groups = {}
    for path, answers in answers_by_file.items():
        for a in answers:
            groups.setdefault(transcripts.project_label(a.cwd, path, projects_dir), []).append(a)
    rows = [(name, costs.cost_of(items)) for name, items in groups.items()]
    rows.sort(key=lambda r: (-r[1].dollars, -r[1].total_tokens, r[0]))
    return rows[:limit]


def _point(start, answers_by_file, s, e, partial=False):
    inside = _in(answers_by_file, s, e)
    cost = costs.cost_of(a for items in inside.values() for a in items)
    convs = sum(1 for p in inside if p.parent.name != "subagents")
    return TrendPoint(start, cost.total_tokens, cost.dollars, cost.inconnu, convs, partial)


def _trend(points):
    """Mois d'activité les plus anciens retirés s'ils sont vides ; vide sous `TREND_MIN` mois."""
    active = [p for p in points if p.tokens]
    if len(active) < TREND_MIN:
        return []
    first = points.index(active[0])
    return points[first:]


def build_report(start, end, store=None, projects_dir=None, profiles=None, settings=None,
                 previous=True, trend_months=TREND_MONTHS):
    """Rapport de [start, end) (un mois civil, ou son début) d'après le store et les journaux.

    Les journaux de toute la plage (tendance comprise) ne sont lus qu'une fois."""
    from .settings import load_settings
    from .store import Store
    start = month_of(start)
    full_end = shift(start, 1)
    end = min(end, full_end)
    own = store is None
    store = store or Store()
    try:
        profiles = core.list_profiles() if profiles is None else profiles
        settings = settings or load_settings()
        projects_dir = projects_dir or core.paths().config_dir / "projects"
        earliest = shift(start, -trend_months) if previous else start
        prev_start = shift(start, -1)
        span = end - start
        prev_end = min(start, prev_start + span) if end < full_end else start
        floor = (earliest - timedelta(days=1)).timestamp()
        end_ts = end.timestamp()
        samples = {p.name: {k: [row for row in store.samples(p.name, k, floor) if row[0] < end_ts]
                            for k in ("session", "weekly_all")} for p in profiles}
        events = store.events(earliest.timestamp())
        answers = costs.period_answers(projects_dir, earliest.timestamp(), end_ts)
        report = _assemble(start, end, full_end, samples, events, answers, projects_dir)
        report.paid, report.paid_label = _plans_paid(profiles, settings)
        if previous:
            report.previous = _assemble(prev_start, prev_end, start, samples, events, answers,
                                        projects_dir, with_projects=False)
            points = []
            for i in range(trend_months, -1, -1):
                m = shift(start, -i)
                m_end = full_end if i == 0 else shift(m, 1)
                points.append(_point(m, answers, m.timestamp(), min(m_end, end).timestamp(),
                                     partial=i == 0 and end < full_end))
            report.trend = _trend(points)
        return report
    finally:
        if own:
            store.close()


def _assemble(start, end, full_end, samples, events, answers, projects_dir, with_projects=True):
    s, e = start.timestamp(), end.timestamp()
    base = weekly_report.aggregate(start, end, {n: {k: [r for r in rows if r[0] < e] for k, rows in kinds.items()}
                                                for n, kinds in samples.items()},
                                   events, answers, projects_dir)
    report = MonthReport(start, end, full_end, base)
    if with_projects:
        report.projects = _project_costs(_in(answers, s, e), projects_dir)
    return report


# --------------------------------------------------------------------------
# Textes
# --------------------------------------------------------------------------

def title(report):
    suffix = f" (au {weekly_report._date(report.end)})" if report.partial else ""
    return f"Rapport mensuel : {month_label(report.start)}{suffix}"


def _signed_dollars(value):
    return ("+" if value > 0 else "−" if value < 0 else "") + costs.format_dollars(abs(value))


def _signed_tokens(value):
    return ("+" if value > 0 else "−" if value < 0 else "") + weekly_report.fmt_tokens(abs(value))


def evolution(cur, prev, fmt):
    """« (+12 % · +3,40 $) » : évolution en pourcentage puis en valeur ; « (=) » si rien ne bouge."""
    diff = cur - prev
    if not diff:
        return " (=)"
    if not prev:
        return f" (nouveau · {fmt(diff)})"
    pct = 100 * diff / prev
    if abs(pct) < 0.5:
        return " (=)"
    return f" ({pct:+.0f}".replace("-", "−") + f" % · {fmt(diff)})"


def _count(value):
    return f"{value:+d}".replace("-", "−")


def _weeks_used(points):
    return core.fr(points / 100) if points else "0"


def comparison_lines(report):
    prev = report.previous
    if prev is None:
        return []
    c, p = report.cost, prev.cost
    return [
        f"tokens : {weekly_report.fmt_tokens(c.total_tokens)}"
        f"{evolution(c.total_tokens, p.total_tokens, _signed_tokens)}",
        f"équivalent API : {weekly_report._dollars(c)}{evolution(c.dollars, p.dollars, _signed_dollars)}",
        f"conversations : {report.base.conversations}"
        f"{evolution(report.base.conversations, prev.base.conversations, _count)}",
        f"fenêtres de 5 h : {report.base.windows}"
        f"{evolution(report.base.windows, prev.base.windows, _count)}",
        f"bascules : {report.base.switches}"
        f"{evolution(report.base.switches, prev.base.switches, _count)}",
    ]


def sections(report):
    """[(titre, [lignes])] du rapport, pour `format_text` et l'application."""
    base = report.base
    out = []
    accounts = []
    for a in base.accounts:
        if a.weekly_peak is None and not a.windows and not a.switches_to:
            accounts.append(f"{a.name} : aucun relevé ce mois-ci")
            continue
        parts = []
        if a.weekly_peak is not None:
            parts.append(f"{_weeks_used(a.weekly_used)} semaine(s) utilisée(s) "
                         f"(pic hebdomadaire à {a.weekly_peak:.0f} %)")
        if a.windows:
            parts.append(weekly_report._plural(a.windows, "fenêtre de 5 h", "fenêtres de 5 h"))
        if a.session_hits:
            parts.append(weekly_report._plural(a.session_hits, "limite de session atteinte",
                                               "limites de session atteintes"))
        if a.switches_to:
            parts.append(weekly_report._plural(a.switches_to, "bascule vers ce compte",
                                               "bascules vers ce compte"))
        accounts.append(f"{a.name} : " + ", ".join(parts))
    if accounts:
        out.append(("Comptes", accounts))
    c = report.cost
    if not c.reponses:
        out.append(("Activité", ["Aucune activité de Claude Code enregistrée sur ce PC."]))
    else:
        out.append(("Activité", [
            f"{weekly_report._plural(base.conversations, 'conversation')}, "
            f"{weekly_report._plural(base.sessions, 'session')}, "
            f"{weekly_report._plural(c.reponses, 'réponse')}",
            f"{weekly_report.fmt_tokens(c.total_tokens)} tokens"]))
        api = [f"{weekly_report._dollars(c)} au tarif de l'API"]
        if report.paid:
            ratio = c.dollars / report.paid if not report.partial else None
            line = f"{api[0]}, contre {advisor.money(report.paid)}/mois payés ({report.paid_label})"
            if ratio is not None and c.dollars:
                line += f" : ×{core.fr(ratio)}"
            api = [line]
        out.append(("Équivalent API", api))
        out.append(("Modèles", [_model_line(report)]))
        if report.projects:
            total = c.dollars or 0
            rows = []
            for name, cost in report.projects:
                share = f" ({100 * cost.dollars / total:.0f} %)" if total else ""
                rows.append(f"{name} : {weekly_report._dollars(cost)}{share}")
            out.append((f"Projets ({len(rows)} premiers)", rows))
    out.append(("Bascules et alertes", weekly_report.event_lines(base)))
    lines = comparison_lines(report)
    if lines:
        head = ("Par rapport au même nombre de jours du mois précédent" if report.partial
                else "Par rapport au mois précédent")
        out.append((head, lines))
    if report.trend:
        rows = []
        for p in report.trend:
            money = "≥ " if p.inconnu else "≈ "
            rows.append(f"{short_label(p.start)}{' (en cours)' if p.partial else ''} : "
                        f"{weekly_report.fmt_tokens(p.tokens)} tokens · "
                        f"{money}{costs.format_dollars(p.dollars)} · "
                        f"{weekly_report._plural(p.conversations, 'conversation')}")
        out.append((f"Tendance sur {len(rows)} mois", rows))
    return out


def _model_line(report):
    """Part de chaque famille de modèles (tokens pondérés) avec son équivalent API."""
    from . import transcripts
    dollars = {}
    for name, mc in report.cost.modeles.items():
        fam = transcripts.model_family(name)
        dollars[fam] = None if dollars.get(fam, 0) is None or mc.dollars is None \
            else dollars.get(fam, 0) + mc.dollars
    parts = []
    for fam, pct in weekly_report._shares(report.base.by_model, 5):
        d = dollars.get(fam)
        extra = f" ({costs.format_dollars(d)})" if d else ""
        parts.append(f"{fam.capitalize()} {pct:.0f} %{extra}")
    return " · ".join(parts)


def format_text(report):
    """Texte de `ccs mois`."""
    lines = [title(report)]
    for head, rows in sections(report):
        lines += ["", head] + [f"• {row}" for row in rows]
    return "\n".join(lines)


def notification(report, key):
    """Notification de synthèse (courte)."""
    c = report.cost
    period = month_label(report.start).capitalize()
    if not c.reponses:
        body = f"{period} : aucune activité de Claude Code enregistrée sur ce PC."
    else:
        prev = report.previous
        delta = ""
        if prev is not None and prev.cost.dollars:
            pct = 100 * (c.dollars - prev.cost.dollars) / prev.cost.dollars
            if abs(pct) >= 0.5:
                delta = f", {pct:+.0f} % sur le mois précédent".replace("-", "−")
        paid = f" contre {advisor.money(report.paid)} payés" if report.paid else ""
        body = (f"{period} : {weekly_report.fmt_tokens(c.total_tokens)} tokens, "
                f"{weekly_report._dollars(c)} au tarif de l'API{paid}"
                f"{delta}, "
                f"{weekly_report._plural(report.base.conversations, 'conversation')}, "
                f"{weekly_report._plural(report.base.windows, 'fenêtre de 5 h', 'fenêtres de 5 h')}.")
        if report.projects:
            name, cost = report.projects[0]
            body += f" Projet principal : {name} ({weekly_report._dollars(cost)})."
    return Alert(key, "Rapport mensuel", body, 0)


# --------------------------------------------------------------------------
# Commande `ccs mois`
# --------------------------------------------------------------------------

class _Usage(Exception):
    pass


def _months_back(text):
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"nombre de mois invalide : « {text} »") from None
    if not 0 <= n <= MAX_MONTHS_BACK:
        raise argparse.ArgumentTypeError(f"nombre de mois entre 0 et {MAX_MONTHS_BACK} : « {text} »")
    return n


def add_arguments(parser):
    """Options de `ccs mois` (pour le sous-analyseur de cli)."""
    parser.add_argument("--precedent", type=_months_back, default=0, metavar="N",
                        help="N mois avant le mois écoulé (0 = le dernier mois terminé)")


def _parse(argv):
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise _Usage(message)
    parser = Parser(prog="ccs mois", add_help=False)
    add_arguments(parser)
    return parser.parse_args(list(argv)).precedent


def command(args, now=None, build=None):
    """`ccs mois [--precedent N]` : (code, texte). `args` est la liste des arguments ou un
    objet portant `precedent` ; codes : 0 réussi, 1 échec, 2 usage."""
    try:
        back = args.precedent if hasattr(args, "precedent") else _parse(args or [])
        if not isinstance(back, int) or not 0 <= back <= MAX_MONTHS_BACK:
            raise _Usage(f"nombre de mois entre 0 et {MAX_MONTHS_BACK}")
    except _Usage as e:
        return 2, f"Usage : ccs mois [--precedent N] ({e})"
    except SystemExit:
        return 2, "Usage : ccs mois [--precedent N]"
    from datetime import timezone
    now = now or datetime.now(timezone.utc)
    start = shift(month_of(now), -(back + 1))
    end = shift(start, 1)
    try:
        report = (build or build_report)(start, end)
    except Exception as e:  # noqa: BLE001 — historique ou journaux illisibles : message, pas de trace
        return 1, f"Rapport impossible : {e}"
    return 0, format_text(report)


# --------------------------------------------------------------------------
# Notification mensuelle (appelée à chaque relevé du service)
# --------------------------------------------------------------------------

_RUNNING = object()
_NO_DATA = object()
_JOBS = {}       # clé -> _RUNNING | _NO_DATA | ("échec", ts) | MonthReport
_LOCK = threading.Lock()


def clear_jobs():
    with _LOCK:
        _JOBS.clear()


def _build_and_free(start, end):
    """Rapport calculé par le service, qui ne garde pas en mémoire les journaux lus pour lui."""
    try:
        return build_report(start, end)
    finally:
        costs.clear_cache()


def _thread(work):
    threading.Thread(target=work, name="ccs-rapport-mensuel", daemon=True).start()


def _has_data(start, end):
    return weekly_report.has_data(start, end, span=MIN_DATA)


def pending_alert(accounts, settings, now, sent_keys, build=None, has_data=None, run=None):
    """Notification du rapport du mois écoulé, une fois par mois (le 1er à l'heure réglée,
    jusqu'au 2 si le PC dormait). Sans calcul ni lecture tant que le rapport n'est pas dû ;
    une fois dû, il est calculé dans un fil et la notification part au relevé suivant."""
    cfg = settings["alerts"]
    if not cfg.get("monthly_report", True):
        return None
    hour = cfg.get("monthly_report_hour", DEFAULT_HOUR)
    if not isinstance(hour, int) or isinstance(hour, bool) or not 0 <= hour <= 23:
        hour = DEFAULT_HOUR
    this_month = month_of(now)
    due = this_month + timedelta(hours=hour)
    if not due <= now < this_month + timedelta(days=DUE_DAYS):
        return None
    start = shift(this_month, -1)
    key = report_key(start)
    if key in sent_keys:
        return None
    with _LOCK:
        for old in [k for k in _JOBS if k != key]:
            del _JOBS[old]
        job = _JOBS.get(key)
        retry = isinstance(job, tuple) and now.timestamp() - job[1] >= RETRY_AFTER_S
        launch = job is None or retry
        if launch:
            _JOBS[key] = job = _RUNNING
    if launch:
        check = has_data or _has_data
        make = build or _build_and_free
        stamp = now.timestamp()

        def work():
            try:
                result = make(start, this_month) if check(start, this_month) else _NO_DATA
            except Exception:  # noqa: BLE001 — journaux ou historique illisibles : nouvel essai plus tard
                log.exception("rapport mensuel impossible")
                result = ("échec", stamp)
            with _LOCK:
                _JOBS[key] = result
        (run or _thread)(work)
        with _LOCK:
            job = _JOBS.get(key)
    if isinstance(job, MonthReport):
        return notification(job, key)
    return None
