"""Archive des conversations Claude Code.

Claude Code efface les conversations de plus de `cleanupPeriodDays` jours (30 par
défaut, d'après la date de modification des fichiers de `~/.claude/projects`). Ce
module en garde une copie compressée, dans `${XDG_DATA_HOME:-~/.local/share}/ccs/archive`
(dossier 700, fichiers 600) :

    archive/index.json                     identifiant, dossier, titre, date, taille…
    archive/<projet>/<session>.jsonl.gz    le journal
    archive/<projet>/<session>.dir.tar.gz  son dossier frère (sous-agents…), s'il existe

Seules les conversations inchangées depuis `idle_days` sont copiées, et une copie est
refaite si l'original a bougé depuis. Un passage (`archive_pass`, appelé par le
service toutes les 30 min dans un fil) copie au plus MAX_FILES fichiers ou MAX_BYTES
octets, les plus anciens d'abord (ce sont eux que Claude Code effacera en premier) :
le premier archivage s'étale sur plusieurs passages. Les originaux ne sont jamais
modifiés. `restore` remet une conversation à sa place avec une date de modification
« maintenant », sinon Claude Code l'effacerait de nouveau aussitôt.
"""

import gzip
import json
import os
import shutil
import tarfile
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from . import conversations, core, sessions

INDEX_VERSION = 1
MAX_FILES = 20
MAX_BYTES = 100 * 1024 * 1024
DAY_S = 86400
DEFAULTS = {"enabled": True, "idle_days": 1, "max_age_days": 0}


def archive_dir():
    base = os.environ.get("XDG_DATA_HOME") or str(core.paths().home / ".local" / "share")
    return Path(base) / "ccs" / "archive"


def index_path():
    return archive_dir() / "index.json"


def config(settings=None):
    """Réglages « archive » (valeurs par défaut si absents ou invalides)."""
    raw = (settings or {}).get("archive") if isinstance(settings, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULTS)
    if isinstance(raw.get("enabled"), bool):
        out["enabled"] = raw["enabled"]
    for key in ("idle_days", "max_age_days"):
        v = raw.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
            out[key] = v
    return out


def _mkdir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


# ---- index ---------------------------------------------------------------------------

_memo = {"stamp": None, "items": {}}


def load_index():
    """{clé « projet/session »: élément}. Un index absent ou illisible vaut un index vide."""
    path = index_path()
    try:
        st = path.stat()
    except OSError:
        _memo.update(stamp=None, items={})
        return {}
    stamp = (st.st_mtime_ns, st.st_size)
    if _memo["stamp"] != stamp:
        data = core.load_json(path)
        items = data.get("items") if data.get("version") == INDEX_VERSION else None
        _memo.update(stamp=stamp, items=items if isinstance(items, dict) else {})
    return dict(_memo["items"])


def save_index(items):
    _mkdir(archive_dir())
    core.atomic_write_json(index_path(), {"version": INDEX_VERSION, "items": items})
    _memo["stamp"] = None


def items():
    """Conversations archivées, de la plus récente à la plus ancienne."""
    return sorted(load_index().values(), key=lambda i: i.get("updated_at") or 0, reverse=True)


def _key(slug, sid):
    return f"{slug}/{sid}"


def _journal_file(item):
    return archive_dir() / item["slug"] / f"{item['id']}.jsonl.gz"


def _dir_file(item):
    return archive_dir() / item["slug"] / f"{item['id']}.dir.tar.gz"


def journal_path(item):
    """Emplacement d'origine du journal (où `restore` le remet)."""
    return sessions.projects_dir() / item["slug"] / f"{item['id']}.jsonl"


def find(session_id, cwd=None):
    """Élément archivé d'une conversation (le plus récent ; celui du dossier `cwd` d'abord)."""
    found = [i for i in load_index().values() if i.get("id") == session_id]
    if not found:
        return None
    if cwd:
        slug = sessions.project_slug(cwd)
        same = [i for i in found if i.get("slug") == slug]
        found = same or found
    return max(found, key=lambda i: i.get("updated_at") or 0)


