"""Historique des fichiers de Claude Code : changements d'une session et retour en arrière.

Claude Code garde, pour chaque message de l'utilisateur, une copie des fichiers qu'il suit
(format observé, non documenté) : lignes du journal de la conversation

    {"type": "file-history-snapshot", "messageId": <uuid du message>, "isSnapshotUpdate": bool,
     "snapshot": {"messageId", "timestamp",
                  "trackedFileBackups": {<chemin absolu>: {"backupFileName": "<hash>@v<n>" | null,
                                                           "version": n, "backupTime": iso}}}}

Une ligne `isSnapshotUpdate: true` remplace l'instantané de même `messageId`. Les copies sont
dans `<dossier de config>/file-history/<session>/<backupFileName>` ; `backupFileName: null`
veut dire que le fichier n'existait pas. Si ce format change, `read` renvoie None et rien n'est
proposé (voir `check`, repris par `ccs doctor`).

Limite connue : les copies sont des états d'AVANT un message ; l'état laissé par la dernière
modification de Claude n'a pas de copie. `user_edited` est donc vrai pour un fichier dont le
contenu ne correspond à aucune copie : il peut signaler à tort une modification de Claude
faite après le dernier instantané. La confirmation le dit, rien n'est écrit sans accord.
"""

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import core

SNAPSHOT_TYPE = "file-history-snapshot"
CHECK_FILES = 40       # journaux examinés par `check` (les plus récents)


@dataclass
class Backup:
    path: str
    name: str | None
    version: int


@dataclass
class Snapshot:
    message_id: str
    time: str
    files: dict = field(default_factory=dict)       # chemin → Backup


@dataclass
class Change:
    path: str
    before: bytes | None
    now: bytes | None


@dataclass
class Step:
    path: str
    content: bytes | None        # None : supprimer le fichier
    user_edited: bool


class NoSnapshot(LookupError):
    """Ce message n'a pas d'instantané : l'état des fichiers d'avant lui est inconnu."""


def _config_dir():
    return core.paths().config_dir


def _parse(entry):
    """Snapshot d'une ligne `file-history-snapshot`, ou None si elle ne suit pas le format."""
    snap = entry.get("snapshot")
    if not isinstance(snap, dict):
        return None
    mid = entry.get("messageId") or snap.get("messageId")
    tracked = snap.get("trackedFileBackups")
    if not isinstance(mid, str) or not isinstance(tracked, dict):
        return None
    files = {}
    for path, info in tracked.items():
        if not isinstance(path, str) or not isinstance(info, dict) or "backupFileName" not in info:
            return None
        name = info["backupFileName"]
        if name is not None and not isinstance(name, str):
            return None
        version = info.get("version")
        files[path] = Backup(path, name, version if isinstance(version, int) else 0)
    return Snapshot(mid, str(snap.get("timestamp") or ""), files)


def read(transcript):
    """Instantanés du journal, dans l'ordre ; [] s'il n'y en a aucun ; None si des lignes
    `file-history-snapshot` existent mais qu'aucune ne suit le format (format inconnu)."""
    snaps, seen_candidate = [], False
    try:
        with open(transcript, encoding="utf-8", errors="replace") as f:
            for line in f:
                if SNAPSHOT_TYPE not in line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(entry, dict) or entry.get("type") != SNAPSHOT_TYPE:
                    continue
                seen_candidate = True
                snap = _parse(entry)
                if snap is None:
                    continue
                same = next((i for i, s in enumerate(snaps) if s.message_id == snap.message_id),
                            None)
                if same is not None:
                    snaps[same] = snap          # mise à jour : remplace, garde la place
                else:
                    snaps.append(snap)
    except OSError:
        return []
    if seen_candidate and not snaps:
        return None
    return snaps


@dataclass
class UserMessage:
    message_id: str
    text: str
    time: str


def _user_text(message):
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p)
    return ""


