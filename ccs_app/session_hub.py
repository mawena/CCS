"""Onglet Sessions de l'application (pur, sans GTK) : les projets à gauche, à droite les
sessions ouvertes puis les conversations du projet choisi (ou de tous), avec une
recherche et un filtre d'origine communs.

- `build(convs, found, …)` → `View` : entrées de la liste des projets (« Tous les
  projets » en tête), entrée choisie, sessions ouvertes et conversations à afficher.
- Tri des projets : ceux qui ont une session ouverte d'abord, puis par dernière activité
  (dernière écriture d'une conversation, dernier changement d'état d'une session).
- Recherche (titre, demandes, projet, dossier ; sans accents ni casse) et origine
  (« vscode », « terminal ») s'appliquent aux conversations, aux sessions ouvertes et à
  la liste des projets (projets sans résultat retirés, sauf le projet choisi).
- `project_for_ref(réf, sessions, conversations)` : projet à choisir pour afficher la
  session désignée par une notification (« <pid>:<identifiant> »).
"""

from dataclasses import dataclass

from . import attention, conversations, project_accounts, sessions

ALL = None                       # entrée « Tous les projets »
ALL_LABEL = "Tous les projets"
UNKNOWN_LABEL = "Dossier inconnu"


@dataclass(frozen=True)
class ProjectEntry:
    cwd: str | None          # None : « Tous les projets » ; "" : dossier inconnu
    name: str                # nom affiché (chemin court si deux projets portent le même nom)
    conversations: int       # conversations affichées (recherche et origine appliquées)
    total: int               # toutes les conversations du projet
    open: int                # sessions ouvertes affichées
    waiting: int             # dont en attente d'une réponse
    last: float              # dernière activité (0 si inconnue)
    exists: bool = True      # dossier présent sur le disque
    moved_to: str | None = None   # dossier probable d'un projet déplacé
    profile: str | None = None    # compte associé (au dossier ou à un dossier parent)

    @property
    def activity(self):
        """« attention » (une session attend une réponse), « ouverte », ou None."""
        if self.waiting:
            return "attention"
        return "ouverte" if self.open else None


@dataclass
class View:
    entries: list            # ProjectEntry, « Tous les projets » en tête
    selected: ProjectEntry   # entrée choisie (« Tous » si le projet demandé a disparu)
    sessions: list           # sessions ouvertes affichées
    conversations: list      # conversations affichées, de la plus récente à la plus ancienne
    total: int               # conversations de l'entrée choisie, sans recherche ni origine
    filtering: bool          # recherche ou filtre d'origine actif
    projects: int = 0        # nombre de projets, sans recherche ni origine (dossier inconnu exclu)


def plural(n, word):
    return f"{n} {word}{'s' if n > 1 else ''}"


def session_origin(s):
    """« vscode », « terminal » ou « autre », comme l'origine d'une conversation."""
    entrypoint = s.entrypoint or ""
    if "vscode" in entrypoint:
        return "vscode"
    return "terminal" if entrypoint in ("", "cli") else "autre"


def filter_conversations(convs, query="", origin=None, project=ALL):
    """Conversations qui correspondent à la recherche, à l'origine et au projet (`""` :
    dossier inconnu)."""
    found = conversations.search(convs, query, project or None, origin)
    return [c for c in found if not c.cwd] if project == "" else found


def filter_sessions(found, query="", origin=None, project=ALL, titles=None):
    """Sessions ouvertes qui correspondent : chaque mot dans le titre de la conversation,
    le nom de la session, le projet ou le dossier."""
    words = conversations.fold(query).split()
    titles = titles or {}
    out = []
    for s in found:
        if project is not ALL and s.cwd != project:
            continue
        if origin and session_origin(s) != origin:
            continue
        hay = conversations.fold(" ".join((titles.get(s.session_id) or "", s.name or "", s.project or "",
                                           s.cwd or "")))
        if all(w in hay for w in words):
            out.append(s)
    return out


def _labels(cwds, home):
    """Nom affiché de chaque projet : nom du dossier, ou chemin court s'il est ambigu."""
    by_name = {}
    for cwd in cwds:
        name = sessions.project_name(cwd) if cwd else UNKNOWN_LABEL
        by_name.setdefault(name, []).append(cwd)
    labels = {}
    for name, group in by_name.items():
        for cwd in group:
            labels[cwd] = project_accounts.short_path(cwd, home) if len(group) > 1 and cwd else name
    return labels