def item_for_path(path):
    """Élément archivé dont `path` est l'emplacement d'origine du journal, ou None."""
    p = Path(path)
    return load_index().get(_key(p.parent.name, p.stem))


# ---- signature d'un original ---------------------------------------------------------

def _dir_sig(journal):
    """(nombre de fichiers, taille totale, plus grande date) du dossier frère, ou None."""
    d = journal.with_suffix("")
    if not d.is_dir():
        return None
    count = size = newest = 0
    for root, _dirs, files in os.walk(d):
        for name in files:
            try:
                st = os.stat(os.path.join(root, name))
            except OSError:
                continue
            count += 1
            size += st.st_size
            newest = max(newest, st.st_mtime_ns)
    return [count, size, newest] if count else None


def _stamp(journal):
    st = journal.stat()
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "dir_sig": _dir_sig(journal)}


def _same(item, stamp):
    return (item.get("size") == stamp["size"] and item.get("mtime_ns") == stamp["mtime_ns"]
            and item.get("dir_sig") == stamp["dir_sig"])


# ---- copie ---------------------------------------------------------------------------

def _gzip_copy(src, dest):
    tmp = dest.with_name(dest.name + ".ccs-tmp")
    try:
        with open(src, "rb") as fin, open(tmp, "wb") as raw:
            os.chmod(tmp, 0o600)
            with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, mtime=0) as gz:
                shutil.copyfileobj(fin, gz, 1024 * 1024)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()


def _tar_dir(src_dir, dest):
    tmp = dest.with_name(dest.name + ".ccs-tmp")
    try:
        with open(tmp, "wb") as raw:
            os.chmod(tmp, 0o600)
            with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, mtime=0) as gz:
                with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
                    tar.add(src_dir, arcname=src_dir.name)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()


def _archive_one(journal, now):
    """Copie un journal (et son dossier frère) ; renvoie l'élément d'index, ou None si
    l'original a bougé pendant la copie (réessayé au passage suivant)."""
    slug = journal.parent.name
    before = _stamp(journal)
    entry = conversations.read_entry(journal)
    conv = conversations._to_conversation(journal, entry)
    dest = archive_dir() / slug
    _mkdir(dest)
    _gzip_copy(journal, dest / f"{journal.stem}.jsonl.gz")
    sibling = journal.with_suffix("")
    dir_file = dest / f"{journal.stem}.dir.tar.gz"
    if before["dir_sig"] is not None:
        _tar_dir(sibling, dir_file)
    elif dir_file.exists():
        dir_file.unlink()
    if _stamp(journal) != before:
        return None
    packed = (dest / f"{journal.stem}.jsonl.gz").stat().st_size
    if dir_file.exists():
        packed += dir_file.stat().st_size
    return {"id": journal.stem, "slug": slug, "cwd": conv.cwd, "title": conv.title,
            "first_prompt": conv.first_prompt, "last_prompt": conv.last_prompt,
            "prompts": conv.prompts, "started_at": conv.started_at, "origin": conv.origin,
            "git_branch": conv.git_branch, "updated_at": before["mtime_ns"] / 1e9,
            "archived_at": now, "packed": packed, **before}


@dataclass
class PassResult:
    archived: list = field(default_factory=list)   # identifiants copiés pour la première fois
    updated: list = field(default_factory=list)    # identifiants recopiés (l'original avait bougé)
    pending: int = 0                               # à copier aux passages suivants
    bytes: int = 0                                 # octets d'originaux lus
    errors: list = field(default_factory=list)     # (identifiant, message)
    pruned: list = field(default_factory=list)     # identifiants supprimés par le ménage

    @property
    def changed(self):
        return bool(self.archived or self.updated or self.pruned)


