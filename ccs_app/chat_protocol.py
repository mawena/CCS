"""Protocole stream-json de Claude Code (`claude -p --input-format stream-json`), sans GTK.

Les formes viennent de l'essai réel du 12/11/2026 (Claude Code 2.1.322), qui prime sur la
documentation publique : voir `docs/superpowers/specs/2026-11-12-phase-12-design.md`.

- `parse_line(ligne)` transforme une ligne de stdout en événements (dataclasses gelées) ;
  elle ne lève jamais d'exception ;
- `user_message`, `control`, `allow`, `allow_always`, `deny` fabriquent les lignes à écrire
  sur stdin (JSON terminé par un saut de ligne, ASCII pur : aucun séparateur Unicode ne
  peut couper la ligne).
"""

import base64
import json
import logging
import re
from dataclasses import dataclass, field

from . import task_runner

log = logging.getLogger(__name__)

# Outil de tâches de Claude Code (liste de choses à faire).
TODO_TOOLS = ("TodoWrite",)
# Sous-types `system` sans intérêt pour le chat (sorties de hooks énormes, compteurs).
IGNORED_SYSTEM = frozenset({"hook_started", "hook_response", "hook_progress", "thinking_tokens"})


# ----------------------------------------------------------------------------- événements

@dataclass(frozen=True)
class Init:
    """`system/init` : émis à chaque message envoyé, pas au démarrage."""
    session_id: str
    model: str
    permission_mode: str
    slash_commands: tuple = ()


@dataclass(frozen=True)
class Hello:
    """Réponse à `initialize`.

    `commands` : ((nom, description, indice d'argument), …) ;
    `models` : ((valeur, libellé, description, niveaux d'effort), …).
    """
    commands: tuple = ()
    models: tuple = ()
    permission_mode: str = ""
    capabilities: tuple = ()


@dataclass(frozen=True)
class Status:
    """`system/status` portant un changement de mode de permissions."""
    permission_mode: str


@dataclass(frozen=True)
class LocalCommand:
    """Résultat d'une commande locale (`/effort`…) : aucun appel au modèle."""
    text: str


@dataclass(frozen=True)
class TextDelta:
    msg_id: str
    index: int
    text: str


@dataclass(frozen=True)
class AssistantText:
    msg_id: str
    text: str
    parent_id: str | None = None     # texte d'un sous-agent (outil Task/Agent qui l'a lancé)


@dataclass(frozen=True)
class Thinking:
    msg_id: str


@dataclass(frozen=True)
class ToolUse:
    tool_id: str
    name: str
    input: dict = field(default_factory=dict)
    parent_id: str | None = None


@dataclass(frozen=True)
class ToolResult:
    tool_id: str
    text: str
    is_error: bool = False
    parent_id: str | None = None


@dataclass(frozen=True)
class TaskNotice:
    """Avis de fin d'un travail d'arrière-plan (sous-agent, commande) : la CLI le remet à Claude
    comme un message « <task-notification> ». `tool_id` : l'appel d'outil qui l'avait lancé."""
    tool_id: str
    status: str = ""
    summary: str = ""


@dataclass(frozen=True)
class Todos:
    """Liste de tâches de Claude : ((texte, état), …), état = pending|in_progress|completed."""
    items: tuple = ()


@dataclass(frozen=True)
class PermissionRequest:
    request_id: str
    tool_name: str
    display_name: str
    input: dict = field(default_factory=dict)
    suggestions: list = field(default_factory=list)
    description: str = ""
    blocked_path: str | None = None
    agent_id: str | None = None      # demande venue d'un sous-agent


@dataclass(frozen=True)
class ControlReply:
    request_id: str
    ok: bool
    data: dict = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class TurnResult:
    ok: bool
    subtype: str
    cost_usd: float = 0.0
    turn_usage: dict = field(default_factory=dict)
    context_window: int | None = None
    text: str = ""
    is_limit: bool = False
    interrupted: bool = False


@dataclass(frozen=True)
class Compacted:
    pre_tokens: int | None
    trigger: str


@dataclass(frozen=True)
class Retrying:
    attempt: int
    delay_s: float


@dataclass(frozen=True)
class Unknown:
    raw: dict


# ----------------------------------------------------------------------------- lecture

def _str(value, default=""):
    return value if isinstance(value, str) else default


def _dict(value):
    return value if isinstance(value, dict) else {}


