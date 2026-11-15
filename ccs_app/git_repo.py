"""Dépôt git du projet d'une session : lecture et écritures par la commande `git` du système.

La commande installée est utilisée telle quelle (comme GiGit) : configuration, hooks, agent
SSH et gestionnaire d'identifiants marchent comme dans un terminal. Aucune fonction de ce
module ne touche à GTK ; l'interface les appelle hors de son fil (`in_thread`).
"""

import os
import re
import stat
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


def run(repo, *args, input=None, env=None, timeout=60, ok_codes=(0,), detach=False):
    """`git -C repo args…` ; sortie standard en octets. Lève `GitError` si le code n'est pas
    dans `ok_codes` (ou si git est introuvable, ou trop long). Sans `input`, l'entrée standard
    est vide : git ne lit jamais celle de l'appelant. `detach` : nouvelle session, sans
    terminal où une invite pourrait s'afficher."""
    argv = ["git", "-c", "core.quotePath=false", "-C", str(repo), *args]
    command = " ".join(["git", *args])
    feed = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
    try:
        proc = subprocess.run(argv, capture_output=True, env=_env(env), timeout=timeout,
                              start_new_session=detach, **feed)
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
    raw: bytes = None     # octets de la ligne tels que git les donne (correctifs : jamais `text`)
    no_eol: bool = False  # suivie de « \ No newline at end of file »


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
    too_big: bool = False         # diff non calculé : fichier plus gros que la limite demandée


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
            raw = line[1:]
            text = _text(raw)
            if kind == " ":
                hunk.lines.append(DiffLine(" ", text, old_no, new_no, raw))
                old_no += 1
                new_no += 1
            elif kind == "-":
                hunk.lines.append(DiffLine("-", text, old_no, None, raw))
                old_no += 1
            else:
                hunk.lines.append(DiffLine("+", text, None, new_no, raw))
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
        if line.startswith(b"\\"):        # « \ No newline at end of file » : ligne précédente
            if hunk is not None and hunk.lines:
                hunk.lines[-1].no_eol = True
            continue
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
        elif line.startswith((b"--- ", b"+++ ")):
            # git termine par une tabulation un nom qui contient des espaces
            name = line[4:].rstrip(b"\t")
            if name != b"/dev/null":
                if line.startswith(b"--- "):
                    cur.old_path = cur.old_path or _strip_prefix(_unquote(name))
                else:
                    cur.path = _strip_prefix(_unquote(name))
    for f in files:
        if f.old_path == f.path:
            f.old_path = None
    return files


def hunk_done(hunk, old_no, new_no):
    """Le bloc a reçu toutes ses lignes (une ligne `--- ` qui suit est un nouvel en-tête)."""
    return (old_no >= hunk.old_start + hunk.old_len
            and new_no >= hunk.new_start + hunk.new_len)


_DIFF_OPTS = ("--no-color", "--no-ext-diff", "-M")
_LITERAL = {"GIT_LITERAL_PATHSPECS": "1"}     # un chemin est un nom de fichier, jamais un motif


def _untracked(repo, path):
    """Vrai seulement pour un fichier non suivi que git liste lui-même (`ls-files -o`, exactement
    ce chemin) : jamais un fichier ignoré, derrière un lien ou hors du dépôt, ni « - » (l'entrée
    standard pour `--no-index`), ni un dossier ou un lien vers un dossier (que `--no-index`
    parcourrait)."""
    if path == "-":
        return False
    try:
        out = run(repo, "ls-files", "-z", "-o", "--exclude-standard", "--", path, env=_LITERAL)
    except GitError:
        return False
    if out.split(b"\0")[:-1] != [os.fsencode(path)]:
        return False
    full = os.path.join(str(repo), path)
    try:
        mode = os.lstat(full).st_mode
    except OSError:
        return False
    if stat.S_ISLNK(mode):
        return not os.path.isdir(full)
    return stat.S_ISREG(mode)


def _file_size(repo, path):
    try:
        st = os.lstat(os.path.join(str(repo), path))
    except OSError:
        return 0
    return st.st_size if stat.S_ISREG(st.st_mode) else 0


def _blob_size(repo, spec):
    try:
        return int(run(repo, "cat-file", "-s", spec, ok_codes=(0, 128)).strip() or 0)
    except (GitError, ValueError):
        return 0


