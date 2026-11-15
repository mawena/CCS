"""Pont : projets et conversations, fichiers, feuille de route, analyse et file de tâches.

Les chemins reçus sont absolus et, une fois les liens suivis, sous le dossier personnel de
l'utilisateur ou sous un dossier de projets web du serveur (`EXTRA_ROOTS`, où lnmp range les
sites). Le pont tourne sous l'utilisateur : les droits Unix restent la vraie barrière ; cette
garde évite qu'une page web piégée ou une erreur fasse lire ailleurs.
"""

import asyncio
import dataclasses
import os
import time
from pathlib import Path

from .. import conversations, core, file_tree, preview, roadmap, session_hub, sessions, tasks, transcripts
from ..store import Store
from . import rpc

EXTRA_ROOTS = ("/var/www", "/srv")
MAX_LIST = 2000
MAX_CONVERSATIONS = 300


def _home():
    return os.path.realpath(os.environ.get("HOME") or str(Path.home()))


def _under(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def allowed_path(path, home=None):
    home = home or _home()
    return _under(path, home) or any(_under(path, r) for r in EXTRA_ROOTS)


def safe_path(p):
    if not isinstance(p, str) or not p or "\0" in p or not os.path.isabs(p):
        raise rpc.RpcError("refuse", "Chemin refusé.")
    real = os.path.realpath(p)
    if not allowed_path(real):
        raise rpc.RpcError("refuse", "Chemin refusé.")
    return Path(real)


def _plain(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _plain(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _stamp(path):
    s = file_tree.stamp(path)
    return [s[0], s[1]]


class DataApi:
    def __init__(self, bridge):
        bridge.add_handlers({
            "projects.list": self.projects, "conversation.messages": self.messages,
            "files.list": self.files_list, "files.read": self.files_read,
            "files.write": self.files_write, "roadmap.read": self.roadmap_read,
            "roadmap.toggle": self.roadmap_toggle, "analysis.report": self.analysis,
            "tasks.list": self.tasks_list, "tasks.add": self.tasks_add,
            "tasks.cancel": self.tasks_cancel,
        })

    # ---- projets et conversations ----------------------------------------------------

    async def projects(self, _conn, params):
        selected = params.get("cwd") if isinstance(params.get("cwd"), str) else session_hub.ALL
        query = params.get("query") if isinstance(params.get("query"), str) else ""

        def work():
            convs = conversations.scan()
            found = sessions.list_sessions()
            view = session_hub.build(convs, found, selected=selected, query=query)
            return {"entries": _plain(view.entries), "sessions": _plain(view.sessions),
                    "conversations": _plain(view.conversations[:MAX_CONVERSATIONS]),
                    "total": view.total, "projects": view.projects}
        return await asyncio.to_thread(work)

    async def messages(self, _conn, params):
        path = safe_path(params.get("path"))
        limit = params.get("limit") if isinstance(params.get("limit"), int) else None
        try:
            msgs = await asyncio.to_thread(preview.read_messages, str(path), limit)
        except FileNotFoundError:
            raise rpc.RpcError("introuvable", "Conversation introuvable.") from None
        return {"messages": _plain(msgs)}

    # ---- fichiers --------------------------------------------------------------------

    async def files_list(self, _conn, params):
        root = safe_path(params.get("root"))
        rel = params.get("rel") if isinstance(params.get("rel"), str) else ""
        folder = safe_path(os.path.join(str(root), rel)) if rel else root
        if not _under(str(folder), str(root)):
            raise rpc.RpcError("refuse", "Chemin refusé.")

        def work():
            marks = file_tree.git_marks(str(root))
            out = []
            try:
                items = list(os.scandir(folder))
            except OSError:
                raise rpc.RpcError("introuvable", "Dossier illisible.") from None
            for e in items[:MAX_LIST]:
                if e.name == ".git":
                    continue
                relpath = os.path.relpath(e.path, root)
                out.append({"name": e.name, "path": relpath, "dir": e.is_dir(follow_symlinks=False),
                            "mark": marks.get(relpath, "")})
            out.sort(key=lambda x: (not x["dir"], x["name"].lower()))
            return {"entries": out, "truncated": len(items) > MAX_LIST}
        return await asyncio.to_thread(work)

    async def files_read(self, _conn, params):
        path = safe_path(params.get("path"))

        def work():
            k = file_tree.kind(path)
            if k == "missing":
                raise rpc.RpcError("introuvable", "Fichier introuvable.")
            out = {"kind": k, "stamp": _stamp(path)}
            if k == "text":
                out["text"], out["encoding"] = file_tree.read_text(path)
            return out
        return await asyncio.to_thread(work)

    async def files_write(self, _conn, params):
        path = safe_path(params.get("path"))
        text, stamp = params.get("text"), params.get("stamp")
        if not isinstance(text, str):
            raise rpc.RpcError("invalide", "Texte manquant.")

        def work():
            if path.exists():
                if not isinstance(stamp, list) or _stamp(path) != stamp:
                    raise rpc.RpcError("conflit", "Le fichier a changé depuis son ouverture.")
            file_tree.save(path, text)
            return {"stamp": _stamp(path)}
        return await asyncio.to_thread(work)

    # ---- feuille de route ------------------------------------------------------------

    async def roadmap_read(self, _conn, params):
        cwd = safe_path(params.get("cwd"))

        def work():
            path = roadmap.find(cwd)
            if path is None:
                return {"path": None, "phases": [], "title": ""}
            rm = roadmap.parse(path.read_text(encoding="utf-8", errors="replace"), path)
            return {"path": str(path), "title": rm.title, "phases": _plain(rm.phases)}
        return await asyncio.to_thread(work)

    async def roadmap_toggle(self, _conn, params):
        path = safe_path(params.get("path"))
        line, text = params.get("line"), params.get("text")
        if not isinstance(line, int) or not isinstance(text, str):
            raise rpc.RpcError("invalide", "Case invalide.")
        if not await asyncio.to_thread(roadmap.toggle, path, line, text):
            raise rpc.RpcError("conflit", "La feuille de route a changé : relis-la.")
        return {}

    # ---- analyse et tâches -----------------------------------------------------------

    async def analysis(self, _conn, params):
        days = params.get("days") if isinstance(params.get("days"), int) else 7
        days = max(1, min(days, 365))

        def work():
            since = time.time() - days * 86400
            rows = transcripts.scan(core.paths().config_dir / "projects", since)
            periods = Store().active_periods(since, time.time())
            report = transcripts.aggregate(rows, periods, days)
            return {**_plain(report), "responses": len(rows)}
        return await asyncio.to_thread(work)

    async def tasks_list(self, _conn, _params):
        return {"tasks": _plain(await asyncio.to_thread(tasks.all))}

    async def tasks_add(self, _conn, params):
        cwd = safe_path(params.get("cwd"))
        try:
            task = await asyncio.to_thread(tasks.add, params.get("message") or "", str(cwd),
                                           params.get("model"), params.get("rights") or tasks.DEFAULT_RIGHTS,
                                           params.get("when") or "quota")
        except ValueError as e:
            raise rpc.RpcError("invalide", str(e)) from None
        return {"task": _plain(task)}

    async def tasks_cancel(self, _conn, params):
        try:
            task = await asyncio.to_thread(tasks.cancel, str(params.get("id")))
        except ValueError as e:
            raise rpc.RpcError("invalide", str(e)) from None
        if task is None:
            raise rpc.RpcError("introuvable", "Tâche inconnue.")
        return {"task": _plain(task)}
