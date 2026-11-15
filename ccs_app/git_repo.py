"""Dépôt git du projet d'une session : lecture et écritures par la commande `git` du système.

La commande installée est utilisée telle quelle (comme GiGit) : configuration, hooks, agent
SSH et gestionnaire d'identifiants marchent comme dans un terminal. Aucune fonction de ce
module ne touche à GTK ; l'interface les appelle hors de son fil (`in_thread`).
"""

import os
import re
import subprocess
from dataclasses import dataclass, field

# Un enregistrement par commit : champs séparés par NUL, enregistrements par RS (0x1e).
LOG_FORMAT = "%H%x00%P%x00%an%x00%ae%x00%at%x00%s%x00%b%x1e"
_HUNK = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class GitError(Exception):
    """Commande git en échec : la commande, sa sortie complète et son code."""

    def __init__(self, command, output, code):
        self.command = command
        self.output = output
        self.code = code
        last = next((l for l in reversed(output.strip().splitlines()) if l.strip()), "")
        super().__init__(last or f"git a échoué (code {code})")


def _env(extra=None):
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"})
    if extra:
        env.update(extra)
    return env


def run(repo, *args, input=None, env=None, timeout=60, ok_codes=(0,)):
    """`git -C repo args…` ; sortie standard en octets. Lève `GitError` si le code n'est pas
    dans `ok_codes` (ou si git est introuvable, ou trop long)."""
    argv = ["git", "-c", "core.quotePath=false", "-C", str(repo), *args]
    command = " ".join(["git", *args])
    try:
        proc = subprocess.run(argv, input=input, capture_output=True, env=_env(env),
                              timeout=timeout)
    except FileNotFoundError:
        raise GitError(command, "La commande git est introuvable.", 127) from None
    except subprocess.TimeoutExpired as e:
        out = (e.stderr or b"").decode("utf-8", "replace")
        raise GitError(command, out + f"\nArrêtée après {timeout:g} s.", -1) from None
    if proc.returncode not in ok_codes:
        out = (proc.stderr + proc.stdout).decode("utf-8", "replace")
        raise GitError(command, out, proc.returncode)
    return proc.stdout


def _text(raw):
    return raw.decode("utf-8", "replace")


def is_repo(path):
    try:
        return _text(run(path, "rev-parse", "--is-inside-work-tree")).strip() == "true"
    except GitError:
        return False


def toplevel(path):
    try:
        return _text(run(path, "rev-parse", "--show-toplevel")).strip() or None
    except GitError:
        return None


# ---- historique ----------------------------------------------------------------------

@dataclass
class Commit:
    id: str
    parents: list
    author: str
    email: str
    time: int
    subject: str
    body: str = ""


@dataclass
class Ref:
    name: str
    kind: str      # "head", "branch", "remote" ou "tag"
    target: str


def _parse_log(raw):
    out = []
    for rec in _text(raw).split("\x1e"):
        rec = rec.lstrip("\n")
        f = rec.split("\0", 6)
        if len(f) < 7 or not f[0]:
            continue
        try:
            when = int(f[4])
        except ValueError:
            when = 0
        out.append(Commit(f[0], f[1].split(), f[2], f[3], when, f[5], f[6].rstrip("\n")))
    return out


def log(repo, skip=0, limit=200):
    """Commits de toutes les références, du plus récent au plus ancien (ordre des dates, comme
    GiGit), page par page. Dépôt sans commit : liste vide."""
    try:
        raw = run(repo, "log", "--all", "--date-order", "--no-color", "--no-show-signature",
                  f"--format={LOG_FORMAT}", f"--skip={int(skip)}", f"-n{int(limit)}")
    except GitError:
        if not refs(repo):        # dépôt vide : pas une erreur (lève si ce n'est pas un dépôt)
            return []
        raise
    return _parse_log(raw)


