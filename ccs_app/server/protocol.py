"""Version du protocole du pont et table des anciens noms (avant la 1.0.0).

Les applications Android et iPhone déjà installées appellent encore les anciens noms de méthode
et de paramètre : le pont les accepte en les ramenant ici aux nouveaux (`normalize`). Une
connexion qui ne déclare pas de version (`hello {protocol}` sur le socket, `?protocol=` sur
`/api/ws`) est un ancien client : `legacy(conn)` le dit, pour les quelques réponses dont les
valeurs (et non les clés) ont changé.

Dans l'autre sens, une connexion relayée vers une autre machine dont le pont est plus ancien
(son `hello` ne renvoie pas `protocol`) reçoit les anciens noms (`to_legacy`) et ses réponses
sont complétées des nouvelles clés (`upgrade_result`).

Valeurs renommées (rôles des messages et des étiquettes, « utilisateur » → « user », « outil » →
« tool ») : un ancien client reçoit les anciennes (`downgrade_result`, `event_data`), une réponse
ou un événement d'un ancien pont est ramené aux nouvelles (`upgrade_result`, `upgrade_event`).

Compatibilité 1.x, à retirer en 2.0 : `METHOD_ALIASES`, `PARAM_ALIASES`, les conversions de
valeurs et ce qui s'en sert.
"""

from .. import message_tags, preview

PROTOCOL = 1

# ancien nom → nouveau nom
METHOD_ALIASES = {
    "machine.attach": "machines.attach",
    "conversation.messages": "conversations.messages",
    "conversation.rename": "conversations.rename",
    "conversation.cost": "conversations.cost",
    "conversation.trash": "conversations.trash",
    "conversation.trash_list": "trash.list",
    "conversation.restore": "trash.restore",
    "roadmap.task_prompt": "roadmap.prompt",
    "phone.new_topic": "phone.renew",
    "work.saved.list": "saved.list",
    "work.saved.save": "saved.save",
    "work.saved.delete": "saved.delete",
    "work.shell.run": "shell.run",
    "work.shell.poll": "shell.poll",
    "work.shell.stop": "shell.stop",
    "work.undo_file": "work.undo",
    "work.rewind_plan": "rewind.plan",
    "work.rewind_apply": "rewind.apply",
}

# nouvelle méthode → {ancien paramètre: nouveau paramètre}
PARAM_ALIASES = {
    "trash.restore": {"tid": "trash_id"},
    "machines.limit": {"limite": "limit"},
    "machines.configure": {"relais": "relay", "jeton": "token"},
}

# événements renommés : ancien nom → nouveau nom
EVENT_ALIASES = {
    "work.shell": "shell.done",
    "machine.ready": "machines.ready",
}

_LEGACY_METHODS = {new: old for old, new in METHOD_ALIASES.items()}


def normalize(method, params):
    """(méthode, paramètres) aux nouveaux noms ; un nouveau nom passe tel quel. Un paramètre
    donné sous les deux noms garde la valeur du nouveau."""
    method = METHOD_ALIASES.get(method, method)
    renames = PARAM_ALIASES.get(method)
    if renames and any(old in params for old in renames):
        params = dict(params)
        for old, new in renames.items():
            if old in params:
                value = params.pop(old)
                params.setdefault(new, value)
    return method, params


def to_legacy(method, params):
    """(méthode, paramètres) aux anciens noms (et anciennes valeurs), pour le pont d'une machine
    plus ancienne."""
    old = _LEGACY_METHODS.get(method, method)
    renames = PARAM_ALIASES.get(method)
    if renames:
        params = dict(params)
        for old_key, new_key in renames.items():
            if new_key in params:
                params.setdefault(old_key, params.pop(new_key))
    if method == "chat.tag" and params.get("role") in message_tags.LEGACY_ROLES:
        params = dict(params, role=message_tags.LEGACY_ROLES[params["role"]])
    return old, params


