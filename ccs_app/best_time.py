"""Meilleur moment pour lancer une grosse tâche (fonctions pures : `now` est toujours passé).

Question : « quand lancer un gros travail pour avoir le plus de quota d'affilée ? ».
Le calcul part de `state.json` (rien d'autre) et mesure, pour chaque départ possible,
le quota cumulé disponible pendant [départ, départ + durée] en **fenêtres de 5 h**.

Hypothèses (écrites ici pour qu'on puisse les discuter) :
- chaque compte apporte d'abord ce qui reste de sa fenêtre en cours (100 % - usage),
  puis une fenêtre neuve (1,0) à sa réinitialisation, puis d'autres toutes les 5 h ;
- une fenêtre de 5 h ne commence qu'au premier message : sans fenêtre en cours, une
  fenêtre neuve démarre au départ de la tâche ; on travaille en continu, donc les
  fenêtres suivantes s'enchaînent sans trou (le plan de l'orchestrateur ne change
  rien : il ne démarre une fenêtre qu'au plus tôt, jamais avant l'usage réel) ;
- une fenêtre ne compte en entier que s'il reste au moins `FULL_AFTER_H` (1 h) pour la
  consommer, sinon au prorata du temps restant : un départ ne profite pas d'une fenêtre
  qui s'ouvre 5 minutes avant la fin ;
- le reste hebdomadaire plafonne le total d'un compte jusqu'à la réinitialisation de la
  semaine : une semaine pleine vaut `WEEK_WINDOWS` fenêtres de 5 h (hypothèse : le vrai
  rapport dépend de la formule et n'est pas publié) ; après la réinitialisation, plus de
  plafond ;
- les comptes en erreur bloquante sont ignorés (les erreurs passagères 429/5xx/réseau
  laissent les dernières données valables, comme dans `forecast`).

L'unité est donc du quota disponible, pas une durée de travail : la consommation réelle
dépend du modèle et des requêtes.
"""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import core
from .forecast import TRANSIENT_ERRORS

WINDOW_H = 5.0
FULL_AFTER_H = 1.0
WEEK_WINDOWS = 10.0
STEP = timedelta(minutes=15)
NOW_TOLERANCE = 0.10      # « maintenant » gagne s'il est à 10 % près du meilleur
ALT_SPACING = timedelta(minutes=90)
ALT_MIN_RATIO = 0.5
MAX_ALTERNATIVES = 3
DURATION_RANGE = (1.0, 10.0)
SPAN_RANGE = (1.0, 72.0)
DEFAULT_DURATION_H = 3.0
DEFAULT_SPAN_H = 24.0

USAGE = "usage : ccs moment [--duree 3h] [--sur 24h]   (durée de 1 h à 10 h, horizon de 1 h à 72 h)"


@dataclass
class Slot:
    start: datetime
    score: float            # fenêtres de 5 h disponibles pendant la tâche
    text: str = ""          # explication lisible
    parts: list = field(default_factory=list)   # [(compte, fenêtres)]


@dataclass
class Result:
    now: datetime
    duration_h: float
    span_h: float
    curve: list = field(default_factory=list)          # [Slot], un par départ possible
    best: Slot | None = None
    alternatives: list = field(default_factory=list)   # [Slot]
    now_is_best: bool = False
    ignored: list = field(default_factory=list)        # [(compte, raison)]
    paused: bool = False
    stale: bool = False
    accounts: int = 0


# --------------------------------------------------------------------------
# Lecture de l'état
# --------------------------------------------------------------------------

@dataclass
class _Acct:
    name: str
    sess_pct: float | None
    sess_reset: datetime | None
    week_pct: float | None
    week_reset: datetime | None


def _limit_dt(lim):
    return core.parse_dt(lim.get("resets_at"))


def _usable(state):
    """([_Acct], [(nom, raison)]) : comptes dont les données servent, et ignorés."""
    ok, ignored = [], []
    for a in (state or {}).get("accounts") or []:
        err = a.get("error")
        if err and not str(err).startswith(TRANSIENT_ERRORS):
            ignored.append((a["name"], f"erreur : {err}"))
            continue
        limits = a.get("limits") or []
        sess = next((x for x in limits if x.get("kind") == "session"), None)
        weeks = [x for x in limits if str(x.get("kind", "")).startswith("weekly")]
        week = max(weeks, key=lambda x: float(x.get("percent") or 0), default=None)
        ok.append(_Acct(a["name"],
                        None if sess is None else float(sess.get("percent") or 0),
                        None if sess is None else _limit_dt(sess),
                        None if week is None else float(week.get("percent") or 0),
                        None if week is None else _limit_dt(week)))
    return ok, ignored


