"""Historique des conversations Claude Code du PC (lecture seule de ~/.claude/projects).

Chaque conversation est un fichier `<projet>/<session>.jsonl` auquel Claude Code
ajoute des lignes. L'index garde, pour chaque fichier, la position déjà lue : une
relecture ne parcourt que les octets ajoutés depuis. Les sous-agents
(`<session>/subagents/*.jsonl`) ne sont pas des conversations et sont ignorés.

Titre affiché, comme dans l'extension VS Code : titre donné par l'utilisateur
(`custom-title`), sinon dernier titre automatique (`ai-title`), sinon première
demande.
"""

import glob
import json
import os
import shlex
import shutil
import subprocess
import threading
import time
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from . import core, costs, sessions

CACHE_VERSION = 1
TITLE_MAX = 80
PROMPT_MAX = 300
VSCODE_DELAY_S = 1.5
ORIGINS = {"claude-vscode": "vscode", "cli": "terminal"}
ORIGIN_LABELS = {"vscode": "VS Code", "terminal": "terminal", "autre": "autre"}
DAY_GROUPS = ("Aujourd'hui", "Hier", "7 derniers jours", "30 derniers jours", "Plus ancien")


@dataclass
class Conversation:
    session_id: str
    path: str
    cwd: str
    title: str
    first_prompt: str
    last_prompt: str
    prompts: int            # demandes tapées par l'utilisateur
    started_at: float | None
    updated_at: float       # dernière écriture du fichier
    origin: str             # "vscode" | "terminal" | "autre"
    git_branch: str
    size: int
    folder_exists: bool = field(default=True)
    archived: bool = field(default=False)   # l'original a disparu : copie dans l'archive de CCS

    @property
    def project(self):
        return sessions.project_name(self.cwd)

    @property
    def origin_label(self):
        return ORIGIN_LABELS.get(self.origin, self.origin)


# ---- lecture incrémentale ------------------------------------------------------------

def cache_path():
    return core.paths().store / "conversations-cache.json"


def moves_path():
    """Journaux copiés par relocate() : {chemin du journal copié: nouveau dossier}."""
    return core.paths().store / "conversations-moves.json"


def _new_entry():
    return {"size": 0, "mtime": 0.0, "offset": 0, "cwd": None, "custom_title": None,
            "ai_title": None, "first_prompt": None, "last_prompt": None, "prompts": 0,
            "started_at": None, "entrypoint": None, "git_branch": None}


