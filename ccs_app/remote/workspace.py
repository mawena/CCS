"""Espace de session d'un chat distant : les vues du panneau de gauche (Fichiers, Feuille de route,
Git) et l'éditeur lisent et écrivent le dossier du serveur par les RPC du pont.

`RemoteWorkspace(client)` : `client` a `call_sync(method, timeout=…, **params)` (le
`SyncBridgeClient` d'une `RemoteConnection`). Tous les appels sont bloquants : ils ne se font que
depuis les fils de travail des vues (`in_thread`), jamais depuis le fil GTK.

- `.git` imite le module `git_repo` (mêmes noms, mêmes objets rendus, erreurs `GitError`) ; ce qui
  n'a pas d'équivalent dans le pont vaut None (annuler des modifications, .gitignore, git flow) et
  la vue le masque ;
- `.files` : liste des dossiers et marques git (arbre), lecture et enregistrement (éditeur) ;
- `.roadmap` : lecture et coche de la feuille de route.
"""

import base64
import threading
import time
from pathlib import Path

from .. import file_tree, git_repo, roadmap
from ..server import rpc

NET_TIMEOUT = 330          # fetch / pull / push : le pont attend jusqu'à 300 s
STATUS_TTL = 1.5           # un même rafraîchissement demande l'état plusieurs fois
UNREACHABLE = "Serveur injoignable"


def _reason(e):
    if isinstance(e, rpc.RpcError):
        return e.message
    return f"{UNREACHABLE} ({e.__class__.__name__})" if not str(e) else f"{UNREACHABLE} : {e}"


class RemoteGit:
    """Le module `git_repo` vu à travers le pont (`repo` : le dossier du serveur)."""

    GitError = git_repo.GitError
    FLOW_KINDS = git_repo.FLOW_KINDS
    FLOW_UNAVAILABLE = "git flow n'est pas disponible sur une session distante"
    remote = True
    # sans équivalent dans le pont : masqués par les vues
    discard_file = discard_lines = ignore = None

    def __init__(self, ws):
        self._ws = ws
        self._cache = {}
        self._lock = threading.Lock()

    def _call(self, method, timeout=30, **params):
        try:
            return self._ws.call(method, timeout=timeout, **params)
        except Exception as e:  # noqa: BLE001 — RPC, réseau, délai : une erreur git pour la vue
            raise git_repo.GitError(method, _reason(e), 1) from None

    def _write(self, method, repo, timeout=30, **params):
        self.forget(repo)
        try:
            return self._call(method, timeout=timeout, cwd=str(repo), **params)
        finally:
            self.forget(repo)

    def forget(self, repo=None):
        with self._lock:
            if repo is None:
                self._cache.clear()
            else:
                self._cache.pop(str(repo), None)

    def _status(self, repo):
        key = str(repo)
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and time.monotonic() - hit[0] < STATUS_TTL:
                return hit[1]
        r = self._call("git.status", cwd=key)
        with self._lock:
            self._cache[key] = (time.monotonic(), r)
        return r

    def _repo_status(self, repo):
        r = self._status(repo)
        if not r.get("repo"):
            raise git_repo.GitError("git.status", "Ce dossier n'est pas un dépôt git.", 128)
        return r

    # ---- lecture -------------------------------------------------------------------------

    def is_repo(self, repo):
        try:
            return bool(self._status(repo).get("repo"))
        except git_repo.GitError:
            return False

    def toplevel(self, repo):
        try:
            r = self._status(repo)
        except git_repo.GitError:
            return None
        return r.get("root") if r.get("repo") else None

    def branch(self, repo):
        b = self._repo_status(repo).get("branch") or {}
        return git_repo.Branch(b.get("name"), b.get("upstream"), int(b.get("ahead") or 0),
                               int(b.get("behind") or 0))

    def status(self, repo):
        return [git_repo.FileStatus(f["path"], f["staged"], f["unstaged"], f.get("orig_path"))
                for f in self._repo_status(repo).get("files") or []]

    def last_message(self, repo):
        return self._repo_status(repo).get("last_message") or ""

    def propose_message(self, repo, files=None):
        self.forget(repo)
        return self._repo_status(repo).get("proposed") or ""

    @staticmethod
    def _diff(d):
        if d is None:
            return None
        hunks = []
        for h in d.get("hunks") or []:
            lines = [git_repo.DiffLine(l["kind"], l["text"], l.get("old_no"), l.get("new_no"))
                     for l in h.get("lines") or []]
            hunks.append(git_repo.Hunk(h["header"], 0, 0, 0, 0, lines))
        return git_repo.FileDiff(d["path"], d.get("old_path"), bool(d.get("binary")), hunks,
                                 new_file=bool(d.get("new_file")), deleted=bool(d.get("deleted")),
                                 too_big=bool(d.get("too_big")))

    def diff(self, repo, path, staged, max_bytes=None):
        r = self._call("git.diff", cwd=str(repo), path=path, staged=bool(staged))
        return self._diff(r.get("diff"))

    @staticmethod
    def _commit(c):
        return git_repo.Commit(c["id"], list(c.get("parents") or []), c.get("author", ""),
                               c.get("email", ""), int(c.get("time") or 0), c.get("subject", ""),
                               c.get("body", ""))

    def log(self, repo, skip=0, limit=200):
        r = self._call("git.log", cwd=str(repo), skip=int(skip), limit=int(limit))
        return [self._commit(c) for c in r.get("commits") or []]

    def refs(self, repo):
        r = self._call("git.refs", cwd=str(repo))
        return [git_repo.Ref(x["name"], x["kind"], x["target"]) for x in r.get("refs") or []]

    def show(self, repo, cid):
        r = self._call("git.show", cwd=str(repo), id=cid)
        return self._commit(r["commit"]), [self._diff(d) for d in r.get("files") or []]

    # ---- écritures -----------------------------------------------------------------------

    def stage_file(self, repo, path):
        self._write("git.stage", repo, paths=[path])

    def unstage_file(self, repo, path):
        self._write("git.unstage", repo, paths=[path])

    def _lines(self, repo, fd, keep, action):
        self._write("git.lines", repo, path=fd.path, action=action,
                    lines=sorted([hi, li] for hi, li in keep),
                    headers=[h.header for h in fd.hunks])

    def stage_lines(self, repo, fd, keep):
        self._lines(repo, fd, keep, "stage")

    def unstage_lines(self, repo, fd, keep):
        self._lines(repo, fd, keep, "unstage")

    def commit(self, repo, message, amend=False):
        return self._write("git.commit", repo, message=message, amend=bool(amend)).get("id")

    def fetch(self, repo):
        self._write("git.fetch", repo, timeout=NET_TIMEOUT)

    def pull(self, repo, prompt=False):
        self._write("git.pull", repo, timeout=NET_TIMEOUT)

    def push(self, repo, force=False, prompt=False):
        self._write("git.push", repo, timeout=NET_TIMEOUT, force=bool(force))

    @staticmethod
    def flow_available():
        return False

    flow = None


