"""Réglages utilisateur (~/.claude-accounts/settings.json), fusionnés avec les défauts."""

import copy
import json
import logging
import math
import re

from . import core, launch_options, phone

log = logging.getLogger("ccs.settings")

DEFAULTS = {
    "auto_switch": {
        "enabled": True,
        "threshold": 98,
        "target_max_session": 80,
        "target_max_weekly": 95,
    },
    "alerts": {
        "enabled": True,
        "session_thresholds": [80, 95],
        "eta_minutes": 20,
        "weekly_ahead_points": 15,
        "weekly_forecast": True,
        "weekly_forecast_days": 2,
        "resets": True,
        "auth": True,
        "sessions": True,
        "waiting_reminder": True,
        "waiting_reminder_min": 10,
        # Conseil de modèle : compte actif au-delà de ce % (session ou semaine) avec un
        # modèle cher → proposer la famille moins chère (une fois par fenêtre de 5 h).
        "model_advice": True,
        "model_advice_pct": 80,
        # Bilan de la semaine : notification une fois par semaine, au début de la semaine
        # de la plupart des comptes (jour None) ou le jour donné (0 = lundi) à l'heure donnée.
        "weekly_report": True,
        "weekly_report_day": None,
        "weekly_report_hour": 9,
        # Rapport mensuel : notification le 1er du mois (ou le 2), à l'heure donnée.
        "monthly_report": True,
        "monthly_report_hour": 9,
        # Ne pas déranger : pendant la plage (qui peut passer minuit, heure locale réelle,
        # jours = jour de début) les notifications sont retenues puis résumées en une seule ;
        # « attend ta réponse » (et son rappel) passe quand allow_waiting.
        "quiet": {
            "enabled": False,
            "start": "22:00",
            "end": "08:00",
            "days": [0, 1, 2, 3, 4, 5, 6],
            "allow_waiting": True,
        },
    },
    "poll": {"normal_s": 300, "fast_s": 60},
    # Conseiller de formule (`advisor`) : semaines analysées, marge de sécurité,
    # tarifs surchargés ({"pro": 20, "max5": 100, "max20": 200} en $ par mois) et
    # formule imposée par profil ({"perso": "max5"}) si la détection se trompe.
    "advisor": {
        "weeks": 4,
        "margin_pct": 20,
        "plan_prices": {},
        "profile_plans": {},
        "max_accounts": 3,
    },
    "updates": {"enabled": True},
    "warmup": {},
    "orchestrator": {
        "enabled": False,
        "active_hours": {"start": "08:00", "end": "02:00", "days": [0, 1, 2, 3, 4, 5, 6]},
        "stagger": True,
        "expiring_switch": True,
        "expiring_within_min": 60,
        "expiring_min_left": 30,
        "expiring_cooldown_min": 30,
        "reserve_points": 10,
        "max_weekly_start": 95,
    },
    # Phase 11 : file de tâches, téléphone (ntfy), archive, mémoire des sessions,
    # contexte lourd, budget par projet (mêmes valeurs que les DEFAULTS des modules).
    "tasks": {"enabled": True, "night": {"start": "23:00", "end": "07:00"}, "max_attempts": 3},
    "phone": {
        "enabled": False,
        "server": "https://ntfy.sh",
        "topic": "",
        "events": {"waiting": True, "task": True, "switch": True, "exhausted": True},
    },
    "archive": {"enabled": True, "idle_days": 1, "max_age_days": 0},
    "sessions": {"idle_hours": 2},
    "context_alert": {"enabled": True, "threshold_tokens": 150000},
    "budget": {"enabled": True, "alert_pcts": [80, 100]},
    # Phase 12 : chat graphique, panneau Fichiers, page Projets, apparence.
    # idle_suspend_min : minutes d'inactivité avant de suspendre le processus claude d'un
    # chat (0 = jamais) ; rights : mode de permission des nouveaux chats.
    "chat": {"idle_suspend_min": 30, "rights": "manual"},
    "files": {"layout": "B", "show_ignored": False},
    "appearance": {"color_scheme": "auto", "account_colors": {}},
}


def settings_path():
    return core.paths().store / "settings.json"


def _merge(base, override):
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