def user_messages(transcript):
    """Messages de l'utilisateur du journal, dans l'ordre (pas les résultats d'outils, ni les
    entrées de méta-données) : le k-ième du fil de chat est le k-ième de cette liste."""
    out = []
    try:
        with open(transcript, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"user"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(entry, dict) or entry.get("type") != "user" \
                        or entry.get("isMeta") or entry.get("isSidechain") \
                        or not isinstance(entry.get("uuid"), str):
                    continue
                text = _user_text(entry.get("message"))
                if text.strip():
                    out.append(UserMessage(entry["uuid"], text, str(entry.get("timestamp") or "")))
    except OSError:
        return []
    return out


def backup_text(session_id, backup):
    """Contenu d'une copie ; None si le fichier n'existait pas ou si la copie a disparu."""
    if backup.name is None:
        return None
    try:
        return (_config_dir() / "file-history" / session_id / backup.name).read_bytes()
    except OSError:
        return None


def _current(path):
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def _backups_by_path(snaps):
    out = {}
    for s in snaps:
        for path, b in s.files.items():
            out.setdefault(path, []).append(b)
    return out


def _content(session_id, backup):
    """(connu, contenu) : une copie perdue n'est pas « connue »."""
    if backup.name is None:
        return True, None
    data = backup_text(session_id, backup)
    return data is not None, data


def changes(snaps, session_id):
    """Fichiers dont le contenu actuel diffère de leur état d'avant la conversation (plus
    ancienne copie connue)."""
    out = []
    for path, backups in _backups_by_path(snaps).items():
        known, before = _content(session_id, backups[0])
        if not known:
            continue
        now = _current(path)
        if before != now:
            out.append(Change(path, before, now))
    return out


def rewind_plan(snaps, session_id, message_id):
    """Ce qu'il faut écrire pour revenir à l'état d'avant `message_id`. Pour chaque fichier
    suivi : la copie de l'instantané de ce message si elle existe ; sinon (suivi pour la
    première fois après ce message) sa plus ancienne copie. Seuls les fichiers qui changent.
    Lève `NoSnapshot` si ce message n'a pas d'instantané (sans lui, tout reviendrait à l'état
    d'avant la conversation)."""
    target_snap = next((s for s in snaps if s.message_id == message_id), None)
    if target_snap is None:
        raise NoSnapshot(message_id)
    steps = []
    for path, backups in _backups_by_path(snaps).items():
        backup = target_snap.files.get(path)
        known, content = _content(session_id, backup or backups[0])
        if not known:
            continue
        now = _current(path)
        if content == now:
            continue
        states = [c for ok, c in (_content(session_id, b) for b in backups) if ok]
        steps.append(Step(path, content, now not in states))
    return steps


def apply(steps):
    """Écrit ou supprime ; chaque écriture passe par un fichier temporaire du même dossier
    puis `os.replace`."""
    for step in steps:
        if step.content is None:
            try:
                os.unlink(step.path)
            except FileNotFoundError:
                pass
            continue
        folder = os.path.dirname(step.path) or "."
        os.makedirs(folder, exist_ok=True)
        try:
            mode = os.stat(step.path).st_mode & 0o7777
        except OSError:
            mode = None
        fd, tmp = tempfile.mkstemp(prefix=".ccs-", dir=folder)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(step.content)
            if mode is not None:
                os.chmod(tmp, mode)
            os.replace(tmp, step.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def check():
    """(ok, texte) pour `ccs doctor` : lit le journal le plus récent qui contient des
    instantanés."""
    root = _config_dir() / "projects"
    try:
        files = sorted(root.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        files = []
    for path in files[:CHECK_FILES]:
        snaps = read(path)
        if snaps is None:
            return False, "format inconnu : l'historique des fichiers de Claude Code a changé"
        if snaps:
            return True, "format reconnu"
    return True, "aucun historique de fichiers à vérifier"