def _number(value, default=0):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _text_of(content):
    """Texte d'un `content` de tool_result : une chaîne, ou une liste de blocs `text`."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif block.get("type") == "image":
                    parts.append("[image]")
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return "" if content is None else str(content)


def _parent(ev):
    parent = ev.get("parent_tool_use_id")
    return parent if isinstance(parent, str) and parent else None


def _hello(ev, data):
    commands = tuple(
        (_str(c.get("name")), _str(c.get("description")), _str(c.get("argumentHint")))
        for c in data.get("commands", ()) if isinstance(c, dict) and c.get("name"))
    models = tuple(
        (_str(m.get("value")), _str(m.get("displayName")) or _str(m.get("value")),
         _str(m.get("description")), tuple(e for e in m.get("supportedEffortLevels") or () if isinstance(e, str)))
        for m in data.get("models", ()) if isinstance(m, dict) and m.get("value"))
    capabilities = tuple(c for c in data.get("capabilities") or () if isinstance(c, str))
    return Hello(commands, models, _str(data.get("current_permission_mode")), capabilities)


def _control_response(ev):
    response = _dict(ev.get("response"))
    data = _dict(response.get("response"))
    if "commands" in data and "models" in data:
        return [_hello(ev, data)]
    ok = response.get("subtype") == "success"
    error = response.get("error")
    return [ControlReply(_str(response.get("request_id")), ok, data,
                         None if ok else (str(error) if error is not None else "erreur inconnue"))]


def _control_request(ev):
    request = _dict(ev.get("request"))
    if request.get("subtype") != "can_use_tool":
        return [Unknown(ev)]
    suggestions = request.get("permission_suggestions")
    tool = _str(request.get("tool_name"))
    blocked = request.get("blocked_path")
    return [PermissionRequest(
        request_id=_str(ev.get("request_id")),
        tool_name=tool,
        display_name=_str(request.get("display_name")) or tool,
        input=_dict(request.get("input")),
        suggestions=list(suggestions) if isinstance(suggestions, list) else [],
        description=_str(request.get("description")),
        blocked_path=blocked if isinstance(blocked, str) and blocked else None,
        agent_id=_str(request.get("agent_id")) or None)]


def _system(ev):
    sub = ev.get("subtype")
    if sub == "init":
        return [Init(_str(ev.get("session_id")), _str(ev.get("model")), _str(ev.get("permissionMode")),
                     tuple(s for s in ev.get("slash_commands") or () if isinstance(s, str)))]
    if sub == "status":
        mode = ev.get("permissionMode")
        return [Status(mode)] if isinstance(mode, str) and mode else []
    if sub == "compact_boundary":
        meta = _dict(ev.get("compact_metadata"))
        pre = meta.get("pre_tokens", ev.get("pre_tokens"))
        return [Compacted(pre if isinstance(pre, int) else None,
                          _str(meta.get("trigger") or ev.get("trigger")))]
    if sub == "api_retry":
        delay = ev.get("retry_delay_ms")
        delay_s = _number(delay) / 1000 if delay is not None else _number(ev.get("delay_s"))
        return [Retrying(int(_number(ev.get("attempt"))), float(delay_s))]
    if sub in IGNORED_SYSTEM:
        return []
    return [Unknown(ev)]


def _stream_event(ev):
    inner = _dict(ev.get("event"))
    kind = inner.get("type")
    msg_id = _str(ev.get("api_message_id")) or _str(_dict(inner.get("message")).get("id"))
    if kind == "content_block_delta":
        delta = _dict(inner.get("delta"))
        if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
            return [TextDelta(msg_id, int(_number(inner.get("index"))), delta["text"])]
        return []
    if kind == "content_block_start" and _dict(inner.get("content_block")).get("type") == "thinking":
        return [Thinking(msg_id)]
    return []


def _todos(tool_input):
    items = []
    for item in _dict(tool_input).get("todos") or ():
        if isinstance(item, dict):
            items.append((_str(item.get("content")) or _str(item.get("activeForm")),
                          _str(item.get("status"), "pending")))
    return Todos(tuple(items))


def _assistant(ev):
    if ev.get("local_command_run") or ev.get("local_command_source"):
        return []   # le texte arrive avec le `result` de la commande locale (LocalCommand)
    message = _dict(ev.get("message"))
    msg_id = _str(message.get("id"))
    parent = _parent(ev)
    out = []
    content = message.get("content")
    if isinstance(content, str):
        return [AssistantText(msg_id, content, parent)] if content else []
    for block in content if isinstance(content, list) else ():
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text" and isinstance(block.get("text"), str):
            out.append(AssistantText(msg_id, block["text"], parent))
        elif kind == "thinking":
            out.append(Thinking(msg_id))
        elif kind == "tool_use":
            tool_input = _dict(block.get("input"))
            name = _str(block.get("name"))
            out.append(ToolUse(_str(block.get("id")), name, tool_input, parent))
            if name in TODO_TOOLS:
                out.append(_todos(tool_input))
    return out


_NOTICE_RE = re.compile(r"<task-notification>(.*?)</task-notification>", re.S)


def _notice_field(body, tag):
    m = re.search(rf"<{tag}>(.*?)</{tag}>", body, re.S)
    return m.group(1).strip() if m else ""


def task_notices(text):
    """Les avis « <task-notification> » d'un texte, en `TaskNotice` (sans `tool-use-id` : ignoré)."""
    out = []
    for m in _NOTICE_RE.finditer(text or ""):
        body = m.group(1)
        tool_id = _notice_field(body, "tool-use-id")
        if tool_id:
            out.append(TaskNotice(tool_id, _notice_field(body, "status"), _notice_field(body, "summary")))
    return out