# --------------------------------------------------------------------------
# Calcul
# --------------------------------------------------------------------------

def _hours(a, b):
    return (b - a).total_seconds() / 3600


def _weight(hours_left):
    """Part d'une fenêtre utilisable quand il reste `hours_left` pour la consommer."""
    return max(0.0, min(1.0, hours_left / FULL_AFTER_H))


def _account_slot(acc, start, end):
    """(fenêtres, phrase) pour un compte sur [start, end]."""
    pieces = []     # (début de fenêtre, fenêtres)
    live = acc.sess_reset is not None and acc.sess_reset > start
    note = None
    if live:
        left = max(0.0, 100 - (acc.sess_pct or 0)) / 100
        stop = min(acc.sess_reset, end)
        pieces.append((start, left * _weight(_hours(start, stop))))
        t = acc.sess_reset
        if acc.sess_reset < end:
            note = f"{acc.name} repart à neuf à {acc.sess_reset.astimezone():%H:%M}"
        else:
            note = f"{acc.name} a encore {round(max(0.0, 100 - (acc.sess_pct or 0)))} %"
    else:
        t = start
        note = f"{acc.name} démarre une fenêtre neuve"
    window = timedelta(hours=WINDOW_H)
    while t < end:
        pieces.append((t, _weight(_hours(t, end))))
        t += window
    total = sum(v for _, v in pieces)
    if acc.week_pct is None:
        return total, note
    exhausted_note = None
    if acc.week_reset is not None and acc.week_reset <= start:
        return total, note                      # nouvelle semaine : pas de plafond
    budget = max(0.0, 100 - acc.week_pct) / 100 * WEEK_WINDOWS
    before = sum(v for s, v in pieces if acc.week_reset is None or s < acc.week_reset)
    after = total - before
    capped = min(before, budget)
    if capped < before - 1e-9:
        if budget <= 1e-9:
            if acc.week_reset is not None and acc.week_reset < end:
                exhausted_note = (f"{acc.name} : semaine épuisée jusqu'à "
                                  f"{acc.week_reset.astimezone():%H:%M}")
            elif acc.week_reset is not None:
                exhausted_note = (f"{acc.name} : semaine épuisée "
                                  f"(retour {_when(acc.week_reset, start)})")
            else:
                exhausted_note = f"{acc.name} : semaine épuisée"
        else:
            exhausted_note = (f"{acc.name} : limité par la semaine "
                              f"(reste {round(100 - acc.week_pct)} %)")
    return capped + after, exhausted_note or note


def _when(dt, ref):
    local, base = dt.astimezone(), ref.astimezone()
    if local.date() == base.date():
        return f"à {local:%H:%M}"
    if local.date() == (base + timedelta(days=1)).date():
        return f"demain {local:%H:%M}"
    return f"le {local:%d/%m} à {local:%H:%M}"


def num(x, digits=1):
    """Nombre à la française : 1,8 ; 2 (sans zéro inutile)."""
    s = f"{x:.{digits}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return (s or "0").replace(".", ",")


def windows_text(x):
    n = num(x)
    return f"{n} fenêtre de 5 h" if x < 2 - 1e-9 else f"{n} fenêtres de 5 h"


def _slot(accts, start, end):
    parts, notes, total = [], [], 0.0
    for acc in accts:
        value, note = _account_slot(acc, start, end)
        parts.append((acc.name, round(value, 6)))
        notes.append(note)
        total += value
    total = round(total, 6)
    text = f"{windows_text(total)} disponibles ({', '.join(notes)})" if notes else ""
    return Slot(start, total, text, parts)


