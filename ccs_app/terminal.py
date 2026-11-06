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
import time
from dataclasses import dataclass, field

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
# Reprise automatique après une limite : texte envoyé et garde anti-boucle.
RESUME_TEXT = "continue"
RESUME_MAX_PER_HOUR = 3
RESUME_MIN_GAP_S = 120
RESUME_MAX_AGE_S = 15 * 60


@dataclass(frozen=True)
class Launch:
    """Ce qu'un onglet lance : `argv` dans `cwd`, avec `env` ajouté à l'environnement."""
    kind: str                     # "claude" | "shell"
    cwd: str
    argv: tuple
    env: dict
    title: str
    session_id: str | None = None
    extra_args: tuple = ()        # claude : arguments ajoutés (--model, --permission-mode…)

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
    extra_args: tuple = ()            # claude : arguments du lancement, repris à la relance
    waiting_for: str | None = None    # motif d'attente de la fiche de session
    started_at: float | None = None   # lancement du processus de l'onglet
    busy_since: float | None = None   # début du dernier tour de travail de claude
    typed_at: float | None = None     # dernière saisie au clavier (ou collage) dans l'onglet
    sent_at: float | None = None      # dernier texte envoyé par l'application (reprise, file)
    resumes: list = field(default_factory=list)  # dates des reprises automatiques


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


def claude_launch(cwd, resume=None, title=None, environ=None, extra_args=()):
    """Claude Code dans `cwd` (`--resume <id>` pour reprendre une conversation), avec
    `extra_args` ajoutés après (ex. `--model opus --permission-mode plan`).

    Comme pour le terminal externe, claude passe par un bash de connexion (profil de
    l'utilisateur) qui s'efface devant lui (`exec`) : le processus de l'onglet est claude
    lui-même, retrouvé ensuite dans les fiches de session par son pid."""
    environ = os.environ if environ is None else environ
    extra_args = tuple(str(a) for a in extra_args or ())
    claude = [sessions._claude_bin()] + (["--resume", resume] if resume else []) + list(extra_args)
    argv = _unset_prefix(environ) + [_tool("bash", "/bin/bash"), "-lc", "exec " + shlex.join(claude)]
    return Launch("claude", cwd, tuple(argv), _env(environ), title or sessions.project_name(cwd), resume,
                  extra_args)


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
    est connu, sinon une nouvelle session, avec les mêmes arguments ; le shell pour un
    onglet de shell."""
    if tab.kind == "shell":
        return shell_launch(tab.cwd, environ)
    return claude_launch(tab.cwd, tab.session_id, tab.title, environ, tab.extra_args)


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


def sync_tabs(tabs, live, now=None):
    """Met à jour les onglets de claude d'après les fiches de session (`live`, trouvées par
    pid) : identifiant de la conversation (connu après le démarrage, changé par /resume),
    état, motif d'attente et début du dernier tour de travail (date de la fiche, sinon
    première fois qu'on le voit). Renvoie les onglets qui viennent de finir de travailler."""
    now = time.time() if now is None else now
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
        if s.state == "busy" and (s.state_since or tab.state != "busy" or tab.busy_since is None):
            tab.busy_since = s.state_since or now
        tab.state = s.state
        tab.waiting_for = s.waiting_for
    return done


def free_for_input(tab):
    """Claude attend une nouvelle demande : au repos, ou en attente d'une saisie libre.
    Jamais pendant une demande de permission (Entrée y validerait un choix)."""
    if tab.state == "idle":
        return True
    return tab.state == "waiting" and (tab.waiting_for or "").lower().startswith("input")


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


# ---- reprise automatique après une limite ----------------------------------------------

@dataclass(frozen=True)
class ResumeDecision:
    """« resume » : envoyer RESUME_TEXT puis Entrée ; « drop » : consommer le marqueur sans
    rien envoyer ; « wait » : le garder pour le prochain passage. `text` : bandeau à afficher."""
    action: str
    text: str | None = None


def _limit_head(event):
    return f"Limite atteinte sur {event.source}" if event.source else "Limite atteinte"


def _limit_text(event, tail):
    return f"{_limit_head(event)} : bascule sur {event.target or 'un autre compte'}. {tail}"


def resume_decision(tab, event, now, enabled=True, max_per_hour=RESUME_MAX_PER_HOUR,
                    min_gap=RESUME_MIN_GAP_S, max_age=RESUME_MAX_AGE_S):
    """Que faire du marqueur de limite `event` (limit_events.LimitEvent) pour l'onglet `tab` ?

    None si le marqueur ne concerne pas cet onglet. On ne relance que si le compte a changé,
    que claude attend une nouvelle demande, que personne n'a écrit dans l'onglet depuis la
    limite, et au plus `max_per_hour` fois par heure (espacées d'au moins `min_gap` s)."""
    if event is None or tab.kind != "claude" or not tab.session_id or event.session_id != tab.session_id:
        return None
    if not tab.running or now - event.ts > max_age:
        return ResumeDecision("drop")
    if tab.started_at is not None and event.ts < tab.started_at:
        return ResumeDecision("drop")  # limite d'un processus précédent de la conversation
    if event.outcome == "pending":
        return ResumeDecision("wait")  # le hook choisit encore le compte
    if not event.switched:
        why = (f"bascule vers {event.target} impossible" if event.target
               else "aucun autre compte disponible")
        return ResumeDecision("drop", f"{_limit_head(event)} : {why}, pas de reprise automatique.")
    manual = "tape « continue » pour reprendre."
    if not enabled:
        return ResumeDecision("drop", _limit_text(event, manual.capitalize()))
    if tab.typed_at is not None and tab.typed_at > event.ts:
        return ResumeDecision("drop", _limit_text(
            event, "Pas de reprise automatique : tu as écrit dans la session."))
    if not free_for_input(tab):
        return ResumeDecision("wait")
    recent = [t for t in tab.resumes if now - t < 3600]
    if len(recent) >= max_per_hour:
        return ResumeDecision("drop", _limit_text(
            event, f"Reprise automatique suspendue ({len(recent)} reprises en une heure) : {manual}"))
    if recent and now - max(recent) < min_gap:
        return ResumeDecision("drop", _limit_text(
            event, f"Reprise automatique suspendue (la précédente date de moins de "
                   f"{min_gap // 60} min) : {manual}"))
    return ResumeDecision("resume", f"{_limit_head(event)} : bascule sur "
                                    f"{event.target or 'un autre compte'}, conversation relancée.")
