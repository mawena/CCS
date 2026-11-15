"""Événements du chat en JSON, et retour. Le pont envoie ce que `ChatEngine` émet ; le bureau
distant reconstruit exactement les mêmes objets que s'il tournait en local."""

import dataclasses

from .. import chat_engine, chat_protocol as proto


@dataclasses.dataclass(frozen=True)
class PermissionSettled:
    """Une autorisation a été réglée (sur cet appareil ou un autre) : les cartes disparaissent."""
    request_id: str
    decision: str = ""


@dataclasses.dataclass(frozen=True)
class Notice:
    """Note du pont, écrite dans le fil de tous les appareils (compactage automatique)."""
    text: str
    kind: str = "info"           # info | warning | error


def _collect():
    out = {}
    for mod in (proto, chat_engine):
        for name, obj in vars(mod).items():
            if isinstance(obj, type) and dataclasses.is_dataclass(obj) and \
                    obj.__module__ == mod.__name__ and name != "ChatSession":
                out[name] = obj
    out["PermissionSettled"] = PermissionSettled
    out["Notice"] = Notice
    return out


TYPES = _collect()


def _plain(value):
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return value


def _tuples(value):
    """Listes JSON → tuples (champs déclarés en tuple), sans entrer dans les dict."""
    if isinstance(value, list):
        return tuple(_tuples(v) for v in value)
    return value


def to_json(ev):
    d = {"type": type(ev).__name__}
    for f in dataclasses.fields(ev):
        d[f.name] = _plain(getattr(ev, f.name))
    return d


def from_json(d):
    cls = TYPES.get(d.get("type")) if isinstance(d, dict) else None
    if cls is None:
        return proto.Unknown(dict(d) if isinstance(d, dict) else {"value": d})
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name not in d:
            continue
        value = d[f.name]
        if isinstance(f.default, tuple):
            value = _tuples(value)
        kwargs[f.name] = value
    try:
        return cls(**kwargs)
    except TypeError:
        return proto.Unknown(dict(d))
