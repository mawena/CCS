"""Terminal intégré à l'application : ce qui se calcule sans GTK.

Commande et environnement de lancement (Claude Code, reprise d'une conversation,
shell), choix entre terminal intégré et terminal externe, état des onglets et
textes affichés. L'interface (`gui/terminals.py`) ne fait qu'appliquer ces
décisions avec VTE.
"""

import os
import pwd
import shlex
import shutil
from dataclasses import dataclass

from . import core, sessions

VTE_PACKAGE = "gir1.2-vte-3.91"
VTE_HINT = (f"Terminal intégré indisponible : les sessions s'ouvrent dans un terminal externe. "
            f"Pour les ouvrir dans l'application : sudo apt install {VTE_PACKAGE}")
TERM_ENV = {"TERM": "xterm-256color", "COLORTERM": "truecolor"}
# Variables qu'une session Claude Code pose dans ses processus. Une application lancée
# depuis une session (ou depuis un terminal de VS Code) les hérite : un claude démarré
# avec elles se croirait imbriqué dans une autre session ou relié à un autre éditeur.
SESSION_VARS = ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT",
                "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ATTENDED",
                "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN")
INDICATORS = {  # état de la session -> (sablier, icône, infobulle)
    "busy": (True, None, "travaille"),
    "waiting": (False, "dialog-question-symbolic", "attend ta réponse"),
    "idle": (False, None, "au repos"),
}
STOPPED = (False, "media-playback-stop-symbolic", "arrêtée")


@dataclass(frozen=True)
class Launch:
    """Ce qu'un onglet lance : `argv` dans `cwd`, avec `env` ajouté à l'environnement."""
    kind: str                     # "claude" | "shell"
    cwd: str
    argv: tuple
    env: dict
    title: str
    session_id: str | None = None

    def envv(self):
        """Environnement au format attendu par VTE (« NOM=valeur »)."""
        return [f"{k}={v}" for k, v in sorted(self.env.items())]


@dataclass
class TabState:
    """État d'un onglet du terminal intégré."""
    kind: str                     # "claude" | "shell"
    cwd: str
    title: str
    session_id: str | None = None
    pid: int | None = None
    running: bool = False
    state: str | None = None      # "busy" | "waiting" | "idle" (fiche de session de claude)
    busy: bool = False            # shell : un programme tourne au premier plan
    exit_status: int | None = None


# ---- lancement ------------------------------------------------------------------------

def _tool(name, fallback):
    return shutil.which(name) or fallback


def _unset_prefix(environ):
    """`env -u …` pour retirer les variables de session héritées (VTE ajoute des variables
    à l'environnement mais ne sait pas en retirer)."""
    found = [v for v in SESSION_VARS if v in environ]
    if not found:
        return []
    out = [_tool("env", "/usr/bin/env")]
    for name in found:
        out += ["-u", name]
    return out


def _env(environ):
    local_bin = f"{core.paths().home}/.local/bin"
    path = environ.get("PATH") or "/usr/local/bin:/usr/bin:/bin"
    if local_bin not in path.split(":"):
        path = f"{local_bin}:{path}"   # application lancée du bureau : PATH minimal
    return {**TERM_ENV, "PATH": path}


def claude_launch(cwd, resume=None, title=None, environ=None):
    """Claude Code dans `cwd` (`--resume <id>` pour reprendre une conversation).

    Comme pour le terminal externe, claude passe par un bash de connexion (profil de
    l'utilisateur) qui s'efface devant lui (`exec`) : le processus de l'onglet est claude
    lui-même, retrouvé ensuite dans les fiches de session par son pid."""
    environ = os.environ if environ is None else environ
    claude = [sessions._claude_bin()] + (["--resume", resume] if resume else [])
    argv = _unset_prefix(environ) + [_tool("bash", "/bin/bash"), "-lc", "exec " + shlex.join(claude)]
    return Launch("claude", cwd, tuple(argv), _env(environ), title or sessions.project_name(cwd), resume)


def _user_shell(environ):
    shell = environ.get("SHELL")
    if shell:
        return shell
    try:
        return pwd.getpwuid(os.getuid()).pw_shell or "/bin/bash"
    except KeyError:
        return "/bin/bash"


