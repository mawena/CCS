"""Version du protocole du pont et table des anciens noms (avant la 1.0.0).

Les applications Android et iPhone déjà installées appellent encore les anciens noms de méthode
et de paramètre : le pont les accepte en les ramenant ici aux nouveaux (`normalize`). Une
connexion qui ne déclare pas de version (`hello {protocol}` sur le socket, `?protocol=` sur
`/api/ws`) est un ancien client : `legacy(conn)` le dit, pour les quelques réponses dont les
valeurs (et non les clés) ont changé.

Dans l'autre sens, une connexion relayée vers une autre machine dont le pont est plus ancien
(son `hello` ne renvoie pas `protocol`) reçoit les anciens noms (`to_legacy`) et ses réponses
sont complétées des nouvelles clés (`upgrade_result`).

Compatibilité 1.x, à retirer en 2.0 : `METHOD_ALIASES`, `PARAM_ALIASES` et ce qui s'en sert.
"""

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
    """(méthode, paramètres) aux anciens noms, pour le pont d'une machine plus ancienne."""
    old = _LEGACY_METHODS.get(method, method)
    renames = PARAM_ALIASES.get(method)
    if renames:
        params = dict(params)
        for old_key, new_key in renames.items():
            if new_key in params:
                params.setdefault(old_key, params.pop(new_key))
    return old, params


def upgrade_result(method, result):
    """Réponse d'un ancien pont complétée des nouvelles clés."""
    if not isinstance(result, dict):
        return result
    if method == "conversations.trash" and "tid" in result:
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
