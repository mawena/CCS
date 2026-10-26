"""Réglages utilisateur (~/.claude-accounts/settings.json), fusionnés avec les défauts."""

import copy

from . import core

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
        "resets": True,
        "auth": True,
        "sessions": True,
    },
    "poll": {"normal_s": 300, "fast_s": 60},
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


def load_settings():
    return _merge(DEFAULTS, core.load_json(settings_path()))


def save_settings(s):
    core.atomic_write_json(settings_path(), s)
