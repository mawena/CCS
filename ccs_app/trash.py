"""Corbeille des conversations : une conversation supprimée reste restaurable 30 jours.

    ${XDG_DATA_HOME:-~/.local/share}/ccs/trash/<session>-<heure>/
        meta.json        {"id", "cwd", "title", "trashed_at", "files": [[origine, nom], …],
                          "archive": [élément de l'index de l'archive, …]}
        <nom>            journal, dossier frère (sous-agents…), copies de fichiers, archives

Tout est déplacé (rien n'est copié puis effacé) : le journal et son dossier frère sous
`~/.claude/projects`, les copies de fichiers de la session (`file-history/<session>`) et les
copies de l'archive de CCS (sinon la conversation y reviendrait). `restore` remet tout en
place et refuse d'écraser un fichier revenu entre-temps. `purge` efface ce qui a plus de
`DAYS` jours (appelé par le service de fond).
"""

import json
import os
import shutil
import time
from pathlib import Path

from . import archive, core, file_history, sessions

DAYS = 30
DAY_S = 86400


class TrashError(Exception):
    pass


def trash_dir():
    return core.ccs_dir("data") / "trash"


def _mkdir(p):
    p.mkdir(mode=0o700, parents=True, exist_ok=True)


def put(journal, session_id, cwd="", title="", now=None):
    """Met une conversation à la corbeille ; `journal` : son emplacement d'origine (le fichier
    peut ne plus exister si seule l'archive la garde). Renvoie l'identifiant de l'élément."""
    now = time.time() if now is None else now
    journal = Path(journal)
    sources = [journal, journal.with_suffix(""),
               file_history._config_dir() / "file-history" / session_id]
    index = archive.load_index()
    arch = [(k, i) for k, i in index.items() if i.get("id") == session_id
            and i.get("slug") == journal.parent.name]
    arch_files = [f for _k, i in arch for f in (archive._journal_file(i), archive._dir_file(i))]
    if not any(p.exists() for p in sources + arch_files):
        raise TrashError("Conversation introuvable.")
    tid = f"{session_id}-{int(now)}"
    folder = trash_dir() / tid
    _mkdir(folder)
    files = []
    for n, src in enumerate(sources + arch_files):
        if src.exists():
            name = f"{n}-{src.name}"
            shutil.move(str(src), str(folder / name))
            files.append([str(src), name])
    if arch:
        for k, _i in arch:
            index.pop(k, None)
        archive.save_index(index)
    meta = {"id": session_id, "cwd": cwd, "title": title, "trashed_at": now, "files": files,
            "archive": [i for _k, i in arch]}
    core.atomic_write_json(folder / "meta.json", meta)
    return tid


def items():
    """Éléments de la corbeille, du plus récent au plus ancien (avec leur identifiant `tid`)."""
    out = []
    root = trash_dir()
    for d in root.iterdir() if root.is_dir() else ():
        meta = core.load_json(d / "meta.json")
        if isinstance(meta, dict) and isinstance(meta.get("files"), list):
            out.append({**meta, "tid": d.name})
    out.sort(key=lambda m: -(m.get("trashed_at") or 0))
    return out


def _folder(tid):
    if not isinstance(tid, str) or not tid or "/" in tid or tid.startswith("."):
        raise TrashError("Élément inconnu.")
    folder = trash_dir() / tid
    if not (folder / "meta.json").is_file():
        raise TrashError("Élément inconnu.")
    return folder


def restore(tid):
    folder = _folder(tid)
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    pairs = [(Path(orig), folder / name) for orig, name in meta.get("files") or []]
    if any(orig.exists() for orig, _ in pairs):
        raise TrashError("Un fichier de cette conversation existe de nouveau : rien n'est remis.")
    for orig, here in pairs:
        if here.exists():
            orig.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(here), str(orig))
    if meta.get("archive"):
        index = archive.load_index()
        for item in meta["archive"]:
            index[archive._key(item["slug"], item["id"])] = item
        archive.save_index(index)
    shutil.rmtree(folder, ignore_errors=True)
    return meta


def purge(now=None, days=DAYS):
    """Efface les éléments mis à la corbeille il y a plus de `days` jours ; renvoie leur nombre."""
    now = time.time() if now is None else now
    gone = 0
    for m in items():
        if now - (m.get("trashed_at") or 0) > days * DAY_S:
            shutil.rmtree(trash_dir() / m["tid"], ignore_errors=True)
            gone += 1
    return gone


def transcript_ok(path, session_id):
    """Vrai si `path` est bien `<session>.jsonl` sous le dossier des projets de Claude Code."""
    projects = os.path.realpath(sessions.projects_dir())
    real = os.path.realpath(path)
    return (os.path.basename(real) == f"{session_id}.jsonl"
            and real.startswith(projects.rstrip("/") + "/"))
