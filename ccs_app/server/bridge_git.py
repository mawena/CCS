"""Git d'un projet côté pont (phase 14 au web) : état, journal, diff, indexation, commit,
fetch / pull / push, par `git_repo` ; chemins limités par `bridge_data.safe_path`.

Tout appel part de `cwd` (le dossier du projet) ; les commandes tournent à la racine du dépôt,
dans un fil (`asyncio.to_thread`), une à la fois par dépôt. Fetch, pull et push ont le délai de
`git_repo` (120 s, 300 s, 300 s), leur propre exécuteur (ils n'occupent jamais le pool commun)
et jamais de demande de mot de passe.
"""

import asyncio
import concurrent.futures
import dataclasses
import functools
import os
import re

from .. import git_repo
from . import rpc
from .bridge_data import safe_path

DIFF_LINES = 2000          # lignes de diff renvoyées au plus (le reste : « tronqué »)
MAX_DIFF_CHARS = 1_000_000  # texte de diff renvoyé au plus (le reste : « tronqué »)
MAX_LINE_CHARS = 4000      # une ligne plus longue est coupée
MAX_FILE_BYTES = 2 * 1024 * 1024    # fichier plus gros : diff non calculé (`too_big`)
MAX_STATUS_FILES = 2000    # fichiers renvoyés par git.status au plus (`truncated` au-delà)
PAGE = 50
MAX_LOG = 1000             # commits renvoyés au plus par git.log (`limit`)
MAX_SHOW_FILES = 300       # fichiers d'un commit renvoyés au plus par git.show
MAX_LINES_PICKED = 20000   # lignes choisies au plus par git.lines
MAX_PATHS = 500
NET_WORKERS = 4            # fetch / pull / push en même temps au plus (les autres attendent)


def _git_error(e):
    return rpc.RpcError("git", str(e))


def _paths(params):
    paths = params.get("paths")
    if not isinstance(paths, list) or not paths or len(paths) > MAX_PATHS:
        raise rpc.RpcError("invalide", "Aucun fichier indiqué.")
    return [_rel(p) for p in paths]


def _rel(path):
    """Chemin relatif à la racine du dépôt ; « - » refusé (l'entrée standard pour git)."""
    if (not isinstance(path, str) or not path or path == "-" or "\0" in path or os.path.isabs(path)
            or ".." in path.split("/")):
        raise rpc.RpcError("invalide", "Chemin de fichier invalide.")
    return path


_COMMIT_ID = re.compile(r"(?:HEAD|[0-9a-fA-F]{4,64})")


def _commit_json(c):
    return {"id": c.id, "short": c.id[:8], "author": c.author, "email": c.email, "time": c.time,
            "subject": c.subject, "parents": list(c.parents)}


def _cut(text):
    return text if len(text) <= MAX_LINE_CHARS else text[:MAX_LINE_CHARS] + "…"


