"""Feuille de route d'un projet : lecture de `ROADMAP.md` et case cochée au clic.

Format (celui des projets de Charles) : un titre `#`, des phases en titres `##`
(« Phase 12 — Titre (0.10.0) ✅ »), des tâches `- [ ]` / `- [x]` éventuellement
imbriquées, du texte libre entre les deux. Les phases ne sont pas forcément dans
l'ordre du fichier. Un titre `##` sans case n'est pas une phase ; une case hors
phase, ou dans un bloc de code, est ignorée.

Les numéros de ligne (`Task.line`, `Phase.line`) commencent à 1.
"""

import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

FILENAME = "ROADMAP.md"
TASK_RE = re.compile(r"^(?P<indent>[ \t]*)[-*+][ \t]+\[(?P<box>[ xX])\][ \t]+(?P<text>.*?)[ \t]*$")
PHASE_RE = re.compile(r"^##(?!#)[ \t]*(?P<title>.*?)[ \t]*#*[ \t]*$")
TITLE_RE = re.compile(r"^#(?!#)[ \t]*(?P<title>.*?)[ \t]*$")
FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")
PARENS_RE = re.compile(r"\(([^()]*)\)")
TAB_WIDTH = 4


@dataclass
class Task:
    text: str
    done: bool
    line: int
    depth: int


@dataclass
class Phase:
    title: str
    version: str | None
    tasks: list = field(default_factory=list)
    line: int = 0

    @property
    def done_count(self):
        return sum(1 for t in self.tasks if t.done)

    @property
    def total(self):
        return len(self.tasks)

    @property
    def finished(self):
        return self.total > 0 and self.done_count == self.total


@dataclass
class Roadmap:
    title: str
    phases: list
    path: Path | None = None


def _version(title):
    """Contenu de la dernière paire de parenthèses du titre qui contient un chiffre."""
    found = [m.strip() for m in PARENS_RE.findall(title) if any(c.isdigit() for c in m)]
    return found[-1] if found else None


def _indent_width(indent):
    return len(indent.expandtabs(TAB_WIDTH))


def _lines(text):
    """Lignes sans leur fin ; seul `\\n` sépare (un `\\r` final est retiré)."""
    return [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]


def parse(text, path=None):
    title = ""
    phases = []
    current = None          # (Phase) en cours, ou None hors phase
    stack = []              # indentations des tâches ouvertes, pour la profondeur
    fenced = False
    for number, line in enumerate(_lines(text), start=1):
        if FENCE_RE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = TASK_RE.match(line)
        if m:
            if current is None:
                continue
            width = _indent_width(m.group("indent"))
            while stack and stack[-1] >= width:
                stack.pop()
            current.tasks.append(Task(m.group("text"), m.group("box") != " ", number, len(stack)))
            stack.append(width)
            continue
        m = PHASE_RE.match(line)
        if m:
            current = Phase(m.group("title"), _version(m.group("title")), [], number)
            phases.append(current)
            stack = []
            continue
        m = TITLE_RE.match(line)
        if m:
            if not title:
                title = m.group("title")
            current = None
            stack = []
    return Roadmap(title, [p for p in phases if p.tasks], Path(path) if path else None)


def find(cwd):
    """`ROADMAP.md` dans `cwd`, puis en remontant jusqu'à la racine du dépôt git (incluse,
    jamais au-delà). Hors dépôt git, seul `cwd` est regardé."""
    try:
        start = Path(cwd).resolve()
    except (OSError, RuntimeError, TypeError):
        return None
    if not start.is_dir():
        return None
    chain = [start, *start.parents]
    root = next((d for d in chain if (d / ".git").exists()), None)
    for d in chain:
        candidate = d / FILENAME
        if candidate.is_file():
            return candidate
        if d == root or root is None:
            break
    return None


FILE_TOOLS = ("Read", "Write", "Edit", "MultiEdit")
_DIRECT_RE = re.compile(r"((?:~/|/)[^\s'\"`;|&()<>]*ROADMAP\.md)\b")
_CD_RE = re.compile(r"\bcd\s+([\"']?)([^\s\"';&|()]+)\1")


def _expand(path, cwd):
    p = Path(os.path.expanduser(path))
    return p if p.is_absolute() else Path(cwd) / p


def path_in_tool(name, data, cwd):
    """Le `ROADMAP.md` qu'une action de Claude lit ou modifie (outils de fichiers, ou commande
    shell qui le cite, éventuellement après un `cd`), s'il existe ; sinon None. Sert au panneau
    pour suivre le projet de la conversation même lancée depuis ~ ou le Bureau."""
    data = data if isinstance(data, dict) else {}
    found = None
    if name in FILE_TOOLS:
        fp = data.get("file_path")
        if isinstance(fp, str) and Path(fp).name == FILENAME:
            found = _expand(fp, cwd)
    elif name == "Bash":
        cmd = data.get("command")
        if isinstance(cmd, str) and FILENAME in cmd:
            direct = _DIRECT_RE.search(cmd)
            if direct:
                found = _expand(direct.group(1), cwd)
            else:
                cd = _CD_RE.search(cmd)
                if cd:
                    found = _expand(cd.group(2), cwd) / FILENAME
    if found is None:
        return None
    try:
        return found if found.is_file() else None
    except OSError:
        return None


def is_project(path):
    """Vrai si `path` est dans un dépôt git : un vrai projet (pas ~ ni le Bureau)."""
    try:
        start = Path(path).resolve()
    except (OSError, RuntimeError, TypeError):
        return False
    return any((d / ".git").exists() for d in (start, *start.parents))


def toggle(path, line, expected_text):
    """Coche ou décoche la case de la ligne `line` (à partir de 1) si c'est bien une case de
    texte `expected_text` dans le fichier tel qu'il est maintenant. Ne change que le
    caractère entre crochets. Renvoie False si la ligne ne correspond plus."""
    try:
        target = Path(path).resolve()
        raw = target.read_bytes()
    except OSError:
        return False
    text = raw.decode("utf-8", errors="surrogateescape")
    task = next((t for p in parse(text).phases for t in p.tasks if t.line == line), None)
    if task is None or task.text != expected_text:
        return False
    lines = text.split("\n")
    old = lines[line - 1]
    pos = TASK_RE.match(old.rstrip("\r")).start("box")
    lines[line - 1] = old[:pos] + (" " if task.done else "x") + old[pos + 1:]
    data = "\n".join(lines).encode("utf-8", errors="surrogateescape")
    try:
        fd, tmp = tempfile.mkstemp(prefix=target.name + ".", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.chmod(tmp, target.stat().st_mode & 0o7777)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        return False
    return True


def _keyed(rm):
    """(titre de phase, texte, rang parmi les homonymes de la phase) -> tâche."""
    out = {}
    for phase in rm.phases:
        seen = {}
        for task in phase.tasks:
            rank = seen.get(task.text, 0)
            seen[task.text] = rank + 1
            out[(phase.title, task.text, rank)] = task
    return out


def newly_done(before, after):
    """Tâches décochées dans `before` et cochées dans `after`, dans l'ordre du fichier."""
    old = _keyed(before)
    return [task for key, task in _keyed(after).items()
            if task.done and key in old and not old[key].done]