def archive_pass(now=None, idle_days=1, max_age_days=0, max_files=MAX_FILES, max_bytes=MAX_BYTES):
    """Un passage : copie les conversations inchangées depuis `idle_days` jours (nouvelles
    ou modifiées depuis leur copie), dans la limite de `max_files` fichiers ou `max_bytes`
    octets. `max_age_days` > 0 : les conversations plus vieilles ne sont pas copiées."""
    now = time.time() if now is None else now
    result = PassResult()
    root = sessions.projects_dir()
    candidates = []
    for path in root.glob("*/*.jsonl") if root.is_dir() else ():
        try:
            st = path.stat()
        except OSError:
            continue
        if now - st.st_mtime < idle_days * DAY_S:
            continue
        if max_age_days and now - st.st_mtime > max_age_days * DAY_S:
            continue
        candidates.append((st.st_mtime, path))
    candidates.sort(key=lambda c: c[0])      # les plus anciens d'abord
    index = load_index()
    dirty = False
    try:
        for _mtime, path in candidates:
            key = _key(path.parent.name, path.stem)
            try:
                stamp = _stamp(path)
            except OSError:
                continue
            old = index.get(key)
            if old and _same(old, stamp):
                continue
            if len(result.archived) + len(result.updated) >= max_files or (
                    result.bytes and result.bytes + stamp["size"] > max_bytes):
                result.pending += 1
                continue
            try:
                item = _archive_one(path, now)
            except (OSError, ValueError) as e:
                result.errors.append((path.stem, str(e)))
                continue
            result.bytes += stamp["size"]
            if item is None:
                result.pending += 1
                continue
            (result.updated if old else result.archived).append(path.stem)
            index[key] = item
            dirty = True
    finally:
        if dirty:
            save_index(index)
    return result


# ---- ménage, suppression -------------------------------------------------------------

def remove(session_id, slug=None):
    """Supprime l'archive d'une conversation ; renvoie le nombre de copies supprimées."""
    index = load_index()
    gone = [k for k, i in index.items()
            if i.get("id") == session_id and (slug is None or i.get("slug") == slug)]
    for key in gone:
        item = index.pop(key)
        for f in (_journal_file(item), _dir_file(item)):
            try:
                f.unlink()
            except FileNotFoundError:
                pass
    if gone:
        save_index(index)
    return len(gone)


def prune(max_age_days, now=None):
    """Ménage : supprime les archives dont la conversation date de plus de `max_age_days`
    jours (0 : sans limite, rien n'est supprimé). Renvoie les identifiants supprimés."""
    if not max_age_days:
        return []
    now = time.time() if now is None else now
    old = [i for i in load_index().values()
           if now - (i.get("updated_at") or 0) > max_age_days * DAY_S]
    done = []
    for item in old:
        if remove(item["id"], item["slug"]):
            done.append(item["id"])
    return done


def tick(now=None, settings=None, max_files=MAX_FILES, max_bytes=MAX_BYTES):
    """Un tour du service (toutes les 30 min, dans un fil) : passage d'archivage puis
    ménage. Ne fait rien si l'archive est désactivée. Renvoie un PassResult."""
    cfg = config(settings)
    if not cfg["enabled"]:
        return PassResult()
    now = time.time() if now is None else now
    result = archive_pass(now, cfg["idle_days"], cfg["max_age_days"], max_files, max_bytes)
    result.pruned = prune(cfg["max_age_days"], now)
    return result


# ---- lecture -------------------------------------------------------------------------

def total_size():
    """Taille de l'archive sur le disque, en octets (copies et index)."""
    total = 0
    for root, _dirs, files in os.walk(archive_dir()):
        for name in files:
            try:
                total += os.stat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def stats():
    """(nombre de conversations archivées, taille sur le disque en octets)."""
    return len(load_index()), total_size()


def search(query="", project=None):
    """Éléments archivés dont le titre, les demandes, le dossier ou la branche contiennent
    chaque mot de `query` (sans accents ni casse) ; `project` : dossier exact."""
    words = conversations.fold(query).split()
    out = []
    for item in items():
        if project and item.get("cwd") != project:
            continue
        hay = conversations.fold(" ".join(str(item.get(k) or "") for k in
                                          ("title", "first_prompt", "last_prompt", "cwd", "git_branch")))
        if all(w in hay for w in words):
            out.append(item)
    return out


