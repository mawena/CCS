"""Options d'un chat Claude Code : modèle, effort, ultracode, droits. Sans GTK.

Le modèle et les droits passent en direct (`set_model`, `set_permission_mode`) ; l'effort et
ultracode passent par la commande locale `/effort` : la CLI n'annonce jamais l'effort, il vient
donc toujours de `ChatOptions`.
"""

import re
from dataclasses import dataclass, replace

from . import launch_options

MODELS = launch_options.MODELS   # (libellé, alias) ; None : réglage de Claude Code

EFFORTS = ("low", "medium", "high", "xhigh", "max")
EFFORT_LABELS = {"low": "Faible", "medium": "Moyen", "high": "Élevé", "xhigh": "Très élevé", "max": "Max"}

# (libellé, valeur de --permission-mode / set_permission_mode)
RIGHTS = (
    ("Demander", "manual"),
    ("Modifications acceptées", "acceptEdits"),
    ("Plan", "plan"),
    ("Tout autoriser", "bypassPermissions"),
)
RIGHT_VALUES = tuple(v for _label, v in RIGHTS)

# Les modèles 4.6 n'ont pas le niveau « xhigh » (ni donc ultracode).
_NO_XHIGH = re.compile(r"(?:opus|sonnet)[-.]4[-.]6", re.I)


@dataclass(frozen=True)
class ChatOptions:
    model: str | None = None
    effort: str | None = None
    ultracode: bool = False
    rights: str = "manual"
    provider: str | None = None   # autre fournisseur que Claude (providers.py) ; None : Claude

    def __post_init__(self):
        from . import providers
        object.__setattr__(self, "provider", None if providers.is_claude(self.provider)
                           else str(self.provider).strip().casefold())
        # Mot des droits (« lecture », « modifications », « tout », celui de `ccs task`) :
        # converti en mode de Claude Code ; un mode reste tel quel.
        if isinstance(self.rights, str) and self.rights.strip().casefold() in launch_options.RIGHTS_WORDS:
            object.__setattr__(self, "rights", launch_options.convert_rights(self.rights, "mode"))


def efforts_for(model, resolved=None):
    """Niveaux d'effort offerts par ce modèle. `resolved` : nom complet derrière un alias
    (le `resolvedModel` de `initialize`), pour reconnaître les alias qui mènent à un 4.6."""
    for name in (model, resolved):
        if name and _NO_XHIGH.search(str(name)):
            return tuple(e for e in EFFORTS if e != "xhigh")
    return EFFORTS


def ultracode_possible(model, resolved=None):
    return "xhigh" in efforts_for(model, resolved)


def launch_args(options):
    """Arguments de `claude` propres aux options (modèle, effort, droits)."""
    from . import providers
    args = []
    if options.provider:
        args += providers.claude_args(options.provider, options.model)
    elif options.model:
        args += ["--model", options.model]
    if options.provider:
        pass   # l'effort (réflexion) est propre aux modèles Claude
    elif options.ultracode:
        args += ["--effort", "ultracode"]
    elif options.effort:
        args += ["--effort", options.effort]
    args += ["--permission-mode", options.rights or "manual"]
    return args


def merge_hello(hello):
    """Modèles à proposer : ceux qu'annonce `initialize` remplacent la table `MODELS`.

    Renvoie des (libellé, valeur) comme `MODELS`. La valeur « default » devient « Par défaut »
    sans option ; si la CLI n'annonce rien, la table reste celle de `launch_options`.
    """
    models = []
    for value, label, _description, _efforts in getattr(hello, "models", ()) or ():
        if value == "default":
            models.append((MODELS[0][0], None))
        else:
            models.append((label or value, value))
    return tuple(models) if models else MODELS


def from_args(extra_args):
    """ChatOptions tirées des arguments d'une session (`--model`, `--permission-mode`,
    `--effort`, en deux mots ou avec `=`). Le reste est ignoré."""
    from . import providers
    values = {}
    args = [a for a in (extra_args or ()) if isinstance(a, str)]
    provider, _model = providers.from_args(args)
    i = 0
    while i < len(args):
        name, sep, inline = args[i].partition("=")
        if name in ("--model", "--permission-mode", "--effort"):
            if sep:
                values[name] = inline
            elif i + 1 < len(args):
                values[name] = args[i + 1]
                i += 1
        i += 1
    try:
        model = launch_options._model(values.get("--model"))
    except ValueError:
        model = None
    rights = values.get("--permission-mode")
    rights = "manual" if rights in (None, "", "default") else rights
    if rights not in RIGHT_VALUES and rights not in launch_options.PERMISSION_MODE_VALUES:
        rights = "manual"
    effort = values.get("--effort")
    ultracode = effort == "ultracode"
    return ChatOptions(model=model, effort=effort if effort in EFFORTS else None,
                       ultracode=ultracode, rights=rights, provider=provider)


def default_rights(settings):
    """Droits par défaut des nouveaux chats (`chat.rights`) ; « manual » si absent ou inconnu."""
    try:
        value = settings.get("chat", {}).get("rights", "manual")
    except AttributeError:
        return "manual"
    if isinstance(value, str) and value.strip().casefold() in launch_options.RIGHTS_WORDS:
        value = launch_options.convert_rights(value, "mode")
    return value if value in RIGHT_VALUES else "manual"


def new_session_form(settings):
    """Champs de « Nouvelle session », communs au bureau et au web (source unique des listes).

    Ordre d'affichage : dossier, compte, fournisseur, modèle, effort, droits (les dossiers,
    comptes et fournisseurs viennent d'ailleurs : sessions, project_accounts, providers).
    Valeurs en [valeur, libellé] ; « » : réglage de Claude Code. L'effort ne vaut que pour
    les modèles Claude ; les droits par défaut sont ceux des réglages (`chat.rights`)."""
    return {
        "models": [[v or "", label] for label, v in MODELS],
        "efforts": [["", "Par défaut"]] + [[e, EFFORT_LABELS[e]] for e in EFFORTS],
        "rights": [[v, label] for label, v in RIGHTS],
        "default_rights": default_rights(settings),
        "dangerous": sorted(launch_options.DANGEROUS_MODES),
    }


def with_default_rights(options, extra_args, settings):
    """`options` complétées des droits par défaut, sauf si `extra_args` fixe `--permission-mode`."""
    args = [a for a in (extra_args or ()) if isinstance(a, str)]
    if any(a == "--permission-mode" or a.startswith("--permission-mode=") for a in args):
        return options
    return replace(options, rights=default_rights(settings))