def shell_launch(cwd, environ=None):
    """Shell de l'utilisateur dans `cwd`, comme un nouvel onglet de terminal."""
    environ = os.environ if environ is None else environ
    argv = _unset_prefix(environ) + [_user_shell(environ)]
    return Launch("shell", cwd, tuple(argv), _env(environ), f"Terminal · {sessions.project_name(cwd)}")


def relaunch(tab, environ=None):
    """Lancement qui reprend un onglet arrêté : la même conversation si son identifiant
    est connu, sinon une nouvelle session ; le shell pour un onglet de shell."""
    if tab.kind == "shell":
        return shell_launch(tab.cwd, environ)
    return claude_launch(tab.cwd, tab.session_id, tab.title, environ)


def relaunch_label(tab):
    return "Reprendre" if tab.kind == "claude" and tab.session_id else "Relancer"


def embedded_disabled(environ=None):
    """CCS_NO_VTE=1 : toujours le terminal externe (essais du repli sans VTE)."""
    environ = os.environ if environ is None else environ
    return bool(environ.get("CCS_NO_VTE"))


def choose(vte_ready, external=False):
    """« integre » si le terminal intégré est disponible et pas écarté, sinon « externe »."""
    return "integre" if vte_ready and not external else "externe"


# ---- état des onglets -------------------------------------------------------------------

def exit_text(kind, status):
    """Texte du bandeau de fin ; `status` est le statut d'attente (waitpid) de VTE."""
    who, verb = ("Claude Code", "s'est arrêté") if kind == "claude" else ("Le terminal", "s'est fermé")
    try:
        code = os.waitstatus_to_exitcode(status)
    except ValueError:
        code = 0
    if code > 0:
        return f"{who} {verb} (code {code})."
    if code < 0:
        return f"{who} {verb} (signal {-code})."
    return f"{who} {verb}."


def find_tab(tabs, pid=None, session_id=None):
    """Onglet du processus `pid` ou de la conversation `session_id`, ou None."""
    for tab in tabs:
        if pid is not None and tab.pid == pid:
            return tab
        if session_id and tab.kind == "claude" and tab.session_id == session_id:
            return tab
    return None


def sync_tabs(tabs, live):
    """Met à jour les onglets de claude d'après les fiches de session (`live`, trouvées par
    pid) : identifiant de la conversation (connu après le démarrage, changé par /resume)
    et état. Renvoie les onglets qui viennent de finir de travailler."""
    by_pid = {s.pid: s for s in live}
    done = []
    for tab in tabs:
        s = by_pid.get(tab.pid) if tab.kind == "claude" and tab.running else None
        if s is None:
            continue
        if s.session_id:
            tab.session_id = s.session_id
        if tab.state == "busy" and s.state != "busy":
            done.append(tab)
        tab.state = s.state
    return done


def indicator(tab):
    """(sablier, icône, infobulle) de l'onglet."""
    if not tab.running:
        return STOPPED
    return INDICATORS.get(tab.state, (False, None, None))


def needs_confirm(tab):
    """Fermer cet onglet arrêterait claude ou un programme lancé dans le shell."""
    return tab.running and (tab.kind == "claude" or tab.busy)


def running_claude(tabs):
    return sum(1 for t in tabs if t.kind == "claude" and t.running)


def _saved(n):
    return ("La conversation est enregistrée : tu pourras la reprendre." if n == 1 else
            "Les conversations sont enregistrées : tu pourras les reprendre.")


def close_question(tabs):
    """(titre, texte) de la confirmation avant de fermer la fenêtre, ou None."""
    n = running_claude(tabs)
    shells = any(t.kind == "shell" and needs_confirm(t) for t in tabs)
    if not n and not shells:
        return None
    parts = []
    if n:
        parts.append("Une session Claude Code tourne encore dans l'application." if n == 1 else
                     f"{n} sessions Claude Code tournent encore dans l'application.")
        parts.append(_saved(n))
    if shells:
        parts.append("Un programme tourne encore dans un terminal de l'application : il sera arrêté.")
    return "Fermer la fenêtre ?", " ".join(parts)


def tab_close_question(tab):
    """(titre, texte) de la confirmation avant de fermer un onglet, ou None."""
    if not needs_confirm(tab):
        return None
    body = (f"Claude Code sera arrêté. {_saved(1)}" if tab.kind == "claude"
            else "Le programme en cours sera arrêté.")
    return f"Fermer « {tab.title} » ?", body
