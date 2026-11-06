"""Aperçu d'une conversation Claude Code sans la reprendre, et export en Markdown.

Lecture seule du journal `~/.claude/projects/<projet>/<id>.jsonl`, en flux (une ligne
à la fois, même pour un journal de plusieurs centaines de Mo). On garde :
  - les demandes tapées par l'utilisateur (`origin.kind` « human » ou absent) ;
  - le texte des réponses de l'assistant (les blocs d'une même réponse sont réunis) ;
  - les appels d'outils, résumés en une ligne (nom + cible principale), avec leur
    résultat raccourci (affiché replié, ou omis) ;
  - deux repères : conversation compactée, demande interrompue.
Tout le reste est ignoré : réflexion (`thinking`), messages méta ou injectés par
Claude Code (contexte de l'IDE, rappels système, sorties de commandes locales,
notifications de tâches, messages d'autres agents), titres, fils latéraux
(`isSidechain`), copies de requêtes (`api-request-*`), lignes illisibles.
"""

import json
import re
import unicodedata
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import core, sessions

USER, ASSISTANT, TOOL, NOTE = "utilisateur", "assistant", "outil", "note"

TARGET_MAX = 120
RESULT_MAX = 2000
MAX_LINE_BYTES = 4_000_000          # au-delà, une ligne de résultat d'outil n'est pas décodée
KEEP_TOOL_IDS = 2000                # appels gardés en mémoire pour y rattacher leur résultat

# Balises injectées par Claude Code ou l'IDE : retirées avec leur contenu.
INJECTED_TAGS = ("system-reminder", "ide_opened_file", "ide_selection", "ide_diagnostics",
                 "local-command-stdout", "local-command-stderr", "local-command-caveat",
                 "command-message", "task-notification", "bash-stdout", "bash-stderr",
                 "user-prompt-submit-hook")
INJECTED_RE = re.compile(r"<(%s)\b[^>]*>.*?(?:</\1>|\Z)" % "|".join(map(re.escape, INJECTED_TAGS)), re.S)
COMMAND_RE = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.S)
COMMAND_ARGS_RE = re.compile(r"<command-args>\s*(.*?)\s*</command-args>", re.S)
BASH_INPUT_RE = re.compile(r"<bash-input>\s*(.*?)\s*</bash-input>", re.S)
# Balises autour d'un texte bien tapé (collé, demande passée par le navigateur) : on garde le texte.
UNWRAP_RE = re.compile(r"<(pasted_content|browser_instruction)\b[^>]*>(.*?)</\1>", re.S)
IMAGE_NOTE_RE = re.compile(r"^\[Image(?: #\d+)?(?:: [^\]]*)?\]$")
INTERRUPTED = "[Request interrupted by user"
OTHER_LINE_TYPES = b'{"type":"'
KEPT_LINE_TYPES = (b'{"type":"user"', b'{"type":"assistant"', b'{"type":"system"')


@dataclass
class ToolCall:
    name: str
    target: str = ""
    tool_id: str = ""
    result: str | None = None
    is_error: bool = False

    @property
    def label(self):
        """Nom lisible : « rea · open_binary » pour un outil MCP."""
        if self.name.startswith("mcp__"):
            parts = self.name.split("__")[1:]
            return " · ".join(p for p in parts if p) or self.name
        return self.name


@dataclass
class Message:
    role: str                    # USER | ASSISTANT | TOOL | NOTE
    text: str
    ts: float | None = None
    tool: ToolCall | None = None
    msg_id: str = ""             # identifiant de la réponse (réunion des blocs)


# ---- lecture -------------------------------------------------------------------------