def _too_big(repo, path, staged, untracked, max_bytes):
    if staged:
        sizes = (_blob_size(repo, f":0:{path}"), _blob_size(repo, f"HEAD:{path}"))
    elif untracked:
        sizes = (_file_size(repo, path),)
    else:
        sizes = (_file_size(repo, path), _blob_size(repo, f":0:{path}"))
    return max(sizes) > max_bytes


def _differs(repo, path, staged):
    try:
        run(repo, "diff", "--quiet", *(("--cached",) if staged else ()), "--", path, env=_LITERAL)
    except GitError as e:
        if e.code == 1:
            return True
        raise
    return False


def diff(repo, path, staged, max_bytes=None):
    """Diff d'un fichier : indexé (`staged`) ou non indexé ; fichier non suivi : contre
    /dev/null. None s'il n'y a pas de différence, ou si git ne suit pas ce chemin et ne le
    liste pas comme non suivi (ignoré, derrière un lien…). `max_bytes` : si la copie de
    travail, l'index ou HEAD dépasse cette taille, le diff n'est pas calculé (`too_big`)."""
    untracked = not staged and _untracked(repo, path)
    if max_bytes is not None and _too_big(repo, path, staged, untracked, max_bytes):
        if not untracked and not _differs(repo, path, staged):
            return None
        return FileDiff(path, None, False, [], new_file=untracked, too_big=True)
    if staged:
        raw = run(repo, "diff", "--cached", *_DIFF_OPTS, "--", path, env=_LITERAL)
    elif untracked:
        raw = run(repo, "diff", "--no-index", *_DIFF_OPTS, "--", "/dev/null", path,
                  ok_codes=(0, 1))
    else:
        raw = run(repo, "diff", *_DIFF_OPTS, "--", path, env=_LITERAL)
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


# ---- écritures -----------------------------------------------------------------------

def _has_head(repo):
    try:
        run(repo, "rev-parse", "--verify", "-q", "HEAD")
        return True
    except GitError:
        return False


def stage_file(repo, path):
    run(repo, "add", "-A", "--", path)


def unstage_file(repo, path):
    if _has_head(repo):
        run(repo, "reset", "-q", "HEAD", "--", path)
    else:
        run(repo, "rm", "-q", "--cached", "--", path)


def _abs(repo, path):
    return os.path.join(toplevel(repo) or str(repo), path)


def discard_file(repo, fs):
    """Remet un fichier dans son état du dernier commit (non suivi ou ajouté : supprimé).
    L'interface demande toujours confirmation avant."""
    if fs.staged == "?":
        target = _abs(repo, fs.path)
        if os.path.isdir(target) and not os.path.islink(target):
            raise GitError(f"supprimer {fs.path}", "C'est un dossier : rien n'est supprimé.", 1)
        os.remove(target)
    elif fs.staged == "A":
        run(repo, "rm", "-q", "-f", "--cached", "--", fs.path)
        try:
            os.remove(_abs(repo, fs.path))
        except FileNotFoundError:
            pass
    elif fs.staged not in (".", "?"):
        run(repo, "restore", "--source=HEAD", "--staged", "--worktree", "--", fs.path)
        if fs.orig_path:
            run(repo, "restore", "--source=HEAD", "--staged", "--worktree", "--", fs.orig_path)
    else:
        run(repo, "restore", "--worktree", "--", fs.path)


def _quote(path):
    """Chemin pour un en-tête de correctif : entre guillemets à la C s'il le faut."""
    raw = path.encode("utf-8")
    if all(32 < b < 127 and b not in (34, 92) for b in raw):
        return path
    out = []
    for b in raw:
        if b == 34:
            out.append('\\"')
        elif b == 92:
            out.append("\\\\")
        elif 32 <= b < 127:
            out.append(chr(b))
        else:
            out.append("\\%03o" % b)
    return '"' + "".join(out) + '"'


_NO_EOL = b"\\ No newline at end of file"


