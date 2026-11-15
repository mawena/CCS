"""Pont : projets et conversations, fichiers, feuille de route, analyse et file de tâches.

Les chemins reçus sont absolus et, une fois les liens suivis, sous le dossier personnel de
l'utilisateur ou sous un dossier de projets web du serveur (`EXTRA_ROOTS`, où lnmp range les
sites). Le pont tourne sous l'utilisateur : les droits Unix restent la vraie barrière ; cette
garde évite qu'une page web piégée ou une erreur fasse lire ailleurs.
"""

import asyncio
import base64
import dataclasses
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import (conversations, core, costs, file_tree, pause, preview, project_accounts, roadmap,
               session_hub, sessions, tasks, transcripts)
from ..store import Store
from . import rpc

EXTRA_ROOTS = ("/var/www", "/srv")
MAX_LIST = 2000
MAX_CONVERSATIONS = 300
MAX_FOLDERS = 300                 # dépôts git renvoyés par projects.folders
MAX_SEARCH = 100                  # résultats de files.search
SCAN_SECONDS = 3.0                # délai des parcours de disque
MAX_VISITED = 50000               # entrées examinées au plus par files.search
MAX_IMAGE = 5 * 1024 * 1024
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
              ".webp": "image/webp", ".bmp": "image/bmp", ".svg": "image/svg+xml", ".ico": "image/x-icon"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}


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
            "tasks.cancel": self.tasks_cancel, "projects.folders": self.folders,
            "projects.account": self.project_account, "files.image": self.files_image,
            "files.search": self.files_search, "conversation.rename": self.rename,
            "conversation.cost": self.cost, "roadmap.task_prompt": self.roadmap_task_prompt,
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

    async def folders(self, _conn, _params):
        """Dépôts git du disque : dossier personnel sur 3 niveaux, /var/www et /srv sur 2."""
        def work():
            deadline = time.monotonic() + SCAN_SECONDS
            found, truncated = [], False
            roots = [(_home(), 3)] + [(r, 2) for r in EXTRA_ROOTS if os.path.isdir(r)]
            for top, depth in roots:
                stack = [(top, 0)]
                while stack:
                    if time.monotonic() > deadline:
                        truncated = True
                        break
                    folder, level = stack.pop()
                    if level and os.path.exists(os.path.join(folder, ".git")):
                        if len(found) >= MAX_FOLDERS:
                            truncated = True
                            break
                        found.append(folder)
                        continue
                    if level >= depth:
                        continue
                    try:
                        with os.scandir(folder) as it:
                            kids = sorted(e.path for e in it if not e.name.startswith(".")
                                          and e.name not in SKIP_DIRS and e.is_dir(follow_symlinks=False))
                    except OSError:
                        continue
                    stack.extend((k, level + 1) for k in reversed(kids))
            return {"folders": [{"path": f, "name": os.path.basename(f)} for f in found],
                    "truncated": truncated}
        return await asyncio.to_thread(work)

    async def project_account(self, _conn, params):
        """Comptes et compte présélectionné pour ce dossier, comme « Nouvelle session » du bureau."""
        cwd = params.get("cwd")
        if isinstance(cwd, str) and cwd.startswith("~"):
            cwd = os.path.normpath(os.path.expanduser(cwd))
        path = str(safe_path(cwd))

        def work():
            profiles = core.list_profiles()
            names = [p.name for p in profiles]
            paused = pause.pause_state(datetime.now(timezone.utc)) is not None
            try:
                assocs = project_accounts.all()
            except OSError:
                assocs = []
            return {"profiles": [{"name": p.name, "email": p.email, "active": bool(p.active)} for p in profiles],
                    "active": next((p.name for p in profiles if p.active), None),
                    "preferred": project_accounts.preferred_profile(path, names, paused, assocs),
                    "hint": project_accounts.hint(path, names, paused, assocs), "paused": paused}
        return await asyncio.to_thread(work)

    async def rename(self, _conn, params):
        """Titre ajouté au journal : seulement `<session_id>.jsonl` sous le dossier des projets
        de Claude Code (liens suivis), jamais un autre fichier du dossier personnel."""
        path, session_id = safe_path(params.get("path")), params.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise rpc.RpcError("invalide", "Conversation inconnue.")
        projects = os.path.realpath(sessions.projects_dir())
        if path.name != f"{session_id}.jsonl" or str(path) == projects or not _under(str(path), projects):
            raise rpc.RpcError("refuse", "Ce fichier n'est pas un journal de conversation.")
        try:
            title = await asyncio.to_thread(conversations.rename, session_id, params.get("title"), None, str(path))
        except ValueError as e:
            raise rpc.RpcError("invalide", f"Titre refusé : {e}.") from None
        except OSError:
            raise rpc.RpcError("introuvable", "Conversation introuvable.") from None
        return {"title": title}

    async def cost(self, _conn, params):
        path = safe_path(params.get("path"))

        def work():
            c = costs.conversation_cost(str(path))
            return {"short": costs.format_short(c), "text": costs.format_cost(c), "dollars": c.dollars}
        try:
            return await asyncio.to_thread(work)
        except OSError:
            raise rpc.RpcError("introuvable", "Conversation introuvable.") from None

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

    async def files_image(self, _conn, params):
        path = safe_path(params.get("path"))
        mime = IMAGE_MIME.get(path.suffix.lower())

        def work():
            if mime is None or not path.is_file():
                raise rpc.RpcError("invalide", "Ce fichier n'est pas une image.")
            if path.stat().st_size > MAX_IMAGE:
                raise rpc.RpcError("trop_gros", "Image trop grosse pour être affichée (5 Mo au plus).")
            return {"mime": mime, "data": base64.b64encode(path.read_bytes()).decode("ascii")}
        return await asyncio.to_thread(work)

    async def files_search(self, _conn, params):
        root = safe_path(params.get("root"))
        query = params.get("query") if isinstance(params.get("query"), str) else ""
        needle = query.strip().lower()

        def work():
            out, truncated, seen = [], False, 0
            deadline = time.monotonic() + SCAN_SECONDS
            for folder, dirs, files in os.walk(root):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                for name, is_dir in [(d, True) for d in dirs] + [(f, False) for f in sorted(files)]:
                    seen += 1
                    if needle in name.lower():
                        if len(out) >= MAX_SEARCH:
                            return {"entries": out, "truncated": True}
                        out.append({"name": name, "dir": is_dir,
                                    "path": os.path.relpath(os.path.join(folder, name), root)})
                if seen > MAX_VISITED or time.monotonic() > deadline:
                    truncated = True
                    break
            return {"entries": out, "truncated": truncated}
        if not needle:
            return {"entries": [], "truncated": False}
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

    async def roadmap_task_prompt(self, _conn, params):
        """Message qui demande à Claude de faire une tâche (retrouvée par texte et phase)."""
        path = safe_path(params.get("path"))
        text, phase_title = params.get("text"), params.get("phase")

        def work():
            try:
                rm = roadmap.parse(path.read_text(encoding="utf-8", errors="replace"), path)
            except OSError:
                return None
            task = roadmap.locate(rm, text, phase_title)
            phase = next((p for p in rm.phases if p.title == phase_title), None)
            return None if task is None or phase is None else roadmap.task_prompt(task, phase)
        prompt = await asyncio.to_thread(work)
        if prompt is None:
            raise rpc.RpcError("introuvable", "Cette tâche n'existe plus : relis la feuille de route.")
        return {"prompt": prompt}

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
        extra, info = None, params.get("roadmap")
        if isinstance(info, dict) and all(isinstance(info.get(k), str) for k in ("path", "text", "phase")):
            extra = {"roadmap": {"path": str(safe_path(info["path"])), "text": info["text"], "phase": info["phase"]}}
        try:
            task = await asyncio.to_thread(tasks.add, params.get("message") or "", str(cwd),
                                           params.get("model"), params.get("rights") or tasks.DEFAULT_RIGHTS,
                                           params.get("when") or "quota", None, None, extra)
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