def build(convs, found, selected=ALL, query="", origin=None, titles=None, suggestions=None,
          associations=(), home=None):
    """Tout ce que l'onglet affiche, d'après l'historique (`convs`, de conversations.scan),
    les sessions ouvertes (`found`) et le projet choisi (dossier, ou ALL)."""
    suggestions = suggestions or {}
    filtering = bool(query.strip()) or bool(origin)
    shown_convs = filter_conversations(convs, query, origin)
    shown_sessions = filter_sessions(found, query, origin, titles=titles)

    stats = {}   # dossier -> [conversations affichées, total, ouvertes, en attente, dernière activité]
    exists, moved = {}, {}
    for c in convs:
        st = stats.setdefault(c.cwd, [0, 0, 0, 0, 0.0])
        st[1] += 1
        st[4] = max(st[4], c.updated_at or 0.0)
        exists[c.cwd] = exists.get(c.cwd, False) or c.folder_exists
        if not c.folder_exists and suggestions.get(c.session_id):
            moved.setdefault(c.cwd, suggestions[c.session_id])
    for c in shown_convs:
        stats[c.cwd][0] += 1
    for s in found:
        st = stats.setdefault(s.cwd, [0, 0, 0, 0, 0.0])
        st[4] = max(st[4], s.state_since or s.started_at or 0.0)
        exists[s.cwd] = exists.get(s.cwd, False) or bool(s.cwd)   # une session tourne dans un dossier présent
    for s in shown_sessions:
        stats[s.cwd][2] += 1
        stats[s.cwd][3] += s.state == "waiting"

    if selected is not ALL and selected not in stats:
        selected = ALL   # projet disparu (plus de conversation ni de session)
    labels = _labels(list(stats), home)
    entries = []
    for cwd, (shown, total, opened, waiting, last) in stats.items():
        if filtering and not (shown or opened) and cwd != selected:
            continue
        a = project_accounts.resolve(cwd, associations) if cwd else None
        entries.append(ProjectEntry(cwd=cwd, name=labels[cwd], conversations=shown, total=total, open=opened,
                                    waiting=waiting, last=last, exists=exists.get(cwd, True),
                                    moved_to=moved.get(cwd), profile=a.profile if a else None))
    entries.sort(key=lambda e: (e.open == 0, -e.last, e.name))
    everything = ProjectEntry(cwd=ALL, name=ALL_LABEL, conversations=len(shown_convs), total=len(convs),
                              open=len(shown_sessions),
                              waiting=sum(1 for s in shown_sessions if s.state == "waiting"),
                              last=max((e.last for e in entries), default=0.0))
    entries.insert(0, everything)
    chosen = next((e for e in entries if e.cwd == selected), everything)
    projects = sum(1 for cwd in stats if cwd)
    if chosen.cwd is ALL:
        return View(entries, chosen, shown_sessions, shown_convs, len(convs), filtering, projects)
    return View(entries, chosen, [s for s in shown_sessions if s.cwd == chosen.cwd],
                [c for c in shown_convs if c.cwd == chosen.cwd], chosen.total, filtering, projects)


def project_for_ref(ref, found, convs):
    """Dossier du projet de la session `ref` (« <pid>:<identifiant> », pid ou identifiant
    seuls) : celui de la session ouverte, sinon celui de sa conversation ; None si rien
    ne correspond ou si la référence est illisible."""
    pid, session_id = attention.parse_session_ref(ref)
    if pid is None and session_id is None:
        return None
    s = attention.match_session(found, pid, session_id)
    if s is not None:
        return s.cwd
    if session_id:
        c = next((c for c in convs if c.session_id == session_id), None)
        if c is not None:
            return c.cwd
    return None


def entry_detail(entry):
    """(texte, erreur) de la seconde ligne d'une entrée de la liste des projets."""
    if entry.cwd is ALL:
        if not entry.open:
            return "", False
        if entry.waiting:   # plus court : la colonne est étroite
            return (plural(entry.open, "session") + f" · {entry.waiting} "
                    + ("attendent ta réponse" if entry.waiting > 1 else "attend ta réponse")), False
        return plural(entry.open, "session") + (" ouvertes" if entry.open > 1 else " ouverte"), False
    if entry.cwd == "":
        return "dossier inconnu", True
    if not entry.exists:
        return "dossier introuvable" + (" · déplacé ?" if entry.moved_to else ""), True
    parts = []
    if entry.waiting:
        parts.append(f"{entry.waiting} attendent ta réponse" if entry.waiting > 1 else "attend ta réponse")
    elif entry.open:
        parts.append(plural(entry.open, "session") + (" ouvertes" if entry.open > 1 else " ouverte"))
    if entry.profile:
        parts.append(f"compte {entry.profile}")
    return " · ".join(parts), False


def count_text(shown, total):
    """« 12 conversations », ou « 3 conversations sur 340 » quand un filtre en cache."""
    text = plural(shown, "conversation")
    return text if shown == total else f"{text} sur {total}"


def entries_signature(entries):
    """Ce qui change l'affichage de la liste des projets (pas de re-rendu sinon)."""
    return tuple((e.cwd, e.name, e.conversations, e.open, e.waiting, e.exists, e.moved_to is not None,
                  e.profile) for e in entries)
