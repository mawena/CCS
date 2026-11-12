"""Projets de Charles : ceux où il a ouvert une session Claude et qui ont un `ROADMAP.md`.

La liste vient des conversations (`conversations.scan()`), l'historique (versions, cases
cochées par jour) de git. Rien n'est jamais écrit dans les dépôts. Hors git, ou sans
`git`, la carte d'un projet reste complète, sans versions ni historique.
"""

import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import core, roadmap

GIT_TIMEOUT_S = 10
CACHE_NAME = "projects-cache.json"
CACHE_VERSION = 1
CHECKED_RE = re.compile(r"^\+[ \t]*[-*+][ \t]+\[[xX]\][ \t]+(.*?)[ \t]*$")
UNCHECKED_RE = re.compile(r"^-[ \t]*[-*+][ \t]+\[ \][ \t]+(.*?)[ \t]*$")
CHANGELOG_RE = re.compile(r"^##[ \t]*\[(\d[^\]]*)\]", re.M)
NUMBER_RE = re.compile(r"\d+")
COMMIT_MARK = "@@@"


@dataclass
class Project:
    path: Path
    name: str
    roadmap_path: Path
    version: str | None
    last_activity: float          # horodatage : la plus récente des conversations et du dernier commit
    current_phase: roadmap.Phase | None
    done: int                     # cases cochées de toute la feuille de route
    total: int


@dataclass
class History:
    versions: list                # [(tag, date)], du plus ancien au plus récent
    checks_per_day: dict          # {date: nombre de cases passées de [ ] à [x]}
    phase_done: dict              # {titre de phase finie: date de sa dernière case cochée}


def _git(cwd, args):
    """Sortie de `git <args>` dans `cwd`, ou None (git absent, délai dépassé, code ≠ 0)."""
    try:
        res = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                             errors="replace", timeout=GIT_TIMEOUT_S, stdin=subprocess.DEVNULL,
                             env=_git_env())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return res.stdout if res.returncode == 0 else None


def _git_env():
    env = dict(os.environ)
    env.update(GIT_OPTIONAL_LOCKS="0", LC_ALL="C", GIT_TERMINAL_PROMPT="0")
    return env


def _head(path):
    out = _git(path, ["rev-parse", "HEAD"])
    return out.strip() if out and out.strip() else None


def _current_phase(rm):
    """Phase non finie au plus grand numéro (« Phase 12 »), à défaut la dernière du fichier :
    les phases ne sont pas dans l'ordre du fichier."""
    best, best_key = None, None
    for index, phase in enumerate(rm.phases):
        if phase.finished:
            continue
        numbers = NUMBER_RE.findall(phase.title.split("(")[0])
        key = (int(numbers[0]) if numbers else -1, index)
        if best_key is None or key > best_key:
            best, best_key = phase, key
    return best