class RemoteFiles:
    """Arbre et éditeur : dossiers, marques git, lecture et enregistrement sur le serveur."""

    remote = True

    def __init__(self, ws):
        self._ws = ws

    def git_marks(self, root):
        """{chemin relatif à `root`: "M"|"A"|"?"|"D"}, comme `file_tree.git_marks`."""
        try:
            r = self._ws.call("git.status", cwd=str(root))
        except Exception:  # noqa: BLE001 — pas de marques plutôt qu'un arbre vide
            return {}
        if not r.get("repo"):
            return {}
        top = (r.get("root") or "").rstrip("/")
        base = str(root).rstrip("/")
        if base == top:
            prefix = ""
        elif base.startswith(top + "/"):
            prefix = base[len(top) + 1:] + "/"
        else:
            return {}
        marks = {}
        for f in r.get("files") or []:
            path, xy = f["path"], f["staged"] + f["unstaged"]
            if not path.startswith(prefix):
                continue
            if f["staged"] == "?":
                mark = "?"
            elif "D" in xy:
                mark = "D"
            elif "A" in xy:
                mark = "A"
            else:
                mark = "M"
            marks[path[len(prefix):]] = mark
        return marks

    def list_dir(self, root, dirpath, show_ignored, marks):
        """[(nom, est_dossier, supprimé)] triés, dossiers d'abord (comme `file_panel._list_dir`)."""
        root, dirpath = str(root), str(dirpath)
        rel = "" if dirpath.rstrip("/") == root.rstrip("/") else dirpath[len(root.rstrip("/")) + 1:]
        try:
            r = self._ws.call("files.list", root=root, rel=rel, hide_ignored=not show_ignored)
        except Exception:  # noqa: BLE001 — dossier illisible ou serveur injoignable : vide
            return []
        entries = {e["name"]: (bool(e["dir"]), False) for e in r.get("entries") or []
                   if e["name"] not in file_tree.ALWAYS_HIDDEN}
        prefix = rel + "/" if rel else ""
        for relpath, mark in marks.items():
            if mark == "D" and relpath.startswith(prefix):
                name = relpath[len(prefix):]
                if "/" not in name and name not in entries:
                    entries[name] = (False, True)
        return sorted(((n, d, x) for n, (d, x) in entries.items()),
                      key=lambda t: (not t[1], t[0].casefold(), t[0]))

    def read(self, path):
        """(type, texte, encodage, coupé, cachet), comme `file_editor._read` ; une image arrive
        en octets à la place du texte ; trop gros ou injoignable : « unavailable »."""
        try:
            r = self._ws.call("files.read", path=str(path))
        except rpc.RpcError as e:
            if e.code == "introuvable":
                return "missing", "", "utf-8", False, None
            return "unavailable", e.message, "utf-8", False, None
        except Exception as e:  # noqa: BLE001
            return "unavailable", _reason(e), "utf-8", False, None
        kind, stamp = r.get("kind"), r.get("stamp")
        if kind == "text":
            return "text", r.get("text", ""), r.get("encoding") or "utf-8", False, stamp
        if kind == "image":
            try:
                img = self._ws.call("files.image", path=str(path))
                return "image", base64.b64decode(img["data"]), "utf-8", False, stamp
            except Exception as e:  # noqa: BLE001 — trop grosse, illisible
                return "unavailable", _reason(e), "utf-8", False, stamp
        if kind == "too_big":
            return ("unavailable", "Fichier trop gros pour être ouvert à distance.", "utf-8",
                    False, stamp)
        if kind in ("binary", "missing"):
            return kind, "", "utf-8", False, stamp
        return "unavailable", "", "utf-8", False, stamp

    def save(self, path, text, encoding, stamp):
        """Enregistre sur le serveur (refusé si le fichier a changé depuis `stamp`) ; rend le
        nouveau cachet. Erreur : OSError (message en français)."""
        params = {"path": str(path), "text": text}
        if stamp is not None:
            params["stamp"] = list(stamp)
        try:
            return self._ws.call("files.write", **params)["stamp"]
        except Exception as e:  # noqa: BLE001
            raise OSError(_reason(e)) from None