def refs(repo):
    """Branches locales et distantes, tags (cible : le commit, même pour un tag annoté) et
    HEAD s'il désigne un commit."""
    raw = _text(run(repo, "for-each-ref",
                    "--format=%(refname)%00%(objectname)%00%(*objectname)",
                    "refs/heads", "refs/remotes", "refs/tags"))
    out = []
    for line in raw.splitlines():
        parts = line.split("\0")
        if len(parts) < 2:
            continue
        name, oid = parts[0], parts[1]
        peeled = parts[2] if len(parts) > 2 else ""
        if name.startswith("refs/heads/"):
            kind, short = "branch", name[len("refs/heads/"):]
        elif name.startswith("refs/remotes/"):
            short = name[len("refs/remotes/"):]
            if short.endswith("/HEAD"):
                continue
            kind = "remote"
        elif name.startswith("refs/tags/"):
            kind, short = "tag", name[len("refs/tags/"):]
        else:
            continue
        out.append(Ref(short, kind, peeled or oid))
    try:
        head = _text(run(repo, "rev-parse", "--verify", "-q", "HEAD")).strip()
    except GitError:
        head = ""
    if head:
        out.append(Ref("HEAD", "head", head))
    return out


# ---- branche et état -----------------------------------------------------------------

@dataclass
class Branch:
    name: object          # None : HEAD détachée
    upstream: object
    ahead: int
    behind: int


def branch(repo):
    raw = _text(run(repo, "status", "--porcelain=v2", "--branch", "--untracked-files=no"))
    name, upstream, ahead, behind = None, None, 0, 0
    for line in raw.splitlines():
        if line.startswith("# branch.head "):
            value = line[len("# branch.head "):]
            name = None if value == "(detached)" else value
        elif line.startswith("# branch.upstream "):
            upstream = line[len("# branch.upstream "):]
        elif line.startswith("# branch.ab "):
            for part in line[len("# branch.ab "):].split():
                if part.startswith("+"):
                    ahead = int(part[1:])
                elif part.startswith("-"):
                    behind = int(part[1:])
    return Branch(name, upstream, ahead, behind)


@dataclass
class FileStatus:
    path: str
    staged: str           # lettre de l'index (`.` : rien), `?` : non suivi
    unstaged: str         # lettre de la copie de travail
    orig_path: object = None


def status(repo):
    raw = _text(run(repo, "status", "--porcelain=v2", "-z", "--untracked-files=all"))
    items = raw.split("\0")
    out, i = [], 0
    while i < len(items):
        entry = items[i]
        i += 1
        if not entry:
            continue
        kind = entry[0]
        if kind == "?":
            out.append(FileStatus(entry[2:], "?", "?"))
        elif kind == "1":
            f = entry.split(" ", 8)
            out.append(FileStatus(f[8], f[1][0], f[1][1]))
        elif kind == "2":
            f = entry.split(" ", 9)
            orig = items[i] if i < len(items) else None
            i += 1
            out.append(FileStatus(f[9], f[1][0], f[1][1], orig))
        elif kind == "u":
            f = entry.split(" ", 10)
            out.append(FileStatus(f[10], f[1][0], f[1][1]))
    return out


# ---- diff ----------------------------------------------------------------------------

@dataclass
class DiffLine:
    kind: str             # " ", "+" ou "-"
    text: str
    old_no: object
    new_no: object


@dataclass
class Hunk:
    header: str
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    lines: list = field(default_factory=list)


@dataclass
class FileDiff:
    path: str
    old_path: object
    binary: bool
    hunks: list
    new_file: bool = False
    deleted: bool = False


_ESC = {b"n": b"\n", b"t": b"\t", b"\\": b"\\", b'"': b'"', b"a": b"\a", b"b": b"\b",
        b"f": b"\f", b"r": b"\r", b"v": b"\v"}


def _unquote(raw):
    """Chemin tel que git l'écrit (entre guillemets à la C s'il contient des caractères
    spéciaux) → texte."""
    if not raw.startswith(b'"') or not raw.endswith(b'"') or len(raw) < 2:
        return _text(raw)
    body, out, i = raw[1:-1], bytearray(), 0
    while i < len(body):
        c = body[i:i + 1]
        if c == b"\\" and i + 1 < len(body):
            nxt = body[i + 1:i + 2]
            if nxt.isdigit() and i + 3 < len(body) + 1:
                out.append(int(body[i + 1:i + 4], 8))
                i += 4
                continue
            out += _ESC.get(nxt, nxt)
            i += 2
            continue
        out += c
        i += 1
    return _text(bytes(out))


def _strip_prefix(path):
    return path[2:] if path[:2] in ("a/", "b/") else path


