"""Travail dans le chat, côté pont (phase 14 au web) : commandes `/`, fichiers proposés après `@`,
messages enregistrés, commande `!`, changements de la session (copies de Claude Code) et retour
en arrière. Chaque chemin venu du client passe par `bridge_data.safe_path` ; rien d'écrit sans
que le client l'ait demandé après sa carte de confirmation : annuler un fichier ou revenir en
arrière exige les empreintes (sha256) des fichiers tels qu'ils ont été montrés, et rien ne
s'écrit pendant un tour de Claude."""

import asyncio
import collections
import difflib
import hashlib
import itertools
import os
import re
import threading

from .. import context_alert, file_history, saved_messages, sessions, settings, shell_command
from . import rpc
from .bridge_chat import BUSY
from .bridge_data import safe_path

SKIP_DIRS = {"node_modules", "__pycache__", "venv", "dist", "build", "target", "site-packages"}
FILE_SCAN_MAX = 20_000
SHELL_TIMEOUT_S = 600
SHELL_KEEP = 20
MAX_FILE_BYTES = 2 * 1024 * 1024    # fichier plus gros : diff non calculé (`too_big`)
MAX_LINE_CHARS = 4000               # ligne de diff plus longue : coupée
MAX_DIFF = 200_000                  # texte du diff d'un fichier
MAX_DIFF_TOTAL = 1_000_000          # texte de tous les diffs d'une réponse (au-delà : `too_big`)
MAX_NAME = 80
MAX_TEXT = 20_000
POINTS_MAX = 200
MAX_EXPECTED = 10_000
CONFLICT = "Un fichier a changé depuis l'affichage : vérifie de nouveau."
_SHA256 = re.compile(r"[0-9a-f]{64}")


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


def _sha256(data):
    return None if data is None else hashlib.sha256(data).hexdigest()


def _file_sha256(path):
    """Empreinte du contenu actuel (None si le fichier n'existe pas ou ne se lit pas), lu comme
    `file_history` le lit."""
    try:
        with open(path, "rb") as f:
            h = hashlib.sha256()
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _unified(a, b, name, limit):
    """Diff unifié lu au fur et à mesure : s'arrête après `limit` caractères ; lignes coupées
    à MAX_LINE_CHARS."""
    out, size = [], 0
    for line in difflib.unified_diff(a.splitlines(True), b.splitlines(True), f"a/{name}", f"b/{name}", n=3):
        if len(line) > MAX_LINE_CHARS:
            line = line[:MAX_LINE_CHARS] + "…\n"
        out.append(line)
        size += len(line)
        if size > limit:
            out.append("\n… (diff coupé)\n")
            break
    return "".join(out)


def _change_json(ch, budget):
    """Entrée de work.changes. `budget` : [caractères de diff encore permis dans la réponse] ;
    un fichier de plus de MAX_FILE_BYTES, ou venu une fois le budget épuisé, porte `too_big`."""
    kind = "created" if ch.before is None else "deleted" if ch.now is None else "modified"
    out = {"path": ch.path, "kind": kind, "binary": False, "diff": "", "too_big": False,
           "sha256": _sha256(ch.now)}
    before = b"" if ch.before is None else ch.before
    now = b"" if ch.now is None else ch.now
    if max(len(before), len(now)) > MAX_FILE_BYTES or budget[0] <= 0:
        out["too_big"] = True
        return out
    a, b = _text(before), _text(now)
    if a is None or b is None:
        out["binary"] = True
        return out
    out["diff"] = _unified(a, b, os.path.basename(ch.path), min(MAX_DIFF, budget[0]))
    budget[0] -= len(out["diff"])
    return out


def _allowed(path):
    try:
        safe_path(path)
    except rpc.RpcError:
        return False
    return True


def _not_busy(chat):
    if getattr(chat.engine, "state", None) in BUSY:
        raise rpc.RpcError("occupe", "Claude travaille : attends la fin du tour.")


def _expected_sha(value):
    if value is not None and not (isinstance(value, str) and _SHA256.fullmatch(value)):
        raise rpc.RpcError("invalide", "Empreinte invalide : actualise.")
    return value