def candidates(now, span_h):
    """Départs possibles : maintenant, puis tous les quarts d'heure sur l'horizon."""
    out = [now]
    end = now + timedelta(hours=span_h)
    ts = (int(now.timestamp() // STEP.total_seconds()) + 1) * STEP.total_seconds()
    t = datetime.fromtimestamp(ts, timezone.utc)
    while t < end:
        out.append(t)
        t += STEP
    return out


def compute(state, duration_h=DEFAULT_DURATION_H, span_h=DEFAULT_SPAN_H, now=None):
    now = now or datetime.now(timezone.utc)
    accts, ignored = _usable(state)
    paused = bool((state or {}).get("pause")
                  or ((state or {}).get("orchestrator") or {}).get("paused"))
    updated = (state or {}).get("updated_at")
    stale = bool(updated) and now.timestamp() - updated > 600
    res = Result(now, duration_h, span_h, ignored=ignored, paused=paused, stale=stale,
                 accounts=len(accts))
    if not accts:
        return res
    task = timedelta(hours=duration_h)
    res.curve = [_slot(accts, s, s + task) for s in candidates(now, span_h)]
    top = max(s.score for s in res.curve)
    if top <= 1e-9:
        return res
    best = next(s for s in res.curve if s.score >= top - 1e-9)    # le plus tôt à égalité
    if res.curve[0].score >= top * (1 - NOW_TOLERANCE):
        best, res.now_is_best = res.curve[0], True
    res.best = best
    chosen = [best.start]
    for s in sorted(res.curve, key=lambda s: (-s.score, s.start)):
        if len(res.alternatives) >= MAX_ALTERNATIVES or s.score < top * ALT_MIN_RATIO:
            break
        if all(abs(s.start - c) >= ALT_SPACING for c in chosen):
            res.alternatives.append(s)
            chosen.append(s.start)
    res.alternatives.sort(key=lambda s: s.start)
    return res


# --------------------------------------------------------------------------
# Texte et commande
# --------------------------------------------------------------------------

def label(slot, now):
    if slot.start == now:
        return f"maintenant ({now.astimezone():%H:%M})"
    return _when(slot.start, now).removeprefix("à ")


def hours_text(h):
    return f"{num(h)} h"


def format_text(res):
    head = (f"Meilleur moment pour une tâche de {hours_text(res.duration_h)} "
            f"(sur les prochaines {hours_text(res.span_h)})")
    lines = [head]
    if res.accounts == 0:
        lines.append("Aucun compte utilisable : tous sont en erreur ou sans données.")
    elif res.best is None:
        lines.append("Aucun quota disponible sur cet horizon : tous les comptes sont épuisés "
                     "pour la semaine.")
    else:
        lead = "Lance-la maintenant" if res.now_is_best else f"Départ conseillé : {label(res.best, res.now)}"
        lines.append(f"{lead} — {res.best.text}.")
        if res.alternatives:
            lines.append("Autres départs :")
            for s in res.alternatives:
                lines.append(f"  • {label(s, res.now)} — {s.text}")
    if res.ignored:
        lines.append("Ignorés : " + ", ".join(f"{n} ({why})" for n, why in res.ignored) + ".")
    if res.paused:
        lines.append("Orchestrateur en pause : il ne démarre rien ; le calcul suppose que c'est "
                     "toi qui lances la tâche.")
    if res.stale:
        lines.append("Attention : l'état date de plus de 10 minutes (service arrêté ?).")
    lines.append("Unité : quota disponible en fenêtres de 5 h, pas une durée de travail réelle.")
    return "\n".join(lines)


def parse_hours(text):
    """« 3h », « 2h30 », « 90m », « 4 », « 1,5h » → heures (float), None si illisible."""
    t = str(text).strip().lower().replace(",", ".").replace(" ", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(?:h(\d{1,2})?|m|min)?", t)
    if not m:
        return None
    n = float(m.group(1))
    if t.endswith(("m", "min")):
        return n / 60
    return n + (int(m.group(2)) / 60 if m.group(2) else 0)


def _parse_args(args):
    """(durée, horizon) ou message d'erreur (str)."""
    duration, span = DEFAULT_DURATION_H, DEFAULT_SPAN_H
    args = list(args or [])
    i = 0
    while i < len(args):
        a = args[i]
        name, eq, val = a.partition("=")
        if name not in ("--duree", "--sur"):
            return USAGE
        if not eq:
            i += 1
            if i >= len(args):
                return USAGE
            val = args[i]
        h = parse_hours(val)
        low, high = DURATION_RANGE if name == "--duree" else SPAN_RANGE
        if h is None or not low - 1e-9 <= h <= high + 1e-9:
            return USAGE
        if name == "--duree":
            duration = h
        else:
            span = h
        i += 1
    return duration, span


def command(args, state=None, now=None):
    """`ccs moment [--duree 3h] [--sur 24h]` → (code de sortie, texte) : 0, 1 sans état, 2 usage."""
    parsed = _parse_args(args)
    if isinstance(parsed, str):
        return 2, parsed
    if state is None:
        from . import daemon
        state = core.load_json(daemon.state_path())
    if not state or not state.get("accounts"):
        return 1, "Aucun état : le service n'a pas encore relevé les comptes (ccs status)."
    now = now or datetime.now(timezone.utc)
    return 0, format_text(compute(state, parsed[0], parsed[1], now))