# --------------------------------------------------------------------------
# Validation (fichier édité à la main) : une clé invalide retombe sur sa valeur
# par défaut, les clés inconnues sont conservées, le fichier n'est jamais réécrit.
# --------------------------------------------------------------------------

# Bornes (min, max) des nombres, là où le code en suppose ; ailleurs : 0 à 100 000.
BOUNDS = {
    "auto_switch.threshold": (1, 100),
    "auto_switch.target_max_session": (0, 100),
    "auto_switch.target_max_weekly": (0, 100),
    "alerts.eta_minutes": (1, 1440),
    "alerts.weekly_ahead_points": (0, 100),
    "alerts.weekly_forecast_days": (0, 7),
    "alerts.waiting_reminder_min": (1, 1440),
    "alerts.model_advice_pct": (0, 100),
    "alerts.weekly_report_hour": (0, 23),
    "alerts.monthly_report_hour": (0, 23),
    "poll.normal_s": (10, 86400),
    "poll.fast_s": (5, 86400),
    "advisor.weeks": (1, 52),
    "advisor.margin_pct": (0, 100),
    "advisor.max_accounts": (1, 50),
    "orchestrator.expiring_within_min": (1, 1440),
    "orchestrator.expiring_min_left": (0, 1440),
    "orchestrator.expiring_cooldown_min": (0, 1440),
    "orchestrator.reserve_points": (0, 100),
    "orchestrator.max_weekly_start": (0, 100),
    "tasks.max_attempts": (1, 10),
    "archive.idle_days": (0, 3650),
    "archive.max_age_days": (0, 36500),
    "sessions.idle_hours": (0.01, 720),
    "context_alert.threshold_tokens": (1000, 10_000_000),
    "chat.idle_suspend_min": (0, 1440),
}
INTEGERS = {"alerts.weekly_report_hour", "alerts.monthly_report_hour", "advisor.weeks",
            "advisor.max_accounts", "tasks.max_attempts", "archive.idle_days",
            "archive.max_age_days", "context_alert.threshold_tokens",
            "chat.idle_suspend_min"}
CHOICES = {
    "chat.rights": launch_options.PERMISSION_MODE_VALUES,
    "files.layout": ("A", "B"),
    "appearance.color_scheme": ("auto", "clair", "sombre"),
}
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _in_bounds(path, v):
    lo, hi = BOUNDS.get(path, (0, 100000))
    return _is_number(v) and lo <= v <= hi


def _hhmm_ok(v):
    m = _HHMM.match(v) if isinstance(v, str) else None
    return bool(m) and int(m.group(1)) < 24 and int(m.group(2)) < 60


def _days_ok(v):
    return isinstance(v, list) and all(isinstance(d, int) and not isinstance(d, bool)
                                       and 0 <= d <= 6 for d in v)


def _valid(path, v, default):
    """Une valeur est-elle acceptable pour cette clé ? (type de la valeur par défaut)"""
    if path == "alerts.weekly_report_day":
        return v is None or (isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 6)
    if path == "alerts.session_thresholds":
        return isinstance(v, list) and all(_in_bounds("pct", x) and x <= 100 for x in v)
    if path == "phone.server":
        return isinstance(v, str) and phone.valid_server(v)
    if path == "phone.topic":
        return isinstance(v, str) and (v == "" or phone.valid_topic(v))
    if path in CHOICES:
        return isinstance(v, str) and v in CHOICES[path]
    if path == "budget.alert_pcts":
        return (isinstance(v, list) and all(_is_number(x) and 0 < x <= 1000 for x in v))
    if path in ("tasks.night.start", "tasks.night.end"):
        return _hhmm_ok(v)
    if isinstance(default, bool):
        return isinstance(v, bool)
    if _is_number(default):
        return _in_bounds(path, v) and (path not in INTEGERS or isinstance(v, int))
    if isinstance(default, list):
        return isinstance(v, list)
    if isinstance(default, str):
        return isinstance(v, str)
    return True


