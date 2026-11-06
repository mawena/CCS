"""Options d'une nouvelle session Claude Code : modèle, mode de permissions, dossier, compte.

Les options viennent de `claude --help` (Claude Code 2.1.319) :
  --model <model>            alias du dernier modèle (« fable », « opus », « sonnet »…)
                             ou nom complet d'un modèle ;
  --permission-mode <mode>   acceptEdits, auto, bypassPermissions, manual, dontAsk, plan ;
  -r, --resume <id>          reprise d'une conversation.

Rien ici ne bascule de compte : `LaunchSpec.profile` dit seulement quel compte
l'utilisateur a choisi. L'appelant bascule (« ccs use <profil> ») s'il le faut,
puis ouvre la session.
"""

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass

# (libellé, valeur de --model) ; None : pas d'option, Claude Code garde son réglage.
MODELS = (
    ("Par défaut", None),
    ("Opus", "opus"),
    ("Sonnet", "sonnet"),
    ("Haiku", "haiku"),
    ("Fable", "fable"),
)

# (libellé, valeur de --permission-mode) ; None : pas d'option (réglage de Claude Code).
PERMISSION_MODES = (
    ("Par défaut", None),
    ("Manuel", "manual"),
    ("Accepter les modifications", "acceptEdits"),
    ("Plan", "plan"),
    ("Auto", "auto"),
    ("Sans question", "dontAsk"),
    ("Aucune vérification", "bypassPermissions"),
)
PERMISSION_MODE_VALUES = tuple(v for _label, v in PERMISSION_MODES if v)
PERMISSION_HELP = {
    None: "Réglage habituel de Claude Code",
    "manual": "Demande avant chaque action",
    "acceptEdits": "Modifie les fichiers sans demander, demande pour le reste",
    "plan": "Analyse et propose un plan, sans rien modifier",
    "auto": "Claude décide seul des actions sans risque",
    "dontAsk": "Refuse ce qui demanderait une permission",
    "bypassPermissions": "Aucune vérification : dangereux",
}
DANGEROUS_MODES = frozenset({"bypassPermissions"})

DEFAULT_WORDS = {"default", "défaut", "par défaut"}
# Alias ou nom complet (« claude-opus-5-5 », « claude-opus-5-5[1m] ») : jamais une option.
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-\[\]]*$")


def _model(model):
    if model is None:
        return None
    model = str(model).strip()
    if not model or model.casefold() in DEFAULT_WORDS:
        return None
    if not MODEL_RE.match(model):
        raise ValueError(f"modèle invalide : {model!r}")
    return model


def _permission_mode(mode):
    if not mode:
        return None
    if mode not in PERMISSION_MODE_VALUES:
        raise ValueError(f"mode de permissions inconnu : {mode!r} "
                         f"(valeurs : {', '.join(PERMISSION_MODE_VALUES)})")
    return mode


def claude_args(model=None, permission_mode=None, resume=None, extra=()):
    """Arguments de `claude` (sans le nom du programme) pour ces options."""
    args = []
    model = _model(model)
    if model:
        args += ["--model", model]
    mode = _permission_mode(permission_mode)
    if mode:
        args += ["--permission-mode", mode]
    if resume:
        resume = str(resume)
        if resume.startswith("-"):
            raise ValueError(f"identifiant de conversation invalide : {resume!r}")
        args += ["--resume", resume]
    for a in extra or ():
        if not isinstance(a, str):
            raise TypeError(f"argument supplémentaire non textuel : {a!r}")
        args.append(a)
    return args


def model_label(value):
    return next((label for label, v in MODELS if v == value), value or MODELS[0][0])


def permission_label(value):
    return next((label for label, v in PERMISSION_MODES if v == value), value or PERMISSION_MODES[0][0])


def permission_help(value):
    """Explication d'un mode de permissions, en une ligne."""
    return PERMISSION_HELP.get(value or None, "")


def is_dangerous(mode):
    return mode in DANGEROUS_MODES


@dataclass(frozen=True)
class LaunchSpec:
    """Nouvelle session choisie dans le dialogue. `profile` : compte choisi (None :
    garder le compte actif) ; s'il diffère du compte actif, l'appelant bascule avant."""
    cwd: str
    profile: str | None
    model: str | None = None
    permission_mode: str | None = None

    def __post_init__(self):
        if not self.cwd:
            raise ValueError("dossier de la session manquant")
        _model(self.model)
        _permission_mode(self.permission_mode)

    def args(self, resume=None, extra=()):
        return claude_args(self.model, self.permission_mode, resume, extra)

    def needs_switch(self, active_profile):
        """Vrai si la session doit tourner sur un autre compte que le compte actif."""
        return bool(self.profile) and self.profile != active_profile

    def shell_command(self, claude_bin=None, resume=None):
        """Commande à copier : « cd <dossier> && claude <options> »."""
        claude = claude_bin or _claude_bin()
        return f"cd {shlex.quote(self.cwd)} && {shlex.join([claude, *self.args(resume)])}"


def _claude_bin():
    from . import sessions
    return sessions._claude_bin()


def terminal_command(spec, claude_bin=None, resume=None):
    """Argv d'un terminal ouvert dans le dossier, qui lance Claude Code avec les options."""
    term = shutil.which("gnome-terminal") or shutil.which("x-terminal-emulator") or "x-terminal-emulator"
    cmd = shlex.join([claude_bin or _claude_bin(), *spec.args(resume)])
    return [term, f"--working-directory={os.path.expanduser(spec.cwd)}", "--", "bash", "-lc", cmd]


def launch(spec, claude_bin=None, resume=None):
    """Ouvre la session dans un nouveau terminal (à appeler après une éventuelle bascule)."""
    subprocess.Popen(terminal_command(spec, claude_bin, resume), start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def switch_if_needed(spec, active=None, run=None):
    """Bascule sur le compte choisi s'il n'est pas le compte actif (« ccs use <profil> »).
    Renvoie (a basculé, message d'erreur ou None). Lent (ccs, verrou) : hors de l'interface."""
    from . import core
    if active is None:
        active = core.active_profile_name()
    if not spec.needs_switch(active):
        return False, None
    r = (run or core.run_ccs)(["use", spec.profile])
    if r.returncode == 0:
        return True, None
    lines = ANSI_RE.sub("", (r.stderr or "") + (r.stdout or "")).strip().splitlines()
    text = lines[0] if lines else f"échec de la bascule sur « {spec.profile} »"
    return False, text.removeprefix("ccs: ").strip()


def open_session(spec, embedded, open_claude, external=None):
    """Ouvre la session choisie (après l'éventuelle bascule) : onglet du terminal intégré si
    `embedded` (`open_claude(dossier, extra_args=…)`, arguments gardés pour la relance de
    l'onglet), sinon terminal externe (`external(spec)`). Renvoie « integre » ou « externe »."""
    if embedded:
        open_claude(spec.cwd, extra_args=tuple(spec.args()))
        return "integre"
    (external or launch)(spec)
    return "externe"
