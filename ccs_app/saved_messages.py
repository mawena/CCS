"""Messages enregistrés : des textes qu'on envoie souvent, communs à tous les projets
(`messages.json` dans le dossier de CCS) ou propres à un projet (`.ccs/messages.json`).

Format : `[{"name": "...", "text": "..."}]`. Un fichier illisible donne une liste vide, sans
exception. Si un nom existe des deux côtés, celui du projet gagne.
"""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import core

SCOPES = ("global", "projet")


@dataclass
class Saved:
    name: str
    text: str
    scope: str            # "global" ou "projet"


def global_path():
    return core.paths().store / "messages.json"


def project_path(project_dir):
    return Path(project_dir) / ".ccs" / "messages.json"


def _read(path, scope):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("name"), str) \
                and isinstance(item.get("text"), str) and item["name"].strip():
            out.append(Saved(item["name"].strip(), item["text"], scope))
    return out


def load(project_dir=None):
    """Messages communs puis messages du projet (le projet remplace un commun de même nom)."""
    mine = _read(project_path(project_dir), "projet") if project_dir else []
    taken = {s.name for s in mine}
    return [s for s in _read(global_path(), "global") if s.name not in taken] + mine


def save(scope, items, project_dir=None):
    """Écrit (atomiquement) les messages de la portée `scope` ; crée `.ccs/` au besoin."""
    if scope not in SCOPES:
        raise ValueError(f"portée inconnue : {scope!r}")
    if scope == "projet":
        if not project_dir:
            raise ValueError("pas de dossier de projet")
        path = project_path(project_dir)
    else:
        path = global_path()
    data = [{"name": s.name, "text": s.text} for s in items if s.scope == scope]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
