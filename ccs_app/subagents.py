"""Sous-agents d'un chat, dans l'ordre de leur lancement (pour Jarvis : « le premier sous-agent
de la session GliGli »).

Le pont fait passer chaque événement du moteur par `Subagents.feed` :
- `ToolUse` des outils `Task`/`Agent` : un sous-agent est lancé (description, type, de fond ou non) ;
- événement système `task_started` de la CLI (reçu en `Unknown`) : son `task_id`, nécessaire pour
  l'arrêter seul (`stop_task`) ; `task_updated` : changement d'état ;
- `ToolResult` : fin d'un sous-agent au premier plan (le résultat d'un sous-agent de fond ne dit
  que « lancé ») ; `TaskNotice` : fin d'un sous-agent de fond ;
- `StateChanged("stopped")` : la CLI est arrêtée, plus rien ne tourne.

États : `running`, `done`, `failed`, `stopped`. Au plus KEEP sous-agents gardés (les plus anciens
finis partent d'abord).
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

from . import chat_engine, chat_protocol as proto

AGENT_TOOLS = ("Task", "Agent")
KEEP = 200
FINAL_STATUS = {"completed": "done", "done": "done", "success": "done",
                "failed": "failed", "error": "failed",
                "killed": "stopped", "stopped": "stopped", "cancelled": "stopped",
                "canceled": "stopped", "aborted": "stopped"}


def _text(value, limit=200):
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


class Subagents:
    def __init__(self, clock=time.time, keep=KEEP):
        self._clock = clock
        self._keep = keep
        self._items = []           # dans l'ordre de lancement
        self._by_tool = {}
        self._by_task = {}

    # ---- suivi ---------------------------------------------------------------------------

    def feed(self, ev):
        if isinstance(ev, proto.ToolUse) and ev.name in AGENT_TOOLS:
            self._launched(ev)
        elif isinstance(ev, proto.ToolResult):
            item = self._by_tool.get(ev.tool_id)
            if item is not None and item["state"] == "running":
                if not ev.is_error and ev.text.lstrip().lower().startswith("async agent launched"):
                    item["background"] = True           # CLI sans `task_started` : vu au résultat
                elif not item["background"] or ev.is_error:
                    self._end(item, "failed" if ev.is_error else "done")
        elif isinstance(ev, proto.TaskNotice):
            item = self._by_tool.get(ev.tool_id)
            if item is not None:
                if ev.summary:
                    item["summary"] = _text(ev.summary, 300)
                self._end(item, FINAL_STATUS.get(ev.status.lower(), "done"))
        elif isinstance(ev, proto.Unknown) and isinstance(ev.raw, dict) and ev.raw.get("type") == "system":
            self._system(ev.raw)
        elif isinstance(ev, chat_engine.StateChanged) and ev.state == "stopped":
            for item in self._items:
                if item["state"] == "running":
                    self._end(item, "stopped")

    def _launched(self, ev):
        if ev.tool_id in self._by_tool:
            return
        data = ev.input if isinstance(ev.input, dict) else {}
        item = {"tool_id": ev.tool_id, "task_id": "",
                "description": _text(data.get("description")) or _text(data.get("prompt"), 80),
                "type": _text(data.get("subagent_type"), 60) or "general-purpose",
                "background": bool(data.get("run_in_background")),
                "parent": ev.parent_id or None, "state": "running",
                "started": self._clock(), "ended": None, "summary": ""}
        self._items.append(item)
        self._by_tool[ev.tool_id] = item
        self._trim()

    def _system(self, raw):
        sub = raw.get("subtype")
        if sub == "task_started":
            item = self._by_tool.get(raw.get("tool_use_id"))
            task_id = raw.get("task_id")
            if item is None or not isinstance(task_id, str) or not task_id:
                return                      # tâche de fond qui n'est pas un sous-agent (commande)
            item["task_id"] = task_id
            self._by_task[task_id] = item
            if raw.get("is_backgrounded") is True:
                item["background"] = True
        elif sub == "task_updated":
            item = self._by_task.get(raw.get("task_id"))
            patch = raw.get("patch") if isinstance(raw.get("patch"), dict) else {}
            status = patch.get("status")
            if item is not None and isinstance(status, str) and status.lower() in FINAL_STATUS:
                self._end(item, FINAL_STATUS[status.lower()])
        elif sub == "task_notification":
            # forme brute (CLI sans `tool_use_id` dans l'avis) : retrouvée par `task_id`
            item = self._by_task.get(raw.get("task_id"))
            status = raw.get("status")
            if item is not None and isinstance(status, str):
                self._end(item, FINAL_STATUS.get(status.lower(), "done"))

    def _end(self, item, state):
        if item["state"] == "running":
            item["state"] = state
            item["ended"] = self._clock()

    def _trim(self):
        while len(self._items) > self._keep:
            old = next((i for i in self._items if i["state"] != "running"), self._items[0])
            self._items.remove(old)
            self._by_tool.pop(old["tool_id"], None)
            self._by_task.pop(old["task_id"], None)

    # ---- lecture -------------------------------------------------------------------------

    def items(self):
        """Copie des sous-agents suivis, dans l'ordre de lancement."""
        return [dict(i) for i in self._items]

    def running(self):
        return sum(1 for i in self._items if i["state"] == "running")