def _header_path(rest):
    """`diff --git a/X b/X` sans renommage : X, même avec des espaces."""
    if rest.startswith(b'"'):
        end = rest.find(b'" ', 1)
        while end != -1 and rest[end - 1:end] == b"\\":
            end = rest.find(b'" ', end + 1)
        first = rest[:end + 1] if end != -1 else rest
        return _strip_prefix(_unquote(first))
    half = (len(rest) - 1) // 2
    return _strip_prefix(_text(rest[:half]))


def parse_diff(raw):
    """Sortie de `git diff`/`git show` (format unifié) → liste de `FileDiff`."""
    files, cur, hunk = [], None, None
    old_no = new_no = 0
    for line in raw.split(b"\n"):
        if line.startswith(b"diff --git "):
            cur = FileDiff(_header_path(line[len(b"diff --git "):]), None, False, [])
            files.append(cur)
            hunk = None
            continue
        if cur is None:
            continue
        if hunk is not None and line[:1] in (b" ", b"+", b"-") and not (
                line.startswith(b"--- ") and hunk_done(hunk, old_no, new_no)):
            kind = line[:1].decode()
            text = _text(line[1:])
            if kind == " ":
                hunk.lines.append(DiffLine(" ", text, old_no, new_no))
                old_no += 1
                new_no += 1
            elif kind == "-":
                hunk.lines.append(DiffLine("-", text, old_no, None))
                old_no += 1
            else:
                hunk.lines.append(DiffLine("+", text, None, new_no))
                new_no += 1
            continue
        if line.startswith(b"@@"):
            m = _HUNK.match(line)
            if m:
                o, ol, n, nl = m.groups()
                hunk = Hunk(_text(line), int(o), int(ol) if ol is not None else 1,
                            int(n), int(nl) if nl is not None else 1)
                cur.hunks.append(hunk)
                old_no, new_no = int(o), int(n)
            continue
        if line.startswith(b"\\"):
            continue            # « \ No newline at end of file »
        hunk = None
        if line.startswith(b"new file mode"):
            cur.new_file = True
        elif line.startswith(b"deleted file mode"):
            cur.deleted = True
        elif line.startswith(b"rename from "):
            cur.old_path = _unquote(line[len(b"rename from "):])
        elif line.startswith(b"rename to "):
            cur.path = _unquote(line[len(b"rename to "):])
        elif line.startswith(b"Binary files ") or line.startswith(b"GIT binary patch"):
            cur.binary = True
        elif line.startswith(b"--- ") and line[4:] != b"/dev/null":
            cur.old_path = cur.old_path or _strip_prefix(_unquote(line[4:]))
        elif line.startswith(b"+++ ") and line[4:] != b"/dev/null":
            cur.path = _strip_prefix(_unquote(line[4:]))
    for f in files:
        if f.old_path == f.path:
            f.old_path = None
    return files


def hunk_done(hunk, old_no, new_no):
    """Le bloc a reçu toutes ses lignes (une ligne `--- ` qui suit est un nouvel en-tête)."""
    return (old_no >= hunk.old_start + hunk.old_len
            and new_no >= hunk.new_start + hunk.new_len)


_DIFF_OPTS = ("--no-color", "--no-ext-diff", "-M")


def _untracked(repo, path):
    try:
        run(repo, "ls-files", "--error-unmatch", "--", path)
        return False
    except GitError:
        return True


def diff(repo, path, staged):
    """Diff d'un fichier : indexé (`staged`) ou non indexé ; fichier non suivi : contre
    /dev/null. None s'il n'y a pas de différence."""
    if staged:
        raw = run(repo, "diff", "--cached", *_DIFF_OPTS, "--", path)
    elif _untracked(repo, path):
        raw = run(repo, "diff", "--no-index", *_DIFF_OPTS, "--", "/dev/null", path,
                  ok_codes=(0, 1))
    else:
        raw = run(repo, "diff", *_DIFF_OPTS, "--", path)
    files = parse_diff(raw)
    return files[0] if files else None


def show(repo, cid):
    """Un commit et les fichiers qu'il change (fusion : contre son premier parent)."""
    raw = run(repo, "show", "--no-color", "--no-ext-diff", "-M", "--no-show-signature",
              "--diff-merges=first-parent", f"--format={LOG_FORMAT}", cid)
    head, sep, patch = raw.partition(b"\x1e")
    commits = _parse_log(head + sep)
    if not commits:
        raise GitError(f"git show {cid}", "Commit introuvable.", 1)
    return commits[0], parse_diff(patch)
