"""État du terminal intégré gardé d'un lancement à l'autre de l'application.

~/.claude-accounts/terminals.json (600), écrit de façon atomique ; un fichier illisible
ou d'un format inattendu est ignoré (valeurs par défaut) puis remplacé à l'écriture
suivante :

    {"version": 1,
     "options": {"auto_resume": true, "reopen_at_start": false}}

`options` : interrupteurs du menu « ⋮ » de la page Terminaux (reprise automatique après
une limite, onglets rouverts au démarrage).
"""

import json

from . import core

VERSION = 1
DEFAULT_OPTIONS = {"auto_resume": True, "reopen_at_start": False}


def path():
    return core.paths().store / "terminals.json"


def _read():
    try:
        with open(path()) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data):
    try:
        core.atomic_write_json(path(), {**data, "version": VERSION})
        return True
    except (OSError, TypeError, ValueError):
        return False


def _options(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {k: raw[k] if isinstance(raw.get(k), bool) else v for k, v in DEFAULT_OPTIONS.items()}


def load_options():
    return _options(_read().get("options"))


def save_options(options):
    """Enregistre les interrupteurs (le reste du fichier est gardé) ; False en cas d'échec."""
    data = _read()
    data["options"] = _options({**_options(data.get("options")), **(options or {})})
    return _write(data)