def _roles(messages, table):
    """Messages (`conversations.messages`) avec leur rôle passé par `table`."""
    out = []
    for m in messages or ():
        if isinstance(m, dict) and m.get("role") in table:
            m = dict(m, role=table[m["role"]])
        out.append(m)
    return out


def _tag_entries(messages, convert):
    """{identifiant: entrée} des étiquettes (`chat.tags`) passées par `convert`."""
    if not isinstance(messages, dict):
        return messages
    return {k: convert(v) for k, v in messages.items()}


def _upgrade_entry(entry):
    if isinstance(entry, dict) and entry.get("role") in message_tags.OLD_ROLES:
        return dict(entry, role=message_tags.OLD_ROLES[entry["role"]])
    return entry


def upgrade_result(method, result):
    """Réponse d'un ancien pont complétée des nouvelles clés et ramenée aux nouvelles valeurs."""
    if not isinstance(result, dict):
        return result
    if method == "conversations.messages" and isinstance(result.get("messages"), list):
        result["messages"] = _roles(result["messages"], preview.OLD_ROLES)
    elif method == "chat.tags":
        result["messages"] = _tag_entries(result.get("messages"), _upgrade_entry)
    elif method == "chat.tag" and "entry" in result:
        result["entry"] = _upgrade_entry(result["entry"])
    elif method == "conversations.trash" and "tid" in result:
        result.setdefault("trash_id", result["tid"])
    elif method == "trash.list":
        for item in result.get("items") or ():
            if isinstance(item, dict):
                item.setdefault("trash_id", item.get("tid"))
                item.setdefault("session_id", item.get("id"))
    return result


def client_protocol(value):
    """Version déclarée par un client (0 : ancien client, sans version)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def legacy(conn):
    """Vrai pour un ancien client (aucune version de protocole déclarée)."""
    return not (getattr(conn, "peer", None) or {}).get("protocol")


_LEGACY_EVENTS = {new: old for old, new in EVENT_ALIASES.items()}


def event_for(conn, name):
    """Nom d'un événement pour cette connexion : le nouveau, ou l'ancien pour un ancien client
    (un nom ancien venu d'un pont plus ancien est d'abord ramené au nouveau)."""
    name = EVENT_ALIASES.get(name, name)
    return _LEGACY_EVENTS.get(name, name) if legacy(conn) else name


# ---- valeurs : anciennes pour un ancien client, nouvelles depuis un ancien pont ---------------

def _downgrade_entry(entry):
    return message_tags.legacy_entry(entry)


def downgrade_result(conn, method, result):
    """Réponse pour cette connexion : telle quelle, ou avec les anciennes valeurs françaises pour
    un ancien client (rôles des messages et des étiquettes). Ne modifie pas `result`."""
    if not legacy(conn) or not isinstance(result, dict):
        return result
    if method == "conversations.messages" and isinstance(result.get("messages"), list):
        return dict(result, messages=_roles(result["messages"], preview.LEGACY_ROLES))
    if method == "chat.tags" and isinstance(result.get("messages"), dict):
        return dict(result, messages=_tag_entries(result["messages"], _downgrade_entry))
    if method == "chat.tag" and "entry" in result:
        return dict(result, entry=_downgrade_entry(result["entry"]))
    return result


def upgrade_event(name, data):
    """Événement d'un ancien pont ramené aux nouvelles valeurs."""
    if EVENT_ALIASES.get(name, name) == "chat.tags" and isinstance(data, dict) and "entry" in data:
        return dict(data, entry=_upgrade_entry(data["entry"]))
    return data


def event_data(conn, name, data):
    """Données d'un événement pour cette connexion (anciennes valeurs pour un ancien client).
    Ne modifie pas `data`, partagé entre les connexions."""
    if name == "chat.tags" and legacy(conn) and isinstance(data, dict) and "entry" in data:
        return dict(data, entry=_downgrade_entry(data["entry"]))
    return data
