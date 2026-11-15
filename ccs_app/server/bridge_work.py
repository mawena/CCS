"""Travail dans le chat, côté pont (phase 14 au web) : commandes `/`, fichiers proposés après `@`,
messages enregistrés, commande `!`, changements de la session (copies de Claude Code) et retour
en arrière. Chaque chemin venu du client passe par `bridge_data.safe_path` ; rien d'écrit sans
que le client l'ait demandé après sa carte de confirmation."""

import asyncio
import collections
import difflib
import itertools
import os
import threading

from .. import context_alert, file_history, saved_messages, sessions, settings, shell_command
from . import rpc
from .bridge_data import safe_path

SKIP_DIRS = {"node_modules", "__pycache__", "venv", "dist", "build", "target", "site-packages"}
FILE_SCAN_MAX = 20_000
SHELL_TIMEOUT_S = 600
SHELL_KEEP = 20
MAX_DIFF = 200_000
MAX_NAME = 80
MAX_TEXT = 20_000
POINTS_MAX = 200


def scan_files(root, limit=FILE_SCAN_MAX):
    """Fichiers du projet (chemins relatifs), sans dossiers cachés ni dépendances."""
    out = []
    for base, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS)
        for name in sorted(names):
            if not name.startswith("."):
                out.append(os.path.relpath(os.path.join(base, name), root))
                if len(out) >= limit:
                    return out
    return out


def _text(data):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _change_json(ch):
    kind = "created" if ch.before is None else "deleted" if ch.now is None else "modified"
    before = b"" if ch.before is None else ch.before
    now = b"" if ch.now is None else ch.now
    a, b = _text(before), _text(now)
    diff, binary = "", a is None or b is None
    if not binary:
        name = os.path.basename(ch.path)
        diff = "".join(difflib.unified_diff(
            a.splitlines(True), b.splitlines(True), f"a/{name}", f"b/{name}", n=3))
        if len(diff) > MAX_DIFF:
            diff = diff[:MAX_DIFF] + "\n… (diff coupé)\n"
    return {"path": ch.path, "kind": kind, "binary": binary, "diff": diff}