class GitApi:
    def __init__(self, bridge):
        self.bridge = bridge
        self._locks = {}
        self._net = None
        bridge.add_handlers({
            "git.status": self.status, "git.log": self.log, "git.diff": self.diff,
            "git.stage": self.stage, "git.unstage": self.unstage, "git.hunk": self.hunk,
            "git.commit": self.commit, "git.fetch": self.fetch, "git.pull": self.pull,
            "git.push": self.push, "git.refs": self.refs, "git.show": self.show,
            "git.lines": self.lines,
        })

    # ---- aides -----------------------------------------------------------------------

    async def _root(self, params, required=True):
        """Racine du dépôt de `cwd` (sous les dossiers permis), ou None si ce n'est pas un dépôt."""
        cwd = safe_path(params.get("cwd"))
        root = await asyncio.to_thread(git_repo.toplevel, cwd)
        if root is None:
            if required:
                raise rpc.RpcError("invalide", "Ce dossier n'est pas un dépôt git.")
            return None
        return safe_path(root)

    def _lock(self, root):
        return self._locks.setdefault(str(root), asyncio.Lock())

    async def _run(self, root, fn, *args, network=False):
        async with self._lock(root):
            try:
                if not network:
                    return await asyncio.to_thread(fn, root, *args)
                if self._net is None:
                    self._net = concurrent.futures.ThreadPoolExecutor(
                        NET_WORKERS, thread_name_prefix="ccs-git-reseau")
                return await asyncio.get_running_loop().run_in_executor(
                    self._net, functools.partial(fn, root, *args))
            except git_repo.GitError as e:
                raise _git_error(e) from None

    # ---- lecture ---------------------------------------------------------------------

    async def status(self, _conn, params):
        root = await self._root(params, required=False)
        if root is None:
            return {"repo": False}

        def work():
            b = git_repo.branch(root)
            files = git_repo.status(root)
            try:
                last = git_repo.last_message(root)
            except git_repo.GitError:
                last = ""
            return {"repo": True, "root": str(root), "branch": dataclasses.asdict(b),
                    "files": [dataclasses.asdict(f) for f in files[:MAX_STATUS_FILES]],
                    "truncated": len(files) > MAX_STATUS_FILES,
                    "proposed": git_repo.propose_message(root, files), "last_message": last}
        try:
            return await asyncio.to_thread(work)
        except git_repo.GitError as e:
            raise _git_error(e) from None

    async def log(self, _conn, params):
        root = await self._root(params)
        skip = params.get("skip")
        skip = skip if isinstance(skip, int) and not isinstance(skip, bool) and skip >= 0 else 0
        limit = params.get("limit", PAGE)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise rpc.RpcError("invalide", "Nombre de commits invalide.")
        limit = min(limit, MAX_LOG)

        def work(r):
            commits = git_repo.log(r, skip=skip, limit=limit + 1)
            return {"commits": [_commit_json(c) for c in commits[:limit]],
                    "more": len(commits) > limit}
        return await self._run(root, work)

    async def refs(self, _conn, params):
        """Branches, branches distantes, tags et HEAD (graphe du bureau)."""
        root = await self._root(params)

        def work(r):
            return {"refs": [{"name": x.name, "kind": x.kind, "target": x.target}
                             for x in git_repo.refs(r)]}
        return await self._run(root, work)

    async def show(self, _conn, params):
        """Un commit (`id` : identifiant hexadécimal ou HEAD) et le diff de ses fichiers ;
        au-delà de MAX_DIFF_CHARS au total, les fichiers suivants arrivent sans leurs blocs."""
        root = await self._root(params)
        cid = params.get("id")
        if not isinstance(cid, str) or not _COMMIT_ID.fullmatch(cid):
            raise rpc.RpcError("invalide", "Commit invalide.")

        def work(r):
            c, diffs = git_repo.show(r, cid)
            files, used = [], 0
            for fd in diffs[:MAX_SHOW_FILES]:
                if used >= MAX_DIFF_CHARS:
                    files.append(dict(self._diff_json(dataclasses.replace(fd, hunks=[])),
                                      truncated=bool(fd.hunks)))
                    continue
                one = self._diff_json(fd)
                used += sum(len(l["text"]) for h in one["hunks"] for l in h["lines"])
                files.append(one)
            return {"commit": dict(_commit_json(c), body=c.body), "files": files,
                    "truncated": len(diffs) > MAX_SHOW_FILES}
        return await self._run(root, work)

    @staticmethod
    def _diff_json(fd):
        """Au plus DIFF_LINES lignes et MAX_DIFF_CHARS caractères, lignes coupées à
        MAX_LINE_CHARS : la réponse reste loin de `rpc.MAX_LINE`."""
        total = chars = 0
        hunks, truncated = [], False
        for h in fd.hunks:
            if total >= DIFF_LINES or chars >= MAX_DIFF_CHARS:
                truncated = True
                break
            lines = []
            for line in h.lines:
                if total >= DIFF_LINES or chars >= MAX_DIFF_CHARS:
                    truncated = True
                    break
                text = _cut(line.text)
                lines.append({"kind": line.kind, "text": text, "old_no": line.old_no,
                              "new_no": line.new_no})
                total += 1
                chars += len(text)
            hunks.append({"header": h.header, "lines": lines})
        return {"path": fd.path, "old_path": fd.old_path, "binary": fd.binary,
                "new_file": fd.new_file, "deleted": fd.deleted, "hunks": hunks,
                "truncated": truncated, "too_big": fd.too_big}

    async def diff(self, _conn, params):
        root = await self._root(params)
        path = _rel(params.get("path"))
        staged = params.get("staged") is True

        def work(r):
            fd = git_repo.diff(r, path, staged, max_bytes=MAX_FILE_BYTES)
            return {"diff": None if fd is None else self._diff_json(fd)}
        return await self._run(root, work)

    # ---- indexation ------------------------------------------------------------------

    async def stage(self, _conn, params):
        root, paths = await self._root(params), _paths(params)

        def work(r):
            for p in paths:
                git_repo.stage_file(r, p)
        await self._run(root, work)
        return {}

    async def unstage(self, _conn, params):
        root, paths = await self._root(params), _paths(params)

        def work(r):
            for p in paths:
                git_repo.unstage_file(r, p)
        await self._run(root, work)
        return {}

    async def hunk(self, _conn, params):
        """Indexe ou désindexe un seul bloc (`index`) d'un fichier : toutes ses lignes changées,
        seulement s'il porte encore l'en-tête `@@ … @@` affiché (`header`), sinon `conflit`."""
        root, path = await self._root(params), _rel(params.get("path"))
        action, index, header = params.get("action"), params.get("index"), params.get("header")
        if (action not in ("stage", "unstage") or not isinstance(index, int) or isinstance(index, bool)
                or index < 0 or not isinstance(header, str)):
            raise rpc.RpcError("invalide", "Bloc ou action invalide.")

        def work(r):
            fd = git_repo.diff(r, path, staged=action == "unstage", max_bytes=MAX_FILE_BYTES)
            if fd is None or index >= len(fd.hunks) or fd.hunks[index].header != header:
                raise rpc.RpcError("conflit", "Le fichier a changé : actualise.")
            keep = {(index, li) for li, line in enumerate(fd.hunks[index].lines) if line.kind != " "}
            (git_repo.stage_lines if action == "stage" else git_repo.unstage_lines)(r, fd, keep)
        await self._run(root, work)
        return {}

    async def lines(self, _conn, params):
        """Indexe ou désindexe des lignes choisies d'un fichier : `lines` = [[bloc, ligne], …]
        (indices du diff montré), `headers` = en-têtes `@@ … @@` montrés, bloc par bloc ; si un
        bloc concerné n'a plus le même en-tête : `conflit`."""
        root, path = await self._root(params), _rel(params.get("path"))
        action, picked, headers = params.get("action"), params.get("lines"), params.get("headers")
        if (action not in ("stage", "unstage") or not isinstance(picked, list) or not picked
                or len(picked) > MAX_LINES_PICKED or not isinstance(headers, list)
                or not all(isinstance(h, str) for h in headers)):
            raise rpc.RpcError("invalide", "Lignes ou action invalides.")
        keep = set()
        for pair in picked:
            if (not isinstance(pair, list) or len(pair) != 2
                    or not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0
                               for n in pair)):
                raise rpc.RpcError("invalide", "Lignes ou action invalides.")
            keep.add((pair[0], pair[1]))

        def work(r):
            fd = git_repo.diff(r, path, staged=action == "unstage", max_bytes=MAX_FILE_BYTES)
            for hi, li in keep:
                if (fd is None or hi >= len(fd.hunks) or hi >= len(headers)
                        or fd.hunks[hi].header != headers[hi] or li >= len(fd.hunks[hi].lines)):
                    raise rpc.RpcError("conflit", "Le fichier a changé : actualise.")
            (git_repo.stage_lines if action == "stage" else git_repo.unstage_lines)(r, fd, keep)
        await self._run(root, work)
        return {}

    # ---- écritures -------------------------------------------------------------------

    async def commit(self, _conn, params):
        root = await self._root(params)
        message = params.get("message")
        if not isinstance(message, str):
            raise rpc.RpcError("invalide", "Message du commit manquant.")
        amend = params.get("amend") is True
        return {"id": await self._run(root, lambda r: git_repo.commit(r, message, amend=amend))}

    async def fetch(self, _conn, params):
        await self._run(await self._root(params), git_repo.fetch, network=True)
        return {}

    async def pull(self, _conn, params):
        await self._run(await self._root(params), git_repo.pull, network=True)
        return {}

    async def push(self, _conn, params):
        force = params.get("force", False)
        if not isinstance(force, bool):
            raise rpc.RpcError("invalide", "Option de push invalide.")
        await self._run(await self._root(params), lambda r: git_repo.push(r, force=force), network=True)
        return {}