def _version(path):
    out = _git(path, ["describe", "--tags", "--abbrev=0"])
    tag = out.strip() if out else ""
    if tag:
        return tag[1:] if tag[:1] in "vV" and tag[1:2].isdigit() else tag
    try:
        text = (Path(path) / "CHANGELOG.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = CHANGELOG_RE.search(text)
    return m.group(1).strip() if m else None


def _last_commit(path):
    out = _git(path, ["log", "-1", "--format=%ct"])
    try:
        return float(out.strip()) if out else 0.0
    except ValueError:
        return 0.0


def list_projects(convs, hidden=()):
    """Un projet par `ROADMAP.md` trouvé (`roadmap.find`) depuis le dossier d'une conversation
    de `convs` (objets avec `cwd` et `updated_at`), sauf ceux de `hidden` (chemins du dossier de
    la session ou du projet). Triés par dernière activité, la plus récente d'abord."""
    hide = {str(h).rstrip("/") for h in hidden}
    seen, latest = {}, {}
    for c in convs:
        cwd = getattr(c, "cwd", "")
        if not cwd or str(cwd).rstrip("/") in hide:
            continue
        key = str(cwd)
        if key not in seen:
            seen[key] = roadmap.find(cwd)
        rp = seen[key]
        if rp is not None and str(rp.parent) not in hide:
            latest[rp] = max(latest.get(rp, 0.0), float(getattr(c, "updated_at", 0) or 0))
    out = []
    for rp, activity in latest.items():
        try:
            rm = roadmap.parse(rp.read_text(encoding="utf-8", errors="replace"), rp)
        except OSError:
            continue
        folder = rp.parent
        out.append(Project(
            path=folder, name=folder.name or str(folder), roadmap_path=rp,
            version=_version(folder),
            last_activity=max(activity, _last_commit(folder)),
            current_phase=_current_phase(rm),
            done=sum(p.done_count for p in rm.phases),
            total=sum(p.total for p in rm.phases)))
    out.sort(key=lambda p: p.last_activity, reverse=True)
    return out


# --------------------------------------------------------------------------
# Historique
# --------------------------------------------------------------------------

def _versions(path):
    out = _git(path, ["for-each-ref", "--sort=creatordate",
                      "--format=%(refname:short)|%(creatordate:format:%Y-%m-%d)", "refs/tags/v*"])
    versions = []
    for line in (out or "").splitlines():
        tag, _, day = line.partition("|")
        try:
            versions.append((tag, date.fromisoformat(day)))
        except ValueError:
            continue
    return versions


def _checks(path):
    """[(date, texte)] des cases passées de [ ] à [x] dans l'historique de ROADMAP.md : dans
    chaque commit, une ligne cochée ajoutée compte si la même ligne décochée est retirée."""
    out = _git(path, ["log", "-p", "--no-color", "--no-ext-diff", "--no-renames",
                      f"--format={COMMIT_MARK}%ad", "--date=format:%Y-%m-%d", "--",
                      roadmap.FILENAME])
    events, day, removed, added = [], None, Counter(), []

    def flush():
        for text in added:
            if removed[text] > 0:
                removed[text] -= 1
                events.append((day, text))

    for line in (out or "").splitlines():
        if line.startswith(COMMIT_MARK):
            if day is not None:
                flush()
            try:
                day = date.fromisoformat(line[len(COMMIT_MARK):].strip())
            except ValueError:
                day = None
            removed, added = Counter(), []
            continue
        if day is None:
            continue
        m = UNCHECKED_RE.match(line)
        if m:
            removed[m.group(1)] += 1
            continue
        m = CHECKED_RE.match(line)
        if m:
            added.append(m.group(1))
    if day is not None:
        flush()
    return events


def _phase_done(path, events):
    text = _git(path, ["show", f"HEAD:{roadmap.FILENAME}"])
    if not text:
        return {}
    rm = roadmap.parse(text)
    done = {}
    for phase in rm.phases:
        if not phase.finished:
            continue
        texts = {t.text for t in phase.tasks}
        days = [d for d, t in events if t in texts]
        if days:
            done[phase.title] = max(days)
    return done


def _compute(path):
    events = _checks(path)
    per_day = Counter(d for d, _ in events)
    return History(_versions(path), dict(sorted(per_day.items())), _phase_done(path, events))


def _to_json(h):
    return {"versions": [[t, d.isoformat()] for t, d in h.versions],
            "checks_per_day": {d.isoformat(): n for d, n in h.checks_per_day.items()},
            "phase_done": {t: d.isoformat() for t, d in h.phase_done.items()}}


def _from_json(data):
    return History([(t, date.fromisoformat(d)) for t, d in data["versions"]],
                   {date.fromisoformat(d): int(n) for d, n in data["checks_per_day"].items()},
                   {t: date.fromisoformat(d) for t, d in data["phase_done"].items()})


def history(path):
    """Versions (tags `v*`), cases cochées par jour et date de fin des phases finies, tirées de
    git. Mis en cache dans `projects-cache.json` par (dossier, `git rev-parse HEAD`). Hors git
    ou sans `git` : `History([], {}, {})`."""
    empty = History([], {}, {})
    path = Path(path)
    if not path.is_dir():
        return empty
    head = _head(path)
    if head is None:
        return empty
    cache_path = core.paths().store / CACHE_NAME
    cache = core.load_json(cache_path)
    entries = cache.get("entries") if cache.get("version") == CACHE_VERSION else None
    if not isinstance(entries, dict):
        entries = {}
    entry = entries.get(str(path))
    if isinstance(entry, dict) and entry.get("head") == head:
        try:
            return _from_json(entry["data"])
        except (KeyError, TypeError, ValueError, AttributeError):
            pass
    result = _compute(path)
    entries[str(path)] = {"head": head, "data": _to_json(result)}
    try:
        core.atomic_write_json(cache_path, {"version": CACHE_VERSION, "entries": entries})
    except OSError:
        pass
    return result