class WorkApi:
    def __init__(self, bridge):
        self.bridge = bridge
        self.shells = {}                                   # run_id → ShellRun en cours
        self.shell_done = collections.OrderedDict()        # run_id → résultat
        self._ids = itertools.count(1)
        bridge.add_handlers({
            "work.commands": self.commands, "work.files": self.files,
            "work.saved.list": self.saved_list, "work.saved.save": self.saved_save,
            "work.saved.delete": self.saved_delete,
            "work.shell.run": self.shell_run, "work.shell.stop": self.shell_stop,
            "work.shell.poll": self.shell_poll,
            "work.changes": self.changes, "work.undo_file": self.undo_file,
            "work.rewind_plan": self.rewind_plan, "work.rewind_apply": self.rewind_apply,
        })

    def _chat(self, params):
        hub = self.bridge.hubs["chat"]
        chat = hub.chats.get(params.get("chat_id"))
        if chat is None:
            raise rpc.RpcError("introuvable", "Chat inconnu ou fermé.")
        return chat

    # ---- commandes `/` et fichiers `@` -----------------------------------------------

    async def commands(self, _conn, params):
        chat = self._chat(params)
        found = []
        for item in reversed(chat.buf):
            ev = item["event"]
            if ev.get("type") == "Hello":
                found = [{"name": str(c[0]).lstrip("/"), "description": str(c[1] if len(c) > 1 else ""),
                          "hint": str(c[2] if len(c) > 2 else "")}
                         for c in ev.get("commands") or () if c and c[0]]
                break
        cfg = context_alert.config(await asyncio.to_thread(settings.load_settings))
        return {"commands": found, "context": cfg}

    async def files(self, _conn, params):
        root = self._chat(params).cwd
        return {"files": await asyncio.to_thread(scan_files, root)}

    # ---- messages enregistrés -------------------------------------------------------

    @staticmethod
    def _cwd(params):
        return str(safe_path(params.get("cwd")))

    async def saved_list(self, _conn, params):
        cwd = self._cwd(params)
        items = await asyncio.to_thread(saved_messages.load, cwd)
        return {"items": [{"name": s.name, "text": s.text, "scope": s.scope} for s in items]}

    @staticmethod
    def _scope(params):
        scope = params.get("scope")
        if scope not in saved_messages.SCOPES:
            raise rpc.RpcError("invalide", "Portée inconnue.")
        return scope

    async def saved_save(self, _conn, params):
        cwd, scope = self._cwd(params), self._scope(params)
        name, text = params.get("name"), params.get("text")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_NAME:
            raise rpc.RpcError("invalide", "Donne un nom court au message.")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise rpc.RpcError("invalide", "Le texte est vide ou trop long.")

        def work():
            mine = [s for s in saved_messages.load(cwd) if s.scope == scope and s.name != name.strip()]
            mine.append(saved_messages.Saved(name.strip(), text, scope))
            saved_messages.save(scope, mine, cwd)
        try:
            await asyncio.to_thread(work)
        except OSError:
            raise rpc.RpcError("erreur", "Écriture impossible.") from None
        return {}

    async def saved_delete(self, _conn, params):
        cwd, scope = self._cwd(params), self._scope(params)
        name = params.get("name")

        def work():
            mine = [s for s in saved_messages.load(cwd) if s.scope == scope and s.name != name]
            saved_messages.save(scope, mine, cwd)
        try:
            await asyncio.to_thread(work)
        except OSError:
            raise rpc.RpcError("erreur", "Écriture impossible.") from None
        return {}

    # ---- commande `!` ------------------------------------------------------------------

    async def shell_run(self, conn, params):
        chat = self._chat(params)
        command = params.get("command")
        if not isinstance(command, str) or not command.strip() or len(command) > 4000:
            raise rpc.RpcError("invalide", "Commande vide ou trop longue.")
        loop = asyncio.get_running_loop()
        run_id = f"s{next(self._ids)}"
        run = shell_command.ShellRun(command.strip(), chat.cwd)
        self.shells[run_id] = run
        timer = threading.Timer(SHELL_TIMEOUT_S, run.stop)
        timer.daemon = True

        def finish(code, text, truncated):
            timer.cancel()
            data = {"chat_id": chat.chat_id, "run_id": run_id, "code": code,
                    "output": text, "truncated": truncated}
            loop.call_soon_threadsafe(self._shell_finished, run_id, data, conn, chat)

        timer.start()
        run.start(finish)
        return {"run_id": run_id}

    def _shell_finished(self, run_id, data, conn, chat):
        self.shells.pop(run_id, None)
        self.shell_done[run_id] = data
        while len(self.shell_done) > SHELL_KEEP:
            self.shell_done.popitem(last=False)
        for c in {conn, *chat.conns}:
            if not c.closed:
                asyncio.ensure_future(c.push("work.shell", data))

    async def shell_stop(self, _conn, params):
        run = self.shells.get(params.get("run_id"))
        if run is not None:
            await asyncio.to_thread(run.stop)
        return {}

    async def shell_poll(self, _conn, params):
        rid = params.get("run_id")
        if rid in self.shell_done:
            return {"done": True, **self.shell_done[rid]}
        return {"done": False, "running": rid in self.shells}

    # ---- changements de la session ---------------------------------------------------

    def _journal(self, chat):
        sid = getattr(chat.engine, "session_id", None)
        if not sid:
            return None, None
        return sessions.transcript_path(chat.cwd, sid), sid

    async def changes(self, _conn, params):
        transcript, sid = self._journal(self._chat(params))
        if transcript is None:
            return {"unknown": False, "files": [], "points": []}

        def work():
            snaps = file_history.read(transcript)
            if snaps is None:
                return {"unknown": True, "files": [], "points": []}
            files = [_change_json(c) for c in file_history.changes(snaps, sid)]
            points = [{"message_id": u.message_id, "text": u.text[:300], "time": u.time}
                      for u in file_history.user_messages(transcript)[-POINTS_MAX:]]
            return {"unknown": False, "files": files, "points": points}
        return await asyncio.to_thread(work)

    async def undo_file(self, _conn, params):
        transcript, sid = self._journal(self._chat(params))
        path = params.get("path")
        safe_path(path)
        if transcript is None:
            raise rpc.RpcError("introuvable", "Conversation introuvable.")

        def work():
            snaps = file_history.read(transcript) or []
            ch = next((c for c in file_history.changes(snaps, sid) if c.path == path), None)
            if ch is None:
                raise rpc.RpcError("introuvable", "Ce fichier n'a pas changé pendant la session.")
            file_history.apply([file_history.Step(ch.path, ch.before, False)])
        try:
            await asyncio.to_thread(work)
        except OSError:
            raise rpc.RpcError("erreur", "Écriture impossible.") from None
        return {}

    def _plan(self, params):
        transcript, sid = self._journal(self._chat(params))
        mid = params.get("message_id")
        if transcript is None or not isinstance(mid, str):
            raise rpc.RpcError("introuvable", "Conversation ou message introuvable.")
        snaps = file_history.read(transcript)
        if snaps is None:
            raise rpc.RpcError("inconnu", "Format de l'historique des fichiers inconnu : retour impossible.")
        plan = file_history.rewind_plan(snaps, sid, mid)
        for step in plan:
            safe_path(step.path)
        return plan

    async def rewind_plan(self, _conn, params):
        plan = await asyncio.to_thread(self._plan, params)
        return {"steps": [{"path": s.path, "deleted": s.content is None, "user_edited": s.user_edited}
                          for s in plan]}

    async def rewind_apply(self, _conn, params):
        def work():
            plan = self._plan(params)
            file_history.apply(plan)
            return len(plan)
        try:
            return {"count": await asyncio.to_thread(work)}
        except OSError:
            raise rpc.RpcError("erreur", "Écriture impossible.") from None