def _ts(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def prompt_text(d):
    """Texte tapé par l'utilisateur dans une ligne `user`, ou None (réponse d'outil,
    message injecté par Claude Code, contexte de l'IDE…)."""
    if d.get("type") != "user" or d.get("isMeta") or d.get("isSidechain"):
        return None
    content = (d.get("message") or {}).get("content")
    texts = [content] if isinstance(content, str) else [
        c.get("text") for c in content or [] if isinstance(c, dict) and c.get("type") == "text"]
    for text in texts:
        if not isinstance(text, str):
            continue
        text = text.strip()
        # VS Code place le contexte (<ide_opened_file>…) avant la demande elle-même.
        if text and not text.startswith("<") and not text.startswith(sessions.INJECTED_PREFIXES):
            return text
    return None


def _one_line(text, limit):
    line = " ".join(text.split())
    return line[:limit - 1] + "…" if len(line) > limit else line


def _apply(entry, raw):
    """Met à jour l'entrée avec une ligne du journal (octets). Seules les lignes utiles
    sont décodées : les longues réponses et sorties d'outils sont écartées sans parse."""
    maybe_title = b'"custom-title"' in raw or b'"ai-title"' in raw
    maybe_prompt = ((b'"type":"user"' in raw or b'"type": "user"' in raw)
                    and b'"tool_result"' not in raw)
    wants_cwd = entry["cwd"] is None and b'"cwd"' in raw and len(raw) < 50_000
    if not (maybe_title or maybe_prompt or wants_cwd):
        return
    try:
        d = json.loads(raw)
    except ValueError:
        return
    if not isinstance(d, dict):
        return
    kind = d.get("type")
    if kind == "custom-title":
        entry["custom_title"] = str(d.get("customTitle") or "") or entry["custom_title"]
        return
    if kind == "ai-title":
        entry["ai_title"] = str(d.get("aiTitle") or "") or entry["ai_title"]
        return
    text = prompt_text(d) if kind == "user" else None
    if text is not None:
        entry["prompts"] += 1
        if entry["first_prompt"] is None:
            entry["first_prompt"] = _one_line(text, PROMPT_MAX)
        entry["last_prompt"] = _one_line(text, PROMPT_MAX)
        entry["git_branch"] = d.get("gitBranch") or entry["git_branch"]
    if d.get("cwd"):
        entry["cwd"] = entry["cwd"] or d["cwd"]
        entry["entrypoint"] = entry["entrypoint"] or d.get("entrypoint")
        entry["started_at"] = entry["started_at"] or _ts(d.get("timestamp"))


def read_entry(path, entry=None):
    """Lit le fichier à partir de la position mémorisée ; repart de zéro s'il a rétréci."""
    st = path.stat()
    entry = dict(entry) if entry else _new_entry()
    if st.st_size < entry["offset"]:
        entry = _new_entry()
    offset = entry["offset"]
    with open(path, "rb") as fh:
        fh.seek(offset)
        for raw in fh:
            if not raw.endswith(b"\n"):
                break  # ligne en cours d'écriture : relue la fois suivante
            offset += len(raw)
            if raw.strip():
                _apply(entry, raw)
    entry["offset"] = offset
    entry["size"], entry["mtime"] = st.st_size, st.st_mtime
    return entry


def _load_cache():
    data = core.load_json(cache_path())
    if data.get("version") != CACHE_VERSION:
        return {}
    return data.get("files") or {}


def _to_conversation(path, e, cwd=None):
    title = e["custom_title"] or e["ai_title"] or _one_line(e["first_prompt"] or "(sans titre)", TITLE_MAX)
    cwd = cwd or e["cwd"] or ""
    return Conversation(
        session_id=path.stem, path=str(path), cwd=cwd, title=title,
        first_prompt=e["first_prompt"] or "", last_prompt=e["last_prompt"] or "",
        prompts=e["prompts"], started_at=e["started_at"], updated_at=e["mtime"],
        origin=ORIGINS.get(e["entrypoint"] or "", "autre"), git_branch=e["git_branch"] or "",
        size=e["size"], folder_exists=bool(cwd) and os.path.isdir(cwd))


def _from_archive(item):
    """Conversation d'un élément de l'archive (le chemin est celui où elle sera remise)."""
    from . import archive
    cwd = item.get("cwd") or ""
    return Conversation(
        session_id=item["id"], path=str(archive.journal_path(item)), cwd=cwd,
        title=item.get("title") or "(sans titre)", first_prompt=item.get("first_prompt") or "",
        last_prompt=item.get("last_prompt") or "", prompts=item.get("prompts") or 0,
        started_at=item.get("started_at"), updated_at=item.get("updated_at") or 0.0,
        origin=item.get("origin") or "autre", git_branch=item.get("git_branch") or "",
        size=item.get("size") or 0, folder_exists=bool(cwd) and os.path.isdir(cwd), archived=True)


def archived_only(live):
    """Conversations archivées dont l'original a disparu (aucun journal vivant de même
    identifiant dans `live`, un ensemble d'identifiants)."""
    from . import archive
    best = {}
    for item in archive.items():
        sid = item.get("id")
        if sid in live or sid in best or not item.get("prompts"):
            continue
        best[sid] = item   # items() : la plus récente d'abord
    out = []
    for item in best.values():
        if not Path(archive.journal_path(item)).is_file():
            out.append(_from_archive(item))
    return out


def from_journal(path, cwd=None):
    """Conversation d'un seul journal (aperçu depuis l'onglet Sessions). L'index de scan()
    sert s'il est à jour ; sinon seule la fin non lue est parcourue. `cwd` : dossier à
    prendre si le journal n'en dit rien. Un journal disparu mais archivé donne une
    conversation `archived`."""
    path = Path(path)
    if not path.is_file():
        from . import archive
        item = archive.item_for_path(path)
        if item is not None:
            return _from_archive(item)
    entry = _load_cache().get(str(path))
    st = path.stat()
    if not entry or entry.get("size") != st.st_size or entry.get("mtime") != st.st_mtime:
        entry = read_entry(path, entry)
    return _to_conversation(path, entry, None if entry.get("cwd") else cwd)


def scan(archived=True):
    """Toutes les conversations (au moins une demande), de la plus récente à la plus
    ancienne. Met à jour le cache ; un fichier illisible est simplement ignoré.
    `archived` : ajoute celles dont l'original a disparu mais que l'archive garde
    (`archived=True` sur l'objet)."""
    root = sessions.projects_dir()
    cache = _load_cache()
    moves = core.load_json(moves_path())
    files, out = {}, []
    for path in root.glob("*/*.jsonl") if root.is_dir() else ():
        key = str(path)
        try:
            st = path.stat()
            entry = cache.get(key)
            if not entry or entry.get("size") != st.st_size or entry.get("mtime") != st.st_mtime:
                entry = read_entry(path, entry)
        except (OSError, KeyError, TypeError):
            continue
        files[key] = entry
        if entry["prompts"]:
            out.append(_to_conversation(path, entry, moves.get(key)))
    if files != cache:
        try:
            core.atomic_write_json(cache_path(), {"version": CACHE_VERSION, "files": files})
        except OSError:
            pass  # cache facultatif
    # Une conversation copiée par relocate() existe en double : on garde l'exemplaire dont le
    # dossier existe, puis le plus récent ; à égalité (copie intacte), l'exemplaire relié,
    # quel que soit l'ordre de lecture des fichiers. Une conversation qui a continué dans
    # l'ancien dossier après la copie reste plus récente, et l'emporte.
    best = {}
    for c in out:
        cur = best.get(c.session_id)
        rank = (c.folder_exists, c.updated_at, c.path in moves)
        if cur is None or rank > (cur.folder_exists, cur.updated_at, cur.path in moves):
            best[c.session_id] = c
    if archived:
        try:
            for c in archived_only(set(best) | {Path(k).stem for k in files}):
                best[c.session_id] = c
        except (OSError, ValueError, KeyError, TypeError):
            pass  # archive illisible : l'historique vivant reste affiché
    return sorted(best.values(), key=lambda c: c.updated_at, reverse=True)


# ---- recherche, regroupement ----------------------------------------------------------

def fold(text):
    """Texte sans accents ni casse, pour comparer une recherche."""
    text = unicodedata.normalize("NFKD", text or "").casefold()
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def search(convs, query="", project=None, origin=None):
    """Chaque mot de la recherche doit apparaître (sans tenir compte des accents ni de
    la casse) dans le titre, la première ou la dernière demande, le projet, le dossier
    ou la branche."""
    words = fold(query).split()
    out = []
    for c in convs:
        if project and c.cwd != project:
            continue
        if origin and c.origin != origin:
            continue
        if not words:   # rien à chercher : inutile de préparer le texte (relu souvent par l'application)
            out.append(c)
            continue
        hay = fold(" ".join((c.title, c.first_prompt, c.last_prompt, c.project, c.cwd, c.git_branch,
                             "archivee" if c.archived else "")))
        if all(w in hay for w in words):
            out.append(c)
    return out


def projects(convs):
    """[(dossier, nombre)] des projets présents dans l'historique, du plus récent au plus ancien."""
    counts, order = {}, []
    for c in convs:
        if c.cwd not in counts:
            order.append(c.cwd)
            counts[c.cwd] = 0
        counts[c.cwd] += 1
    return [(cwd, counts[cwd]) for cwd in order]


def day_group(ts, now=None):
    now = datetime.fromtimestamp(now if now is not None else time.time())
    day = datetime.fromtimestamp(ts).date()
    today = now.date()
    if day >= today:
        return DAY_GROUPS[0]
    if day == today - timedelta(days=1):
        return DAY_GROUPS[1]
    if day > today - timedelta(days=7):
        return DAY_GROUPS[2]
    if day > today - timedelta(days=30):
        return DAY_GROUPS[3]
    return DAY_GROUPS[4]


def group_by_day(convs, now=None):
    """[(libellé, [conversations])] dans l'ordre de DAY_GROUPS, groupes vides omis."""
    groups = {}
    for c in convs:
        groups.setdefault(day_group(c.updated_at, now), []).append(c)
    return [(g, groups[g]) for g in DAY_GROUPS if g in groups]


def find(convs, ref):
    """Conversation dont l'identifiant vaut `ref` ou commence par `ref` (4 caractères au moins)."""
    ref = (ref or "").strip()
    exact = [c for c in convs if c.session_id == ref]
    if exact:
        return exact[0]
    if len(ref) < 4:
        raise LookupError("donne au moins 4 caractères de l'identifiant")
    found = [c for c in convs if c.session_id.startswith(ref)]
    if not found:
        raise LookupError(f"aucune conversation ne commence par « {ref} »")
    if len(found) > 1:
        raise LookupError(f"« {ref} » désigne {len(found)} conversations : précise l'identifiant")
    return found[0]


# ---- reprise -------------------------------------------------------------------------

def ensure_available(session_id, cwd=None):
    """Chemin du journal de la conversation, remise en place depuis l'archive si son
    original a disparu (date de modification « maintenant »). À appeler avant toute
    reprise. FileNotFoundError si elle n'existe ni sur le disque ni dans l'archive."""
    try:
        return journal_of(session_id, cwd)
    except FileNotFoundError:
        pass
    from . import archive
    return archive.restore(session_id, cwd)


def ensure_conversation(conv):
    """`conv` prête à être reprise : si elle est archivée, elle est restaurée (l'objet
    rendu n'est plus `archived`) ; sinon renvoyée telle quelle."""
    if not conv.archived:
        return conv
    return replace(conv, path=str(ensure_available(conv.session_id, conv.cwd)), archived=False)


def cost_for_path(path):
    """Coût d'un journal, lu dans l'archive s'il a disparu (calculé une fois, copie
    temporaire supprimée aussitôt)."""
    path = Path(path)
    if path.is_file():
        return costs.conversation_cost(path)
    from . import archive
    item = archive.item_for_path(path)
    if item is None:
        return costs.conversation_cost(path)
    key = (item["slug"], item["id"], item.get("archived_at"))
    hit = _ARCHIVE_COSTS.get(key)
    if hit is None:
        with archive.extracted(item) as tmp:
            hit = _ARCHIVE_COSTS[key] = costs.conversation_cost(tmp)
        while len(_ARCHIVE_COSTS) > 500:
            _ARCHIVE_COSTS.pop(next(iter(_ARCHIVE_COSTS)))
    return hit


_ARCHIVE_COSTS = {}


def open_ids():
    """Identifiants des conversations ouvertes en ce moment dans une session Claude Code."""
    return {s.session_id for s in sessions.list_sessions() if s.session_id}


def resume_problem(conv, opened=None):
    """Raison d'empêcher la reprise, ou None."""
    if not conv.folder_exists:
        return f"dossier introuvable : {conv.cwd or '?'}"
    if opened is not None and conv.session_id in opened:
        return "déjà ouverte dans une session Claude Code"
    return None


def resume_command(conv):
    return f"cd {shlex.quote(conv.cwd)} && claude --resume {shlex.quote(conv.session_id)}"


SEARCH_DEPTH = 4
SEARCH_SKIP = {"node_modules", "vendor", "__pycache__", "build", "dist", "target", "venv", "snap"}


def _dirs_named(names, depth=SEARCH_DEPTH):
    """{nom: [chemins]} des dossiers du HOME portant l'un de ces noms (dossiers cachés et
    dossiers de dépendances ignorés, profondeur limitée : quelques dizaines de ms)."""
    hits = {}

    def walk(d, level):
        try:
            entries = os.scandir(d)
        except OSError:
            return
        with entries:
            for e in entries:
                if e.name.startswith(".") or e.name in SEARCH_SKIP or not e.is_dir(follow_symlinks=False):
                    continue
                if e.name in names:
                    hits.setdefault(e.name, []).append(e.path)
                if level < depth:
                    walk(e.path, level + 1)

    if names:
        walk(core.paths().home, 1)
    return hits


def suggest_folders(convs):
    """{identifiant: dossier} pour les conversations dont le dossier a disparu (projet
    déplacé) : l'unique dossier existant du même nom, pris d'abord dans l'historique,
    sinon dans le HOME. Une supposition : la reprise depuis ce dossier se confirme."""
    missing = [c for c in convs if not c.folder_exists and c.cwd]
    if not missing:
        return {}
    known = {}
    for c in convs:
        if c.folder_exists and c.cwd:
            known.setdefault(Path(c.cwd).name, set()).add(c.cwd)
    names = {Path(c.cwd).name for c in missing}
    on_disk = _dirs_named({n for n in names if n not in known})
    out = {}
    for c in missing:
        name = Path(c.cwd).name
        found = known.get(name) or set(on_disk.get(name, ())) - {c.cwd}
        if len(found) == 1:
            out[c.session_id] = next(iter(found))
    return out


def suggest_folder(conv, convs):
    """Dossier probable d'une conversation dont le dossier a disparu, ou None."""
    if conv.folder_exists:
        return None
    others = [c for c in convs if c.session_id != conv.session_id]
    return suggest_folders(others + [conv]).get(conv.session_id)


def relocate(conv, new_cwd):
    """Rend la conversation reprenable depuis `new_cwd` : Claude Code cherche le journal
    dans le dossier de projet du répertoire courant, on l'y copie (l'original reste en
    place, une copie déjà présente n'est jamais écrasée). Renvoie la conversation vue
    depuis ce dossier."""
    new_cwd = os.path.abspath(os.path.expanduser(new_cwd))
    if not os.path.isdir(new_cwd):
        raise FileNotFoundError(f"dossier introuvable : {new_cwd}")
    conv = ensure_conversation(conv)
    dest = sessions.projects_dir() / sessions.project_slug(new_cwd) / f"{conv.session_id}.jsonl"
    if Path(conv.path) != dest and not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".jsonl.ccs-tmp")
        shutil.copy2(conv.path, tmp)
        os.replace(tmp, dest)
    moves = core.load_json(moves_path())
    if moves.get(str(dest)) != new_cwd:
        moves[str(dest)] = new_cwd
        core.atomic_write_json(moves_path(), moves)
    return replace(conv, cwd=new_cwd, path=str(dest), folder_exists=True)