def _ts(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _short(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _first_line(text):
    lines = [line.strip() for line in str(text).strip().splitlines() if line.strip()]
    return lines[0] if lines else ""


def tool_target(name, inp):
    """Cible principale d'un appel d'outil, en une ligne."""
    if not isinstance(inp, dict):
        return ""
    get = lambda key: inp.get(key) if isinstance(inp.get(key), str) else ""  # noqa: E731
    if name == "Bash":
        target = _first_line(get("command"))
    elif name in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
        target = get("file_path") or get("notebook_path")
    elif name == "Grep":
        target = get("pattern") + (f" dans {get('path')}" if get("path") else "")
    elif name == "Glob":
        target = get("pattern") + (f" dans {get('path')}" if get("path") else "")
    elif name == "WebFetch":
        target = get("url")
    elif name in ("WebSearch", "ToolSearch"):
        target = get("query")
    elif name in ("Agent", "Task"):
        target = get("description") or _first_line(get("prompt"))
    elif name == "Skill":
        target = get("skill")
    elif name == "TodoWrite":
        target = "liste de tâches"
    elif name == "AskUserQuestion":
        qs = inp.get("questions")
        q = qs[0] if isinstance(qs, list) and qs and isinstance(qs[0], dict) else {}
        target = _first_line(q.get("question") or "")
    else:
        target = next((_first_line(v) for v in inp.values() if isinstance(v, str) and v.strip()), "")
    return _short(target, TARGET_MAX)


def _result_text(content, limit):
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and isinstance(b.get("text"), str):
                parts.append(b["text"])
            elif b.get("type") == "image":
                parts.append("[image]")
        text = "\n".join(parts)
    else:
        text = ""
    return _short(text.strip(), limit)


def _user_text(text):
    """Texte tapé par l'utilisateur dans un bloc, sans ce que Claude Code y injecte."""
    cmd = COMMAND_RE.search(text)
    if cmd:
        args = COMMAND_ARGS_RE.search(text)
        name = cmd.group(1)
        return f"{name} {args.group(1)}".strip() if args and args.group(1) else name
    bash = BASH_INPUT_RE.search(text)
    if bash:
        return f"! {bash.group(1)}"
    text = INJECTED_RE.sub("", text)
    text = UNWRAP_RE.sub(lambda m: m.group(2).strip(), text).strip()
    if not text or text.startswith(sessions.INJECTED_PREFIXES):
        return ""
    if IMAGE_NOTE_RE.match(text):
        return ""
    return text


class _Reader:
    def __init__(self, limit, results, max_result_chars):
        self.out = deque(maxlen=limit) if limit else []
        self.results = results
        self.max_result_chars = max_result_chars
        self.tools = OrderedDict()   # id -> ToolCall (pour rattacher les résultats)
        self.seen = set()            # uuid des lignes déjà lues (lignes recopiées)

    def add(self, msg):
        last = self.out[-1] if self.out else None
        if (msg.role == ASSISTANT and last is not None and last.role == ASSISTANT
                and msg.msg_id and last.msg_id == msg.msg_id):
            last.text = f"{last.text}\n\n{msg.text}"
            return
        self.out.append(msg)

    def line(self, d):
        if not isinstance(d, dict) or d.get("isSidechain"):
            return
        uid = d.get("uuid")
        if uid:
            if uid in self.seen:
                return
            self.seen.add(uid)
        kind = d.get("type")
        if kind == "user":
            self.user(d)
        elif kind == "assistant":
            self.assistant(d)
        elif kind == "system" and d.get("subtype") == "compact_boundary":
            self.add(Message(NOTE, "Conversation compactée : la suite repart d'un résumé.", _ts(d.get("timestamp"))))

    def user(self, d):
        if d.get("isMeta") or d.get("isCompactSummary"):
            return
        msg = d.get("message") or {}
        content = msg.get("content")
        ts = _ts(d.get("timestamp"))
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
        if not isinstance(blocks, list):
            return
        origin = d.get("origin")
        human = not isinstance(origin, dict) or origin.get("kind") in (None, "human")
        parts, interrupted = [], False
        for b in blocks:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "tool_result":
                call = self.tools.get(b.get("tool_use_id"))
                if call is not None:
                    call.is_error = bool(b.get("is_error"))
                    if self.results:
                        call.result = _result_text(b.get("content"), self.max_result_chars)
            elif not human:
                continue
            elif t == "text" and isinstance(b.get("text"), str):
                if b["text"].strip().startswith(INTERRUPTED):
                    interrupted = True
                    continue
                text = _user_text(b["text"])
                if text:
                    parts.append(text)
            elif t == "image":
                parts.append("[image]")
        if parts:
            self.add(Message(USER, "\n\n".join(parts), ts))
        if interrupted:
            self.add(Message(NOTE, "Demande interrompue par l'utilisateur.", ts))

    def assistant(self, d):
        msg = d.get("message") or {}
        if msg.get("model") == "<synthetic>":
            return
        content = msg.get("content")
        if not isinstance(content, list):
            return
        ts = _ts(d.get("timestamp"))
        msg_id = str(msg.get("id") or "")
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text" and isinstance(b.get("text"), str) and b["text"].strip():
                role = NOTE if d.get("isApiErrorMessage") else ASSISTANT
                self.add(Message(role, b["text"].strip(), ts, msg_id=msg_id))
            elif t == "tool_use":
                name = str(b.get("name") or "?")
                call = ToolCall(name, tool_target(name, b.get("input")), str(b.get("id") or ""))
                if call.tool_id:
                    self.tools[call.tool_id] = call
                    while len(self.tools) > KEEP_TOOL_IDS:
                        self.tools.popitem(last=False)
                label = f"{call.label} · {call.target}" if call.target else call.label
                self.add(Message(TOOL, label, ts, tool=call, msg_id=msg_id))


def _wanted(raw):
    if raw.startswith(OTHER_LINE_TYPES) and not raw.startswith(KEPT_LINE_TYPES):
        return False  # titres, copies de requêtes, instantanés… : jamais décodés
    if b'"user"' not in raw and b'"assistant"' not in raw and b"compact_boundary" not in raw:
        return False
    return len(raw) <= MAX_LINE_BYTES or b'"tool_result"' not in raw


def read_messages(path, limit=None, results=True, max_result_chars=RESULT_MAX):
    """Messages lisibles du journal, dans l'ordre. `limit` : seulement les N derniers.
    `results` : rattacher (raccourci) le résultat de chaque appel d'outil.
    FileNotFoundError si le journal n'existe pas ; les lignes illisibles sont ignorées."""
    reader = _Reader(limit, results, max_result_chars)
    with open(path, "rb") as fh:
        for raw in fh:
            if not raw.endswith(b"\n"):
                break  # ligne en cours d'écriture
            if not _wanted(raw):
                continue
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            reader.line(d)
    return list(reader.out)


# ---- Markdown ------------------------------------------------------------------------

def _meta(meta, key, default=None):
    if meta is None:
        return default
    if isinstance(meta, dict):
        return meta.get(key, default)
    return getattr(meta, key, default)


def _date(ts, with_year=True):
    if not ts:
        return ""
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%d/%m/%Y à %H:%M" if with_year else "%d/%m %H:%M")


def code(text):
    """Texte en `code` Markdown, quels que soient les accents graves qu'il contient."""
    text = str(text).replace("\n", " ")
    runs = [len(m) for m in re.findall(r"`+", text)]
    fence = "`" * (max(runs) + 1 if runs else 1)
    pad = " " if text.startswith("`") or text.endswith("`") or fence != "`" else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _block(text):
    """Bloc de code clôturé, sûr même si le texte contient des ```."""
    runs = [len(m) for m in re.findall(r"`{3,}", text)]
    fence = "`" * max(3, max(runs) + 1 if runs else 3)
    return f"{fence}\n{text}\n{fence}"


def _short_path(path):
    home = str(core.paths().home)
    if path == home:
        return "~"
    return "~" + path[len(home):] if path and path.startswith(home + "/") else path


def to_markdown(conv_meta, messages, results=False, cost=None):
    """Document Markdown : titre, projet, dates, puis les échanges.
    `conv_meta` : une `conversations.Conversation`, un dict aux mêmes clés, ou None ;
    `cost` : coût déjà mis en forme (costs.format_cost), ajouté à l'en-tête s'il est donné."""
    title = _meta(conv_meta, "title") or "Conversation"
    cwd = _meta(conv_meta, "cwd") or ""
    out = [f"# {title}", ""]
    infos = []
    if cwd:
        infos.append(f"- Projet : **{sessions.project_name(cwd)}** — {code(_short_path(cwd))}")
    if _meta(conv_meta, "git_branch"):
        infos.append(f"- Branche : {code(_meta(conv_meta, 'git_branch'))}")
    if _meta(conv_meta, "started_at"):
        infos.append(f"- Début : {_date(_meta(conv_meta, 'started_at'))}")
    if _meta(conv_meta, "updated_at"):
        infos.append(f"- Dernière activité : {_date(_meta(conv_meta, 'updated_at'))}")
    if _meta(conv_meta, "session_id"):
        infos.append(f"- Conversation : {code(_meta(conv_meta, 'session_id'))}")
    if cost:
        infos.append(f"- Coût : {cost} (équivalent API)")
    if infos:
        out += infos + [""]
    out += ["---", ""]
    if not messages:
        out += ["*Aucun message lisible dans cette conversation.*", ""]
    previous = None
    for m in messages:
        when = f" — {_date(m.ts, with_year=False)}" if m.ts else ""
        if previous == TOOL and m.role != TOOL:
            out.append("")  # fin de la liste des appels d'outils
        if m.role == USER:
            out += [f"## Toi{when}", "", m.text, ""]
        elif m.role in (ASSISTANT, TOOL) and previous not in (ASSISTANT, TOOL):
            out += [f"## Claude{when}", ""]  # un seul titre par tour de l'assistant
        if m.role == ASSISTANT:
            out += [m.text, ""]
        elif m.role == TOOL:
            tool = m.tool or ToolCall(m.text)
            target = f" : {code(tool.target)}" if tool.target else ""
            error = " *(erreur)*" if tool.is_error else ""
            out.append(f"- {code(tool.label)}{target}{error}")
            if results and tool.result:
                out += ["", "  <details><summary>Résultat</summary>", "",
                        *(f"  {line}" if line else "" for line in _block(tool.result).splitlines()),
                        "", "  </details>", ""]
        elif m.role == NOTE:
            out += [f"> *{m.text}*", ""]
        previous = m.role
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).rstrip("\n") + "\n"


def markdown_for(conv, results=False, cost=None):
    """Markdown de toute la conversation (objet `conversations.Conversation`)."""
    return to_markdown(conv, read_messages(conv.path, results=results), results=results, cost=cost)


def export_markdown(conv, dest, results=False, cost=None):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = markdown_for(conv, results, cost)
    tmp = dest.with_name(dest.name + ".ccs-tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(dest)
    return dest


def suggested_filename(conv_meta):
    title = _meta(conv_meta, "title") or ""
    folded = unicodedata.normalize("NFKD", title)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch)).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:60].strip("-")
    return f"{slug or 'conversation'}.md"