class RemoteRoadmap:
    """Feuille de route du serveur : lue (puis analysée ici, mêmes objets qu'en local) et cochée."""

    remote = True

    def __init__(self, ws):
        self._ws = ws

    def _text(self, path):
        r = self._ws.call("files.read", path=str(path))
        return r.get("text") if r.get("kind") == "text" else None

    def load(self, cwd, followed=None):
        """(chemin, Roadmap, est un projet) ; (None, None, …) sans feuille de route."""
        path = text = None
        try:
            if followed is not None:
                path = Path(str(followed))
                text = self._text(path)
            if text is None:
                found = self._ws.call("roadmap.read", cwd=str(cwd)).get("path")
                path = Path(found) if found else None
                text = self._text(path) if path is not None else None
        except Exception:  # noqa: BLE001 — injoignable, refusé : pas de feuille affichée
            path = text = None
        if text is None:
            return None, None, self.is_project(cwd)
        return path, roadmap.parse(text, path), True

    def is_project(self, cwd):
        try:
            return bool(self._ws.call("git.status", cwd=str(cwd)).get("repo"))
        except Exception:  # noqa: BLE001
            return False

    def toggle(self, path, line, text):
        try:
            self._ws.call("roadmap.toggle", path=str(path), line=int(line), text=text)
            return True
        except Exception:  # noqa: BLE001 — conflit ou injoignable : relire
            return False


class RemoteWorkspace:
    """Les sources distantes d'un espace de session (`client.call_sync`)."""

    remote = True

    def __init__(self, client, label=""):
        self.client = client
        self.label = label
        self.git = RemoteGit(self)
        self.files = RemoteFiles(self)
        self.roadmap = RemoteRoadmap(self)

    def call(self, method, timeout=30, **params):
        return self.client.call_sync(method, timeout=timeout, **params)

    def add_night_task(self, cwd, message, info):
        """Tâche de la feuille de route dans la file de nuit du serveur ; erreur : ValueError."""
        try:
            return self.call("tasks.add", cwd=str(cwd), message=message, when="nuit",
                             roadmap=info)
        except Exception as e:  # noqa: BLE001
            raise ValueError(_reason(e)) from None