# ---- renommage -------------------------------------------------------------------------

RENAME_MAX = 200


def clean_title(title):
    """Titre sur une ligne ; ValueError s'il est vide ou trop long."""
    title = " ".join((title or "").split())
    if not title:
        raise ValueError("le titre ne peut pas être vide")
    if len(title) > RENAME_MAX:
        raise ValueError(f"titre trop long ({RENAME_MAX} caractères au plus)")
    return title


def journal_of(session_id, cwd=None, path=None):
    """Journal d'une conversation : `path` s'il est donné, sinon celui du dossier de projet
    de `cwd`, sinon le plus récent des projets qui contiennent cet identifiant."""
    if path:
        found = Path(path)
    else:
        found = sessions.transcript_path(cwd, session_id) if cwd else None
        if found is None or not found.is_file():
            root = sessions.projects_dir()
            copies = sorted(root.glob(f"*/{glob.escape(session_id)}.jsonl") if root.is_dir() else (),
                            key=lambda p: p.stat().st_mtime, reverse=True)
            found = copies[0] if copies else None
    if found is None or not found.is_file():
        raise FileNotFoundError(f"journal introuvable pour la conversation {session_id}")
    return found


def rename(session_id, title, cwd=None, path=None):
    """Renomme une conversation comme `/rename` dans Claude Code : une ligne `custom-title`
    ajoutée à la fin du journal (le dernier titre l'emporte). Renvoie le titre retenu.

    Le journal n'est jamais réécrit : la ligne part en un seul write() en mode ajout
    (O_APPEND), qui ne peut pas s'entremêler avec les lignes qu'une session ouverte écrit
    au même moment. Une session ouverte relit la fin du journal avant de réécrire ses
    métadonnées et garde donc ce titre."""
    title = clean_title(title)
    journal = journal_of(session_id, cwd, path)
    data = json.dumps({"type": "custom-title", "sessionId": session_id, "customTitle": title},
                      ensure_ascii=False, separators=(",", ":")) + "\n"
    fd = os.open(journal, os.O_WRONLY | os.O_APPEND | os.O_CLOEXEC)
    try:
        size = os.fstat(fd).st_size
        if size:
            with open(journal, "rb") as fh:  # dernière ligne coupée : on la referme d'abord
                fh.seek(size - 1)
                if fh.read(1) != b"\n":
                    data = "\n" + data
        raw = data.encode()
        if os.write(fd, raw) != len(raw):
            raise OSError(f"écriture incomplète du titre dans {journal}")
    finally:
        os.close(fd)
    return title