def open_journal(path):
    """Ouvre un journal en lecture binaire : le fichier s'il existe, sinon sa copie
    archivée décompressée à la volée. FileNotFoundError si aucun des deux."""
    p = Path(path)
    if p.is_file():
        return open(p, "rb")
    item = item_for_path(p)
    if item is not None and _journal_file(item).is_file():
        return gzip.open(_journal_file(item), "rb")
    raise FileNotFoundError(2, "No such file or directory", str(path))


@contextmanager
def extracted(item):
    """Copie temporaire décompressée (journal et dossier frère) pour les outils qui lisent
    un fichier du disque (coût…) ; rend le chemin du journal, supprimé à la sortie."""
    tmp = Path(tempfile.mkdtemp(prefix="ccs-archive-"))
    try:
        dest = tmp / item["slug"]
        dest.mkdir()
        _gunzip(_journal_file(item), dest / f"{item['id']}.jsonl")
        if _dir_file(item).is_file():
            _untar(_dir_file(item), dest)
        yield dest / f"{item['id']}.jsonl"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _gunzip(src, dest):
    with gzip.open(src, "rb") as fin, open(dest, "wb") as fout:
        shutil.copyfileobj(fin, fout, 1024 * 1024)


def _untar(src, dest):
    """Extrait un `.dir.tar.gz` dans `dest` ; refuse tout ce qui sortirait du dossier."""
    base = os.path.realpath(dest)
    with tarfile.open(src, "r:gz") as tar:
        for m in tar.getmembers():
            target = os.path.realpath(os.path.join(base, m.name))
            if not (m.isfile() or m.isdir()) or not target.startswith(base + os.sep):
                raise ValueError(f"élément refusé dans l'archive : {m.name}")
        tar.extractall(base, filter="data") if hasattr(tarfile, "data_filter") else tar.extractall(base)


# ---- restauration --------------------------------------------------------------------

def _touch_tree(path, when):
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files + dirs:
            try:
                os.utime(os.path.join(root, name), (when, when))
            except OSError:
                pass
    os.utime(path, (when, when))


def restore(session_id, cwd=None, now=None):
    """Remet la conversation archivée à sa place (`~/.claude/projects/<projet>/<id>.jsonl`
    et son dossier frère), avec une date de modification « maintenant ». Un journal déjà
    présent n'est jamais écrasé. Renvoie le chemin du journal ; FileNotFoundError si la
    conversation n'est pas archivée."""
    item = find(session_id, cwd)
    if item is None:
        raise FileNotFoundError(f"conversation {session_id} absente de l'archive")
    now = time.time() if now is None else now
    journal = journal_path(item)
    if journal.is_file():
        return journal
    if not _journal_file(item).is_file():
        raise FileNotFoundError(f"copie archivée introuvable pour {session_id}")
    journal.parent.mkdir(parents=True, exist_ok=True)
    tmp = journal.with_name(journal.name + ".ccs-tmp")
    try:
        _gunzip(_journal_file(item), tmp)
        os.utime(tmp, (now, now))
        os.replace(tmp, journal)
    finally:
        if tmp.exists():
            tmp.unlink()
    if _dir_file(item).is_file():
        _restore_dir(item, journal, now)
    # Le journal restauré est identique à la copie : pas de recopie au prochain passage.
    index = load_index()
    key = _key(item["slug"], item["id"])
    if key in index:
        index[key] = {**index[key], **_stamp(journal)}
        save_index(index)
    return journal


def _restore_dir(item, journal, now):
    sibling = journal.with_suffix("")
    tmp = Path(tempfile.mkdtemp(prefix="ccs-restore-", dir=journal.parent))
    try:
        _untar(_dir_file(item), tmp)
        src = tmp / item["id"]
        for root, _dirs, files in os.walk(src):
            rel = Path(root).relative_to(src)
            (sibling / rel).mkdir(parents=True, exist_ok=True)
            for name in files:
                target = sibling / rel / name
                if not target.exists():
                    shutil.move(os.path.join(root, name), target)
        if sibling.is_dir():
            _touch_tree(sibling, now)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