def _fix_eol(lines):
    """`lines` : [type, octets, sans fin de ligne] d'un bloc retouché. De chaque côté du
    correctif (ancien : contexte et `-`, nouveau : contexte et `+`), seule la dernière ligne
    peut manquer de saut de ligne : une ligne qui n'est plus la dernière de son côté le
    retrouve ; une ligne de contexte qui ne l'est plus que d'un côté est dédoublée (`-` et
    `+`, chacune avec sa fin)."""
    out = []
    for i, (kind, raw, no_eol) in enumerate(lines):
        if no_eol:
            later = lines[i + 1:]
            more_old = any(k in " -" for k, _r, _e in later)
            more_new = any(k in " +" for k, _r, _e in later)
            if kind == " " and more_old != more_new:
                out += [["-", raw, not more_old], ["+", raw, not more_new]]
                continue
            if (kind == "-" and more_old) or (kind == "+" and more_new) or (more_old and more_new):
                no_eol = False
        out.append([kind, raw, no_eol])
    return out


def patch_for(fd, keep, reverse=False):
    """Correctif ne gardant que les lignes `(bloc, ligne)` de `keep`, en octets : les lignes
    sont recopiées telles que git les a données (fichier qui n'est pas en UTF-8 intact) et
    « \\ No newline at end of file » est réécrit après la ligne qu'il suit.

    Sens direct (indexer) : un `+` non choisi disparaît, un `-` non choisi devient du
    contexte. Sens inverse (`reverse`, appliqué avec `-R` : désindexer, annuler) : un `-` non
    choisi disparaît, un `+` non choisi devient du contexte. Blocs sans ligne choisie omis ;
    en-têtes recalculés (`git apply --recount` les recompte aussi)."""
    old = fd.old_path or fd.path
    a = "/dev/null" if fd.new_file else _quote("a/" + old)
    b = "/dev/null" if fd.deleted else _quote("b/" + fd.path)
    body, delta = [], 0
    for hi, h in enumerate(fd.hunks):
        lines, chosen = [], False
        for li, l in enumerate(h.lines):
            picked = (hi, li) in keep
            raw = l.raw if l.raw is not None else l.text.encode("utf-8")
            if l.kind == " ":
                lines.append([" ", raw, l.no_eol])
            elif picked:
                lines.append([l.kind, raw, l.no_eol])
                chosen = True
            elif (l.kind == "-") != reverse:
                lines.append([" ", raw, l.no_eol])     # garde la ligne telle qu'elle est des deux côtés
        if not chosen:
            continue
        lines = _fix_eol(lines)
        old_len = sum(1 for k, _r, _e in lines if k in " -")
        new_len = sum(1 for k, _r, _e in lines if k in " +")
        if reverse:
            new_start = h.new_start
            old_start = new_start - delta
        else:
            old_start = h.old_start
            new_start = old_start + delta
        delta += new_len - old_len
        body.append(f"@@ -{old_start},{old_len} +{new_start},{new_len} @@".encode())
        for kind, raw, no_eol in lines:
            body.append(kind.encode() + raw)
            if no_eol:
                body.append(_NO_EOL)
    if not body:
        return b""
    head = [f"diff --git {_quote('a/' + old)} {_quote('b/' + fd.path)}"]
    if fd.new_file:
        head.append("new file mode 100644")
    if fd.deleted:
        head.append("deleted file mode 100644")
    head += [f"--- {a}", f"+++ {b}"]
    return b"\n".join([h.encode("utf-8") for h in head] + body) + b"\n"


def _apply(repo, patch, *flags):
    if patch:
        run(repo, "apply", "--recount", "--whitespace=nowarn", *flags, "-", input=patch)


def stage_lines(repo, fd, keep):
    _apply(repo, patch_for(fd, keep), "--cached")


def unstage_lines(repo, fd, keep):
    _apply(repo, patch_for(fd, keep, reverse=True), "--cached", "-R")


def discard_lines(repo, fd, keep):
    _apply(repo, patch_for(fd, keep, reverse=True), "-R")


def commit(repo, message, amend=False):
    """Commit de l'index (hooks et signature selon la configuration) ; renvoie son id."""
    if not message.strip():
        raise GitError("git commit", "Le message du commit est vide.", 1)
    args = ["commit", "-q", "--cleanup=strip", "-F", "-"]
    if amend:
        args.append("--amend")
    run(repo, *args, input=message.encode("utf-8"), timeout=300)
    return _text(run(repo, "rev-parse", "HEAD")).strip()


def last_message(repo):
    return _text(run(repo, "log", "-1", "--format=%B")).strip()


def ignore(repo, relpath):
    """Ajoute `/relpath` au .gitignore de la racine (sans doublon)."""
    path = os.path.join(toplevel(repo) or str(repo), ".gitignore")
    entry = "/" + relpath.lstrip("/")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    if entry in (l.strip() for l in text.splitlines()):
        return
    if text and not text.endswith("\n"):
        text += "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + entry + "\n")