def numbered(items):
    """Ajoute `index` (1, 2… sur tous, ordre de lancement) et `active_index` (rang parmi ceux
    qui tournent encore, sinon None)."""
    out, active = [], 0
    for n, item in enumerate(items, 1):
        entry = dict(item, index=n, active_index=None)
        if item.get("state") == "running":
            active += 1
            entry["active_index"] = active
        out.append(entry)
    return out


def _started_at(path):
    """Heure (epoch) de la première ligne du journal d'un sous-agent, sinon sa date de fichier."""
    try:
        with open(path, encoding="utf-8") as f:
            first = json.loads(f.readline() or "{}")
        stamp = first.get("timestamp") if isinstance(first, dict) else None
        if isinstance(stamp, str) and stamp:
            return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (OSError, ValueError):
        pass
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def from_transcript(path):
    """Sous-agents d'une conversation lus sur le disque (`<session>/subagents/agent-<id>.meta.json`
    écrits par Claude Code), dans l'ordre de lancement : marche aussi pour une session ouverte
    dans un terminal. `task_id` : l'identifiant de l'agent (celui de `stop_task`)."""
    if not path:
        return []
    folder = Path(path).with_suffix("") / "subagents"
    out = []
    try:
        metas = list(folder.glob("agent-*.meta.json"))
    except OSError:
        return []
    for meta in metas:
        agent_id = meta.name[len("agent-"):-len(".meta.json")]
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        out.append({"tool_id": str(data.get("toolUseId") or ""), "task_id": agent_id,
                    "description": _text(data.get("description")),
                    "type": _text(data.get("agentType"), 60) or "general-purpose",
                    "background": data.get("requestShape") == "background",
                    "parent": None, "state": "done" if data.get("finished") else "running",
                    "started": _started_at(folder / f"agent-{agent_id}.jsonl"), "ended": None,
                    "summary": ""})
    out.sort(key=lambda i: i["started"])
    return out


def merge(live, on_disk):
    """Sous-agents suivis en direct par le pont (états exacts), complétés par le disque : un
    `task_id` manquant y est repris ; sans suivi direct (pont relancé, session d'un terminal),
    seule la liste du disque compte."""
    if not live:
        return [dict(i) for i in on_disk]
    by_tool = {i["tool_id"]: i for i in on_disk if i["tool_id"]}
    out = []
    for item in live:
        item = dict(item)
        disk = by_tool.get(item["tool_id"])
        if disk is not None and not item.get("task_id"):
            item["task_id"] = disk["task_id"]
        out.append(item)
    return out