def _expected_files(params):
    """{chemin: sha256 ou None} montré par work.rewind_plan (paramètre `expected`)."""
    raw = params.get("expected")
    if not isinstance(raw, list) or len(raw) > MAX_EXPECTED:
        raise rpc.RpcError("invalide", "Fichiers montrés manquants : actualise.")
    out = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise rpc.RpcError("invalide", "Fichiers montrés invalides : actualise.")
        out[item["path"]] = _expected_sha(item.get("sha256"))
    return out


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
            budget = [MAX_DIFF_TOTAL]
            files = [_change_json(c, budget) for c in file_history.changes(snaps, sid)]
            with_snapshot = {s.message_id for s in snaps}     # seuls points de retour possibles
            points = [{"message_id": u.message_id, "text": u.text[:300], "time": u.time}
                      for u in file_history.user_messages(transcript)
                      if u.message_id in with_snapshot][-POINTS_MAX:]
            return {"unknown": False, "files": files, "points": points}
        return await asyncio.to_thread(work)

    async def undo_file(self, _conn, params):
        """Remet un fichier comme avant la conversation, s'il est encore tel qu'il a été montré
        (`expected` : son sha256 dans work.changes, None s'il n'existait pas)."""
        chat = self._chat(params)
        _not_busy(chat)
        transcript, sid = self._journal(chat)
        path = params.get("path")
        safe_path(path)
        if "expected" not in params:
            raise rpc.RpcError("invalide", "Empreinte du fichier montré manquante : actualise.")
        expected = _expected_sha(params.get("expected"))
        if transcript is None:
            raise rpc.RpcError("introuvable", "Conversation introuvable.")

        def work():
            snaps = file_history.read(transcript) or []
            ch = next((c for c in file_history.changes(snaps, sid) if c.path == path), None)
            if ch is None:
                raise rpc.RpcError("introuvable", "Ce fichier n'a pas changé pendant la session.")
            if _sha256(ch.now) != expected:
                raise rpc.RpcError("conflit", CONFLICT)
            file_history.apply([file_history.Step(ch.path, ch.before, False)])
        try:
            await asyncio.to_thread(work)
        except OSError:
            raise rpc.RpcError("erreur", "Écriture impossible.") from None
        return {}

    def _plan(self, chat, params):
        """(étapes, chemins laissés de côté) du retour à l'état d'avant `message_id` : un
        fichier hors des dossiers permis n'est pas écrit, il est seulement signalé."""
        transcript, sid = self._journal(chat)
        mid = params.get("message_id")
        if transcript is None or not isinstance(mid, str):
            raise rpc.RpcError("introuvable", "Conversation ou message introuvable.")
        snaps = file_history.read(transcript)
        if snaps is None:
            raise rpc.RpcError("inconnu", "Format de l'historique des fichiers inconnu : retour impossible.")
        try:
            plan = file_history.rewind_plan(snaps, sid, mid)
        except file_history.NoSnapshot:
            raise rpc.RpcError("introuvable", "Ce message n'a pas d'instantané des fichiers : "
                                              "retour impossible à ce point.") from None
        sorted_plan = [(s, _allowed(s.path)) for s in plan]
        return [s for s, ok in sorted_plan if ok], [s.path for s, ok in sorted_plan if not ok]

    async def rewind_plan(self, _conn, params):
        chat = self._chat(params)

        def work():
            steps, skipped = self._plan(chat, params)
            return {"steps": [{"path": s.path, "deleted": s.content is None, "user_edited": s.user_edited,
                               "sha256": _file_sha256(s.path)} for s in steps],
                    "skipped": skipped}
        return await asyncio.to_thread(work)

    async def rewind_apply(self, _conn, params):
        """Applique le plan seulement s'il est celui qui a été montré : mêmes fichiers, mêmes
        contenus actuels (`expected` : [{path, sha256}] de work.rewind_plan)."""
        chat = self._chat(params)
        _not_busy(chat)
        expected = _expected_files(params)

        def work():
            steps, skipped = self._plan(chat, params)
            if {s.path: _file_sha256(s.path) for s in steps} != expected:
                raise rpc.RpcError("conflit", CONFLICT)
            file_history.apply(steps)
            return {"count": len(steps), "skipped": skipped}
        try:
            return await asyncio.to_thread(work)
        except OSError:
            raise rpc.RpcError("erreur", "Écriture impossible.") from None
