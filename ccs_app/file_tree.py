"""Fichiers d'un projet, sans GTK : marques git, type de fichier, lecture et
écriture sûres. Sert au panneau Fichiers et à l'éditeur de fichiers."""

import os
import subprocess
import tempfile
from collections import namedtuple

MAX_EDIT_BYTES = 2 * 1024 * 1024
ALWAYS_HIDDEN = {".git", "node_modules", "__pycache__"}
GIT_TIMEOUT = 10
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico"}

Stamp = namedtuple("Stamp", "mtime_ns size")


def _git(root, args, stdin=None):
    try:
        r = subprocess.run(["git", "-C", str(root), *args], input=stdin,
                           capture_output=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def git_marks(root):
    """{chemin relatif: "M"|"A"|"?"|"D"} d'après `git status --porcelain=v1 -z`.
    Vide hors d'un dépôt git ou si git est absent ou trop lent."""
    out = _git(root, ["--no-optional-locks", "status", "--porcelain=v1", "-z", "--untracked-files=all"])
    if not out:
        return {}
    marks = {}
    parts = out.decode("utf-8", "replace").split("\0")
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        if "R" in xy or "C" in xy:
            i += 1  # l'ancien nom suit
        if xy == "??":
            mark = "?"
        elif "D" in xy:
            mark = "D"
        elif "A" in xy:
            mark = "A"
        else:
            mark = "M"
        marks[path] = mark
    return marks


def ignored(root, relpaths):
    """Sous-ensemble de `relpaths` ignoré par git (`git check-ignore`)."""
    relpaths = list(relpaths)
    if not relpaths:
        return set()
    data = "\0".join(relpaths).encode("utf-8", "surrogateescape") + b"\0"
    out = _git(root, ["check-ignore", "--stdin", "-z"], stdin=data)
    if not out:
        return set()
    return {p for p in out.decode("utf-8", "surrogateescape").split("\0") if p}


def kind(path):
    """"text", "image", "binary", "missing" ou "too_big"."""
    try:
        if not os.path.isfile(path):
            return "missing"
        size = os.path.getsize(path)
    except OSError:
        return "missing"
    if os.path.splitext(str(path))[1].lower() in IMAGE_EXTS:
        return "image"
    try:
        with open(path, "rb") as f:
            head = f.read(8192)
    except OSError:
        return "missing"
    if b"\0" in head:
        return "binary"
    if size > MAX_EDIT_BYTES:
        return "too_big"
    return "text"


def read_text(path):
    """(texte, encodage) : UTF-8, sinon latin-1 (le drapeau est l'encodage rendu)."""
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


def stamp(path):
    st = os.stat(path)
    return Stamp(st.st_mtime_ns, st.st_size)


def changed(path, old):
    """Vrai si le fichier a changé (ou disparu) depuis `old`."""
    try:
        return stamp(path) != old
    except OSError:
        return True


def save(path, text, encoding="utf-8"):
    """Écriture atomique (fichier temporaire puis renommage), droits conservés."""
    real = os.path.realpath(os.fspath(path))
    try:
        mode = os.stat(real).st_mode & 0o7777
    except OSError:
        mode = 0o644
    data = text.encode(encoding, "replace")
    fd, tmp = tempfile.mkstemp(prefix=".ccs-", dir=os.path.dirname(real))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, real)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return stamp(real)