# Jamais de demande de mot de passe : ni terminal, ni fenêtre (askpass, gestionnaire
# d'identifiants), ni phrase de passe SSH ; agent SSH et identifiants enregistrés marchent.
_NO_PROMPT = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "SSH_ASKPASS": "",
              "SSH_ASKPASS_REQUIRE": "never", "GCM_INTERACTIVE": "never"}


def _config(repo, key):
    try:
        return _text(run(repo, "config", "--get", key, ok_codes=(0, 1))).strip()
    except GitError:
        return ""


def _network_env(repo, prompt=False):
    """Variables de fetch, pull et push : sans invite ; SSH en BatchMode, sauf si l'utilisateur
    ou le dépôt choisit déjà sa commande SSH (`core.sshCommand` n'est jamais écrasé). `prompt` :
    le bureau garde la fenêtre de mot de passe de la session (askpass)."""
    if prompt:
        return None
    env = dict(_NO_PROMPT)
    if not (os.environ.get("GIT_SSH_COMMAND") or os.environ.get("GIT_SSH")
            or _config(repo, "core.sshCommand")):
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"
    return env


def fetch(repo):
    run(repo, "fetch", "--prune", "--quiet", env=_network_env(repo), timeout=120, detach=True)


def pull(repo, prompt=False):
    run(repo, "pull", "--ff-only", "--quiet", env=_network_env(repo, prompt), timeout=300, detach=True)


def _remote(repo):
    remotes = _text(run(repo, "remote")).split()
    if not remotes:
        raise GitError("git push", "Ce dépôt n'a pas de dépôt distant.", 1)
    return "origin" if "origin" in remotes else remotes[0]


def push(repo, force=False, prompt=False):
    """Pousse la branche courante (premier push : crée la branche distante). Forcé :
    `--force-with-lease --force-if-includes`, qui refuse d'écraser un commit distant pas vu.
    `prompt` : voir `_network_env`."""
    b = branch(repo)
    if b.name is None:
        raise GitError("git push", "HEAD est détachée : aucune branche à pousser.", 1)
    args = ["push", "--quiet"]
    if force:
        args += ["--force-with-lease", "--force-if-includes"]
    if b.upstream is None:
        args += ["--set-upstream", _remote(repo), b.name]
    run(repo, *args, env=_network_env(repo, prompt), timeout=300, detach=True)


FLOW_KINDS = ("feature", "release", "hotfix")


def flow_available():
    try:
        return subprocess.run(["git", "flow", "version"], capture_output=True, env=_env(),
                              timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def flow(repo, kind, action, name=None):
    """`git flow <kind> start|finish [name]` ; finir une release ou un hotfix pose le tag avec
    le message `name`, sans ouvrir d'éditeur."""
    if kind not in FLOW_KINDS or action not in ("start", "finish"):
        raise ValueError(f"git flow {kind} {action} : non pris en charge")
    args = ["flow", kind, action]
    if action == "finish" and kind in ("release", "hotfix"):
        args += ["-m", name or ""]
    if name:
        args.append(name)
    run(repo, *args, env={"GIT_MERGE_AUTOEDIT": "no", "GIT_EDITOR": "true"}, timeout=300)


_VERBS = {"A": "ajoute", "M": "modifie", "D": "supprime", "R": "renomme", "C": "copie",
          "T": "modifie"}


def propose_message(repo, files=None):
    """Message de commit proposé d'après les seuls fichiers indexés (sans appel à Claude) ;
    vide si rien n'est indexé. `files` : résultat de `status` déjà lu."""
    staged = [s for s in (status(repo) if files is None else files) if s.staged not in (".", "?")]
    if not staged:
        return ""
    paths = [s.path for s in staged]
    if all(p.endswith(".md") or p.startswith("docs/") for p in paths):
        kind = "docs"
    elif all(p.startswith("tests/") for p in paths):
        kind = "test"
    else:
        kind = "chore"
    if len(staged) == 1:
        title = f"{kind}: {_VERBS.get(staged[0].staged, 'modifie')} {staged[0].path}"
    else:
        title = f"{kind}: {len(staged)} fichiers"
    return title + "\n\n" + "\n".join(f"- {s.staged} {s.path}" for s in staged)
