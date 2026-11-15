"""Projets ajoutés ou retirés à la main (page Sessions, bureau et web).

La liste des projets vient des conversations de Claude Code ; ce fichier la corrige :

    ${XDG_DATA_HOME:-~/.local/share}/ccs/projects.json
    {"version": 1, "added": {<dossier>: <heure>}, "removed": {<dossier>: <heure>}}

Un projet ajouté apparaît même sans conversation. Un projet retiré disparaît de la liste avec
ses conversations, mais rien n'est effacé ; il revient de lui-même si une conversation plus
récente que son retrait apparaît, ou si une session y tourne.
"""

import os
import time
from pathlib import Path

from . import core

VERSION = 1


def path():
    base = os.environ.get("XDG_DATA_HOME") or str(core.paths().home / ".local" / "share")
    return Path(base) / "ccs" / "projects.json"


def _clean(raw):
    if not isinstance(raw, dict):
        return {}
    return {k: float(v) for k, v in raw.items()
            if isinstance(k, str) and os.path.isabs(k) and isinstance(v, (int, float))
            and not isinstance(v, bool)}


def load():
    """(ajoutés, retirés) : deux dict dossier → heure. Fichier absent ou illisible : vides."""
    data = core.load_json(path())
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return {}, {}
    return _clean(data.get("added")), _clean(data.get("removed"))


def _save(added, removed):
    p = path()
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    core.atomic_write_json(p, {"version": VERSION, "added": added, "removed": removed})


def _norm(cwd):
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        raise ValueError("dossier absolu attendu")
    return os.path.normpath(cwd)


def add(cwd, now=None):
    cwd = _norm(cwd)
    added, removed = load()
    added[cwd] = time.time() if now is None else now
    removed.pop(cwd, None)
    _save(added, removed)
    return cwd


def remove(cwd, now=None):
    cwd = _norm(cwd)
    added, removed = load()
    removed[cwd] = time.time() if now is None else now
    added.pop(cwd, None)
    _save(added, removed)
    return cwd


def hidden(removed, convs, found):
    """Dossiers retirés à masquer : sans session en cours ni conversation plus récente que le
    retrait."""
    if not removed:
        return set()
    running = {s.cwd for s in found}
    newer = {c.cwd for c in convs if c.cwd in removed and (c.updated_at or 0) > removed[c.cwd]}
    return {cwd for cwd in removed if cwd not in running and cwd not in newer}