def vscode_bin():
    return shutil.which("code")


def vscode_url(conv):
    return f"vscode://anthropic.claude-code/open?session={quote(conv.session_id, safe='')}"


def resume_terminal(conv):
    ensure_conversation(conv)
    sessions.open_terminal(conv.cwd, resume=conv.session_id)


def resume_vscode(conv, wait=False):
    """Ouvre (ou met au premier plan) la fenêtre VS Code du dossier, puis demande à
    l'extension Claude Code d'y rouvrir la conversation."""
    code = vscode_bin()
    if not code:
        raise FileNotFoundError("VS Code (commande « code ») introuvable")
    ensure_conversation(conv)
    quiet = {"start_new_session": True, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}

    def run():
        subprocess.run([code, conv.cwd], check=False, timeout=30, **quiet)
        time.sleep(VSCODE_DELAY_S)  # la fenêtre du dossier doit recevoir le lien
        subprocess.run([code, "--open-url", vscode_url(conv)], check=False, timeout=30, **quiet)

    if wait:
        run()
    else:
        threading.Thread(target=run, daemon=True).start()


def preferred_target(conv):
    """« vscode » pour une conversation née dans VS Code (si VS Code est installé), sinon « terminal »."""
    return "vscode" if conv.origin == "vscode" and vscode_bin() else "terminal"


def ago(ts, now=None):
    seconds = max(0, (now if now is not None else time.time()) - ts)
    if seconds < 60:
        return "à l'instant"
    if seconds < 3600:
        return f"il y a {int(seconds // 60)} min"
    if seconds < 86400:
        return f"il y a {int(seconds // 3600)} h"
    days = int(seconds // 86400)
    return "hier" if days == 1 else f"il y a {days} j"