def _user(ev):
    parent = _parent(ev)
    content = _dict(ev.get("message")).get("content")
    out = []
    if isinstance(content, str):
        out += task_notices(content)
    for block in content if isinstance(content, list) else ():
        if isinstance(block, dict) and block.get("type") == "tool_result":
            out.append(ToolResult(_str(block.get("tool_use_id")), _text_of(block.get("content")),
                                  bool(block.get("is_error")), parent))
        elif isinstance(block, dict) and block.get("type") == "text":
            out += task_notices(_str(block.get("text")))
    return out


def _context_window(ev):
    for key in ("model_usage_since_last_result", "modelUsage"):
        windows = [_number(u.get("contextWindow"), None) for u in _dict(ev.get(key)).values()
                   if isinstance(u, dict)]
        windows = [w for w in windows if w]
        if windows:
            return int(max(windows))
    return None


def _result(ev):
    text = _str(ev.get("result"))
    if ev.get("local_command"):
        return [LocalCommand(text)]
    subtype = _str(ev.get("subtype"))
    return [TurnResult(
        ok=subtype == "success" and not ev.get("is_error"),
        subtype=subtype,
        cost_usd=float(_number(ev.get("total_cost_usd"))),
        turn_usage=_dict(ev.get("model_usage_since_last_result")),
        context_window=_context_window(ev),
        text=text,
        is_limit=bool(task_runner.is_limit_event(ev)),
        interrupted=ev.get("terminal_reason") == "aborted_streaming")]


def _rate_limit(ev):
    # Seule une limite atteinte intéresse le chat ; les `allowed` sont du bruit.
    return [Unknown(ev)] if task_runner.is_limit_event(ev) else []


_HANDLERS = {
    "system": _system,
    "stream_event": _stream_event,
    "assistant": _assistant,
    "user": _user,
    "result": _result,
    "control_request": _control_request,
    "control_response": _control_response,
    "rate_limit_event": _rate_limit,
}


def parse_line(line):
    """Événements d'une ligne de stdout. Jamais d'exception : ligne illisible → []."""
    try:
        ev = json.loads(line)
    except (TypeError, ValueError):
        log.debug("ligne illisible ignorée : %.200r", line)
        return []
    if not isinstance(ev, dict):
        log.debug("ligne non objet ignorée : %.200r", line)
        return []
    handler = _HANDLERS.get(ev.get("type"))
    try:
        return handler(ev) if handler else [Unknown(ev)]
    except Exception:   # forme inattendue : on garde la ligne brute plutôt que de planter
        log.debug("forme inattendue : %.200r", line, exc_info=True)
        return [Unknown(ev)]


# ----------------------------------------------------------------------------- écriture

def _line(obj):
    return json.dumps(obj, separators=(",", ":")) + "\n"


def user_message(text, images=()):
    """Message utilisateur ; `images` : suite de (media_type, octets)."""
    content = [{"type": "text", "text": text}]
    for media_type, data in images or ():
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": media_type, "data": base64.b64encode(data).decode("ascii")}})
    return _line({"type": "user", "message": {"role": "user", "content": content},
                  "parent_tool_use_id": None})


def control(subtype, request_id, **fields):
    """Requête de contrôle (`initialize`, `interrupt`, `set_model`, `get_context_usage`…)."""
    return _line({"type": "control_request", "request_id": request_id,
                  "request": {"subtype": subtype, **fields}})


def _permission_reply(request_id, response):
    return _line({"type": "control_response", "response": {
        "subtype": "success", "request_id": request_id, "response": response}})


def allow(request_id, input):
    return _permission_reply(request_id, {"behavior": "allow", "updatedInput": input})


def allow_always(request_id, input, suggestions):
    """« Toujours » : ne garde que les règles `addRules`. Les suggestions `setMode` et
    `addDirectories`, appliquées d'un coup, élargiraient bien plus que la commande."""
    rules = [s for s in suggestions or () if isinstance(s, dict) and s.get("type") == "addRules"]
    response = {"behavior": "allow", "updatedInput": input}
    if rules:
        response["updatedPermissions"] = rules
    return _permission_reply(request_id, response)


def deny(request_id, message, interrupt=False):
    response = {"behavior": "deny", "message": message}
    if interrupt:
        response["interrupt"] = True
    return _permission_reply(request_id, response)


def control_error(request_id, message):
    """Réponse d'erreur à une `control_request` de la CLI que CCS ne sait pas traiter : elle
    reçoit une réponse au lieu d'attendre sans fin."""
    return _line({"type": "control_response", "response": {
        "subtype": "error", "request_id": request_id, "error": message}})
