"""État du terminal intégré gardé d'un lancement à l'autre de l'application.

~/.claude-accounts/terminals.json (600), écrit de façon atomique ; un fichier illisible
ou d'un format inattendu est ignoré (valeurs par défaut) puis remplacé à l'écriture
suivante, une entrée d'onglet inattendue est sautée :

    {"version": 2,
     "options": {"auto_resume": true, "reopen_at_start": false},
     "saved_at": 1793000000.0,
     "selected": 0,
     "tabs": [{"kind": "claude", "cwd": "/home/u/Work/App", "title": "Export CSV",
               "session_id": "0f3c…", "extra_args": ["--model", "opus"],
               "queue": ["lance les tests"],
               "chat": {"model": "opus", "effort": null, "ultracode": false, "rights": null}},
              {"kind": "shell", "cwd": "/home/u", "title": "Terminal · ~",
               "session_id": null, "extra_args": [], "queue": []}]}

Version 2 (phase 12) : un onglet claude porte `chat` (options du chat : modèle, effort,
ultracode, droits ; None = réglage par défaut) et le fichier porte `panes` (largeurs des
volets de l'espace de session, par disposition A ou B, arbre visible, volet de gauche).
Un fichier de version 1 se lit sans perte : valeurs par défaut pour ce qui manque.

`options` : interrupteurs du menu « ⋮ » de la page Terminaux (reprise automatique après
une limite, onglets rouverts au démarrage). `tabs` : onglets ouverts, dans l'ordre ;
`selected` : celui qui était affiché ; `queue` : messages en attente de l'onglet.
"""

import json
import re
import time

from . import core

VERSION = 2
DEFAULT_CHAT = {"model": None, "effort": None, "ultracode": False, "rights": None}
DEFAULT_PANES = {"A": {"tree": 240, "side": 460}, "B": {"tree": 240, "side": 460},
                 "tree_visible": True, "left": "fichiers"}
LEFT_VALUES = ("fichiers", "feuille")
DEFAULT_OPTIONS = {"auto_resume": True, "reopen_at_start": False}
KINDS = ("claude", "shell")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


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


def _strings(value):
    return [v for v in value if isinstance(v, str) and v] if isinstance(value, list) else []


def _opt_str(value):
    return value if isinstance(value, str) and value else None


def _abs_path(value):
    return value if isinstance(value, str) and value.startswith("/") else None


def _chat(raw):
    raw = raw if isinstance(raw, dict) else {}
    chat = {"model": _opt_str(raw.get("model")), "effort": _opt_str(raw.get("effort")),
            "ultracode": raw["ultracode"] if isinstance(raw.get("ultracode"), bool) else False,
            "rights": _opt_str(raw.get("rights"))}
    # dossier du projet de l'espace et feuille de route suivie : gardés seulement s'ils servent
    for key in ("root", "roadmap"):
        value = _abs_path(raw.get(key))
        if value:
            chat[key] = value
    return chat


def _entry(raw):
    """Entrée d'onglet normalisée, ou None si elle est inutilisable."""
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
        return None
    cwd = raw.get("cwd")
    if not isinstance(cwd, str) or not cwd.startswith("/"):
        return None
    sid = raw.get("session_id")
    claude = raw["kind"] == "claude"
    entry = {"kind": raw["kind"], "cwd": cwd,
             "title": raw["title"] if isinstance(raw.get("title"), str) else "",
             "session_id": sid if claude and isinstance(sid, str) and SAFE_ID.match(sid) else None,
             "extra_args": _strings(raw.get("extra_args")) if claude else [],
             "queue": _strings(raw.get("queue")) if claude else []}
    if claude:
        entry["chat"] = _chat(raw.get("chat"))
    return entry


def load_tabs():
    """(onglets enregistrés, indice de celui qui était affiché ou None)."""
    data = _read()
    raw = data.get("tabs")
    tabs = [e for e in (_entry(r) for r in raw) if e is not None] if isinstance(raw, list) else []
    selected = data.get("selected")
    ok = isinstance(selected, int) and not isinstance(selected, bool) and 0 <= selected < len(tabs)
    return tabs, selected if ok else None


def save_tabs(tabs, selected=None):
    """Enregistre les onglets (les options sont gardées) ; False en cas d'échec."""
    data = _read()
    data.update(tabs=[e for e in (_entry(t) for t in tabs) if e is not None],
                selected=selected, saved_at=time.time())
    return _write(data)


def _width(value, default):
    ok = isinstance(value, int) and not isinstance(value, bool) and 0 < value <= 10000
    return value if ok else default


def _panes(raw):
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for layout in ("A", "B"):
        sub = raw.get(layout) if isinstance(raw.get(layout), dict) else {}
        out[layout] = {k: _width(sub.get(k), v) for k, v in DEFAULT_PANES[layout].items()}
    out["tree_visible"] = (raw["tree_visible"] if isinstance(raw.get("tree_visible"), bool)
                           else DEFAULT_PANES["tree_visible"])
    out["left"] = raw["left"] if raw.get("left") in LEFT_VALUES else DEFAULT_PANES["left"]
    return out


def load_panes():
    """Largeurs des volets de l'espace de session ; valeurs par défaut pour ce qui manque."""
    return _panes(_read().get("panes"))


def save_panes(panes):
    """Enregistre les volets (le reste du fichier est gardé) ; False en cas d'échec."""
    data = _read()
    data["panes"] = _panes(panes)
    return _write(data)
