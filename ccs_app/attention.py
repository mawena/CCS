"""Ce qui demande l'attention dans la fenêtre (pur, sans GTK) : pause, nouvelle version,
bilan de santé, sessions qui attendent une réponse, et session à afficher quand on
clique sur une notification.

Une session est désignée par une référence texte : « <pid>:<identifiant> », ou le pid
seul, ou l'identifiant de conversation seul. Le pid suit le processus (il ne change pas
après /clear ou /resume) ; l'identifiant retrouve la conversation si le pid est inconnu.
"""

import re

from . import __version__, core, pause, terminal, updates

PID_MAX = 1 << 22                         # /proc/sys/kernel/pid_max ne va pas au-delà
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
SHOW_PREFIX = "show:"                     # clé des actions de notification « afficher la session »


# ---- pause ----------------------------------------------------------------------------

def pause_header(info, now):
    """(libellé, infobulle) de l'en-tête pendant une pause, sinon None.

    `info` : `state["pause"]` ou `PauseState.as_dict()` ({"since", "until", "label"}).
    Le libellé est recalculé depuis l'échéance : celui de state.json date du dernier relevé."""
    if not isinstance(info, dict) or not info:
        return None
    since = core.parse_dt(info.get("since")) if isinstance(info.get("since"), str) else None
    until = info.get("until")
    if until is not None:
        until = core.parse_dt(until) if isinstance(until, str) else None
        if until is None or until <= now:
            return None  # illisible, ou pause échue que le service n'a pas encore levée
    text = pause.label(pause.PauseState(since, until), now)
    label = f"Auto ⏸ {text}" if until is not None else "Auto ⏸ en pause"
    tooltip = (f"Bascule automatique et orchestrateur en pause {text}.\n"
               "Reprendre : clique ici, ou « ccs pause off ».")
    return label, tooltip


# ---- nouvelle version -------------------------------------------------------------------

def _project_url(url, version):
    """Lien vers la page du projet seulement (la version vient du réseau)."""
    if (isinstance(url, str) and url.startswith(updates.PROJECT_URL) and url.isprintable()
            and not any(c.isspace() for c in url)):
        return url
    return f"{updates.PROJECT_URL}releases/tag/v{version}"


def update_banner(update, current=__version__):
    """(titre, lien) du bandeau « nouvelle version » d'après `state["update"]`, sinon None
    (rien de publié, ou version déjà installée depuis le dernier relevé du service)."""
    if not isinstance(update, dict):
        return None
    version = update.get("version")
    if not isinstance(version, str) or not updates.is_newer(version, current):
        return None
    version = version.strip().lstrip("vV")
    return f"CCS {version} est disponible", _project_url(update.get("url"), version)


# ---- bilan de santé ---------------------------------------------------------------------

def doctor_banner(checks):
    """Titre du bandeau quand le bilan contient au moins une erreur (pas un avertissement)."""
    from .doctor import ERREUR  # doctor importe daemon, qui importe ce module
    errors = [c for c in checks or () if c.statut == ERREUR]
    if not errors:
        return None
    if len(errors) == 1:
        return f"Un problème a été détecté : {errors[0].nom}"
    return f"{len(errors)} problèmes ont été détectés"


# ---- sessions ---------------------------------------------------------------------------

def waiting_count(found):
    """Sessions qui attendent une réponse (badge de l'onglet Sessions)."""
    return sum(1 for s in found if s.state == "waiting")


def session_ref(session):
    return f"{session.pid}:{session.session_id}" if session.session_id else str(session.pid)


def _pid(text):
    if not text.isdigit() or len(text) > 8:
        return None
    pid = int(text)
    return pid if 0 < pid <= PID_MAX else None


def parse_session_ref(ref):
    """(pid ou None, identifiant ou None) ; (None, None) si la référence est illisible."""
    if not isinstance(ref, str):
        return None, None
    ref = ref.strip()
    head, sep, tail = ref.partition(":")
    if sep:
        pid = _pid(head)
        if pid is None or not SESSION_ID_RE.match(tail):
            return None, None
        return pid, tail
    if ref.isdigit():
        pid = _pid(ref)
        return (pid, None) if pid else (None, None)
    return (None, ref) if SESSION_ID_RE.match(ref) else (None, None)


def match_session(found, pid, session_id):
    """Session désignée : par pid d'abord, sinon par identifiant de conversation."""
    if pid is not None:
        hit = next((s for s in found if s.pid == pid), None)
        if hit is not None:
            return hit
    if session_id:
        return next((s for s in found if s.session_id == session_id), None)
    return None


def focus_target(ref, tabs):
    """Où afficher la session `ref` : ("onglet", TabState) si elle tourne dans un onglet du
    terminal intégré, sinon ("sessions", pid, identifiant) ; None si `ref` est illisible.

    Avec un pid, seul ce processus compte : un onglet arrêté qui portait la même
    conversation ne la montre pas (elle a été reprise ailleurs)."""
    pid, session_id = parse_session_ref(ref)
    if pid is None and session_id is None:
        return None
    claude_tabs = [t for t in tabs if t.kind == "claude"]
    if pid is not None:
        tab = terminal.find_tab(claude_tabs, pid=pid)
    else:
        tab = terminal.find_tab(claude_tabs, session_id=session_id)
    if tab is not None:
        return "onglet", tab
    return "sessions", pid, session_id
