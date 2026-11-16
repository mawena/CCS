"""Étiquettes sur les messages d'un chat : un ou plusieurs mots-clés (« important », « à revoir »…)
posés sur un message pour le retrouver ensuite.

Un fichier par conversation, `etiquettes/<session_id>.json` dans le dossier de CCS :

    {"messages": {"<identifiant>": {"tags": ["important"], "role": "assistant",
                                    "excerpt": "début du message…", "ts": 1763300000.0}}}

L'identifiant d'un message est le même en direct et à la relecture du journal : celui de la
réponse (`msg_…`) pour Claude, celui de la ligne du journal (uuid, fourni à l'envoi) pour
l'utilisateur. L'extrait permet de lister les messages étiquetés sans relire le journal.
Un fichier illisible vaut « aucune étiquette », sans exception.
"""

import json
import os
import re
import tempfile
import threading
import time

from . import core

MAX_TAGS = 10            # par message
MAX_TAG_CHARS = 40
EXCERPT_CHARS = 160
ROLES = ("utilisateur", "assistant")

_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_MSG_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_:.-]{0,127}")
_lock = threading.Lock()


def folder():
    return core.paths().store / "etiquettes"


def valid_session(session_id):
    return isinstance(session_id, str) and bool(_SESSION_ID.fullmatch(session_id))


def valid_message(msg_id):
    return isinstance(msg_id, str) and bool(_MSG_ID.fullmatch(msg_id))


def path_of(session_id):
    if not valid_session(session_id):
        raise ValueError(f"conversation invalide : {session_id!r}")
    return folder() / f"{session_id}.json"


def clean_tag(tag):
    """Une étiquette propre (espaces réduits, longueur bornée), ou "" si elle est vide."""
    if not isinstance(tag, str):
        return ""
    return " ".join(tag.replace(",", " ").split())[:MAX_TAG_CHARS].strip()


def clean_tags(tags):
    """Étiquettes propres, sans doublon (sans tenir compte de la casse), dans l'ordre donné."""
    out, seen = [], set()
    for tag in tags if isinstance(tags, (list, tuple)) else ():
        tag = clean_tag(tag)
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            out.append(tag)
    return out[:MAX_TAGS]


def parse(text):
    """Étiquettes tapées par l'utilisateur, séparées par des virgules."""
    return clean_tags(text.split(",")) if isinstance(text, str) else []


def excerpt(text):
    """Début du message sur une ligne, pour la liste des messages étiquetés."""
    one = " ".join(str(text or "").split())
    return one if len(one) <= EXCERPT_CHARS else one[:EXCERPT_CHARS - 1].rstrip() + "…"


def _entry(raw):
    if not isinstance(raw, dict):
        return None
    tags = clean_tags(raw.get("tags"))
    if not tags:
        return None
    ts = raw.get("ts")
    return {"tags": tags, "role": raw.get("role") if raw.get("role") in ROLES else "",
            "excerpt": excerpt(raw.get("excerpt")),
            "ts": float(ts) if isinstance(ts, (int, float)) and not isinstance(ts, bool) else 0.0}


def load(session_id):
    """{identifiant: entrée} des messages étiquetés de la conversation."""
    try:
        data = json.loads(path_of(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    msgs = data.get("messages") if isinstance(data, dict) else None
    out = {}
    for msg_id, raw in (msgs.items() if isinstance(msgs, dict) else ()):
        entry = _entry(raw)
        if entry and valid_message(msg_id):
            out[msg_id] = entry
    return out


def _write(path, messages):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not messages:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"messages": messages}, f, indent=1, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def set_tags(session_id, msg_id, tags, text="", role="", clock=time.time):
    """Pose les étiquettes `tags` sur le message (liste vide : les retire toutes). `text` : le
    message, dont on garde un extrait (sinon l'extrait déjà connu). Rend l'entrée, ou None."""
    if not valid_message(msg_id):
        raise ValueError(f"message invalide : {msg_id!r}")
    path = path_of(session_id)
    tags = clean_tags(tags)
    with _lock:
        messages = load(session_id)
        old = messages.get(msg_id) or {}
        if tags:
            messages[msg_id] = {
                "tags": tags, "role": role if role in ROLES else old.get("role", ""),
                "excerpt": excerpt(text) if str(text or "").strip() else old.get("excerpt", ""),
                "ts": old.get("ts") or float(clock())}
        else:
            messages.pop(msg_id, None)
        _write(path, messages)
    return messages.get(msg_id)


def by_tag(messages):
    """[(étiquette, [(identifiant, entrée), …]), …] : étiquettes par ordre alphabétique (sans tenir
    compte de la casse : « Important » rejoint « important »), messages dans l'ordre où ils ont été
    étiquetés."""
    groups = {}
    for msg_id, entry in sorted(messages.items(), key=lambda kv: kv[1].get("ts") or 0):
        for tag in entry["tags"]:
            groups.setdefault(tag.casefold(), (tag, []))[1].append((msg_id, entry))
    return sorted(groups.values(), key=lambda kv: kv[0].casefold())


def known_tags(limit=30):
    """Étiquettes déjà utilisées dans toutes les conversations, les plus fréquentes d'abord
    (suggestions à la saisie)."""
    count = {}
    try:
        files = sorted(folder().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:200]
    except OSError:
        return []
    for path in files:
        for entry in load(path.stem).values() if valid_session(path.stem) else ():
            for tag in entry["tags"]:
                key = tag.casefold()
                n, name = count.get(key, (0, tag))
                count[key] = (n + 1, name)
    ranked = sorted(count.values(), key=lambda v: (-v[0], v[1].casefold()))
    return [name for _n, name in ranked[:limit]]