def _clean_active_hours(value, default, path, bad):
    if not isinstance(value, dict):
        bad.append(path)
        return copy.deepcopy(default)
    out = copy.deepcopy(value)
    for key in ("start", "end"):
        if key in value and not _hhmm_ok(value[key]):
            bad.append(f"{path}.{key}")
            out[key] = default[key]
    if "days" in value and not _days_ok(value["days"]):
        bad.append(f"{path}.days")
        out["days"] = list(default["days"])
    return _merge(default, out)


def _clean_quiet(value, default, path, bad):
    """Plage de silence : horaires et jours comme la plage de l'orchestrateur, plus deux booléens."""
    out = _clean_active_hours(value, default, path, bad)
    if isinstance(value, dict):
        for key in ("enabled", "allow_waiting"):
            if key in value and not isinstance(value[key], bool):
                bad.append(f"{path}.{key}")
                out[key] = default[key]
    return out


def _clean_dict_of(value, ok, path, bad):
    """Dictionnaire libre : les entrées invalides sont retirées une à une."""
    if not isinstance(value, dict):
        bad.append(path)
        return {}
    out = {}
    for k, v in value.items():
        if ok(v):
            out[k] = copy.deepcopy(v)
        else:
            bad.append(f"{path}.{k}")
    return out


def _slot_ok(slot):
    return (isinstance(slot, dict) and _hhmm_ok(slot.get("time"))
            and ("days" not in slot or _days_ok(slot["days"])))


def _clean_warmup(value, path, bad):
    if not isinstance(value, dict):
        bad.append(path)
        return {}
    out = {}
    for name, slots in value.items():
        if not isinstance(slots, list):
            bad.append(f"{path}.{name}")
            continue
        good = [copy.deepcopy(s) for s in slots if _slot_ok(s)]
        if len(good) != len(slots):
            bad.append(f"{path}.{name}")
        out[name] = good
    return out


def _clean(value, default, path, bad):
    """Valeur validée de `path` (dict : récursif) ; `bad` reçoit les chemins ignorés."""
    if path == "orchestrator.active_hours":
        return _clean_active_hours(value, default, path, bad)
    if path == "alerts.quiet":
        return _clean_quiet(value, default, path, bad)
    if path == "advisor.plan_prices":
        return _clean_dict_of(value, lambda v: _is_number(v) and v > 0, path, bad)
    if path == "advisor.profile_plans":
        return _clean_dict_of(value, lambda v: isinstance(v, str), path, bad)
    if path == "appearance.account_colors":
        return _clean_dict_of(value, lambda v: isinstance(v, str) and bool(_COLOR.match(v)), path, bad)
    if path == "warmup":
        return _clean_warmup(value, path, bad)
    if isinstance(default, dict):
        if not isinstance(value, dict):
            bad.append(path)
            return copy.deepcopy(default)
        out = {}
        for key, dv in default.items():
            sub = f"{path}.{key}" if path else key
            out[key] = _clean(value[key], dv, sub, bad) if key in value else copy.deepcopy(dv)
        for key, v in value.items():  # clés inconnues : conservées, sans effet
            if key not in default:
                out[key] = copy.deepcopy(v)
        return out
    if _valid(path, value, default):
        return copy.deepcopy(value)
    bad.append(path)
    return copy.deepcopy(default)


UNREADABLE = "settings.json illisible"
_reported = set()


def _read():
    """(contenu, lisible) : le fichier tel qu'il est, sans jamais l'écrire."""
    try:
        text = settings_path().read_text()
    except OSError:
        return {}, True  # absent : les valeurs par défaut sont normales
    try:
        data = json.loads(text)
    except ValueError:
        return {}, False
    return (data, True) if isinstance(data, dict) else ({}, False)


def _load():
    raw, readable = _read()
    bad = []
    out = _clean(raw, DEFAULTS, "", bad)
    return out, ([] if readable else [UNREADABLE]) + sorted(set(bad))


def problems():
    """Clés du fichier ignorées (valeur invalide) ; [] si tout va bien."""
    return _load()[1]


def load_settings():
    out, bad = _load()
    key = tuple(bad)
    if bad and key not in _reported:  # une seule fois par ensemble de clés
        _reported.add(key)
        log.warning("réglages ignorés (valeurs par défaut utilisées) : %s", ", ".join(bad))
    return out


def save_settings(s):
    core.atomic_write_json(settings_path(), s)
