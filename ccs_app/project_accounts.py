"""Compte par projet : un dossier de projet associé à un compte préféré.

~/.claude-accounts/projects.json (600, écriture atomique sous verrou `.projects.lock`) :
    {"version": 1,
     "projects": {"/home/u/Work/App": {"profile": "pro", "ask": true}}}

- Un sous-dossier hérite du projet le plus proche (`get`).
- `ask` : proposer la bascule en ouvrant une session du projet (False : « Ne plus
  demander pour ce projet »).
- Fichier illisible ou d'un autre format : aucun projet (il est remplacé au prochain
  enregistrement) ; entrée inattendue sautée.

Le compte actif est global (toutes les sessions l'utilisent) : rien ici ne bascule.
L'application propose la bascule (`proposal`), jamais pendant une pause de CCS, et
présélectionne le compte du projet dans « Nouvelle session » (`preferred_profile`).
"""

import fcntl
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass

from . import core

FILE_VERSION = 1
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
NONE_WORDS = ("aucun", "none")
USAGE = "usage : ccs projet [<dossier>] [<compte>|aucun]"


@dataclass(frozen=True)
class Association:
    cwd: str            # dossier du projet (absolu, normalisé)
    profile: str        # compte préféré
    ask: bool = True    # proposer la bascule (False : « Ne plus demander pour ce projet »)


def path():
    return core.paths().store / "projects.json"


def normalize(cwd):
    """Chemin absolu sans « .. », « ~ » développé, sans barre finale (sauf « / »)."""
    return os.path.normpath(os.path.abspath(os.path.expanduser(str(cwd))))


def valid_name(name):
    return isinstance(name, str) and bool(NAME_RE.match(name))


@contextmanager
def _locked():
    lock = core.paths().store / ".projects.lock"
    lock.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(lock, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _read():
    """{dossier: Association} du fichier ({} s'il est absent, illisible ou d'un autre format)."""
    data = core.load_json(path())
    projects = data.get("projects") if data.get("version") == FILE_VERSION else None
    out = {}
    for cwd, entry in (projects or {}).items() if isinstance(projects, dict) else ():
        if not isinstance(cwd, str) or not os.path.isabs(cwd) or not isinstance(entry, dict):
            continue
        profile = entry.get("profile")
        if not valid_name(profile):
            continue
        ask = entry.get("ask", True)
        out[normalize(cwd)] = Association(normalize(cwd), profile, ask if isinstance(ask, bool) else True)
    return out


def _write(projects):
    core.atomic_write_json(path(), {"version": FILE_VERSION, "projects": {
        a.cwd: {"profile": a.profile, "ask": a.ask} for a in sorted(projects.values(), key=lambda a: a.cwd)}})


def all():  # noqa: A001 — nom de l'API demandée (ccs projet)
    """Associations enregistrées, triées par dossier."""
    return sorted(_read().values(), key=lambda a: a.cwd)


def resolve(cwd, associations):
    """Association du dossier ou de son parent le plus proche, parmi `associations`."""
    if not cwd:
        return None
    target = normalize(cwd)
    best = None
    for a in associations:
        if target == a.cwd or a.cwd == "/" or target.startswith(a.cwd + "/"):
            if best is None or len(a.cwd) > len(best.cwd):
                best = a
    return best


def get(cwd):
    """Association qui s'applique à `cwd` (le sien ou celle d'un dossier parent), ou None."""
    return resolve(cwd, _read().values())


def set(cwd, profile):  # noqa: A001 — nom de l'API demandée (ccs projet)
    """Associe le dossier `cwd` au compte `profile` (None : retire l'association du dossier).
    Le même compte garde son réglage « demander » ; un autre compte le remet à True.
    Renvoie l'association enregistrée (None après un retrait). Lève OSError, ValueError."""
    if profile is not None and not valid_name(profile):
        raise ValueError(f"nom de compte invalide : {profile!r}")
    key = normalize(cwd)
    with _locked():
        projects = _read()
        old = projects.get(key)
        if profile is None:
            if old is not None:
                del projects[key]
                _write(projects)
            return None
        new = Association(key, profile, old.ask if old is not None and old.profile == profile else True)
        if new != old:
            projects[key] = new
            _write(projects)
        return new


def set_ask(cwd, ask):
    """Règle « proposer la bascule » de l'association du dossier `cwd` lui-même.
    False s'il n'a pas d'association."""
    key = normalize(cwd)
    with _locked():
        projects = _read()
        old = projects.get(key)
        if old is None:
            return False
        if old.ask != bool(ask):
            projects[key] = Association(key, old.profile, bool(ask))
            _write(projects)
        return True


# --------------------------------------------------------------------------
# Décisions (pures : associations et profils donnés)
# --------------------------------------------------------------------------

def _associations(associations):
    return all() if associations is None else associations


def proposal(cwd, active, profiles, paused=False, associations=None):
    """Association dont il faut proposer le compte en ouvrant une session dans `cwd`, ou
    None : pas de projet, déjà le compte actif, « ne plus demander », compte disparu,
    ou CCS en pause (pas de bascule proposée pendant une pause)."""
    if paused:
        return None
    a = resolve(cwd, _associations(associations))
    if a is None or not a.ask or a.profile == active or a.profile not in profiles:
        return None
    return a


def preferred_profile(cwd, profiles, paused=False, associations=None):
    """Compte à présélectionner dans « Nouvelle session » pour `cwd`, ou None."""
    a = resolve(cwd, _associations(associations))
    if paused or a is None or not a.ask or a.profile not in profiles:
        return None
    return a.profile


def origin_for(cwd, profile, associations=None):
    """« projet » si `profile` est le compte du projet de `cwd` (origine d'une bascule, pour
    le journal), sinon None."""
    a = resolve(cwd, _associations(associations))
    return "projet" if profile and a is not None and a.profile == profile else None


def short_path(cwd, home=None):
    home = str(core.paths().home if home is None else home)
    if cwd == home:
        return "~"
    return "~" + cwd[len(home):] if cwd.startswith(home.rstrip("/") + "/") else cwd


def hint(cwd, profiles, paused=False, associations=None, home=None):
    """Ligne d'information du dialogue « Nouvelle session » (None sans projet associé)."""
    a = resolve(cwd, _associations(associations))
    if a is None:
        return None
    text = f"Compte du projet : {a.profile}"
    if a.cwd != normalize(cwd):
        text += f" (hérité de {short_path(a.cwd, home)})"
    if a.profile not in profiles:
        return text + " — compte introuvable"
    if paused:
        return text + " — CCS en pause, rien n'est présélectionné"
    if not a.ask:
        return text + " — sans proposition de bascule"
    return text


def question(association, active):
    """(titre, texte) de la proposition de bascule avant d'ouvrir une session du projet."""
    now = (f"Le compte actif est « {active} »." if active
           else "Le compte connecté n'est enregistré dans aucun profil.")
    return (f"Ce projet utilise le compte « {association.profile} »",
            f"Basculer ? {now} La bascule s'applique à toutes les sessions ouvertes.")


def card_text(cwd, active, paused=False, associations=None, home=None):
    """Ligne de la carte d'un projet (onglet Sessions), None sans compte associé."""
    a = resolve(cwd, _associations(associations))
    if a is None:
        return None
    text = f"Compte du projet : {a.profile}"
    if a.cwd != normalize(cwd):
        text += f" (hérité de {short_path(a.cwd, home)})"
    if not a.ask:
        return text + " · sans proposition de bascule"
    if a.profile != active:
        return text + (" · pas de bascule proposée pendant la pause" if paused
                       else " · bascule proposée à l'ouverture")
    return text


# --------------------------------------------------------------------------
# Texte et commande « ccs projet »
# --------------------------------------------------------------------------

def format_text(associations=None, home=None):
    """Liste des projets associés (texte de « ccs projet » sans argument)."""
    associations = _associations(associations)
    if not associations:
        return "Aucun projet associé à un compte."
    paths = [short_path(a.cwd, home) for a in associations]
    width = max(len(p) for p in paths)
    return "\n".join(f"{p:<{width}}  → {a.profile}" + ("" if a.ask else " (sans proposition de bascule)")
                     for p, a in zip(paths, associations))


def _show(folder, home):
    a = get(folder)
    where = short_path(folder, home)
    if a is None:
        return f"Aucun compte associé à {where} : le compte actif sera utilisé."
    text = f"{where} → {a.profile}"
    if a.cwd != folder:
        text += f" (hérité de {short_path(a.cwd, home)})"
    return text + ("" if a.ask else " (sans proposition de bascule)")


def _path_like(arg):
    return arg in (".", "..") or "/" in arg or arg.startswith("~")


def command(args, cwd=None, profiles=None, home=None):
    """(code de sortie, texte) de « ccs projet [<dossier>] [<compte>|aucun] ».

    Sans argument : liste. Un argument : un dossier (chemin, ou dossier existant qui ne
    porte pas le nom d'un compte) est affiché ; un compte ou « aucun » s'applique au
    dossier courant. Deux arguments : dossier puis compte (ou « aucun »)."""
    args = list(args or [])
    if profiles is None:
        profiles = [p.name for p in core.list_profiles()]
    base = cwd or os.getcwd()

    def folder_of(arg):
        return normalize(os.path.join(base, os.path.expanduser(arg)))
    if not args:
        return 0, format_text(home=home)
    if len(args) > 2:
        return 2, USAGE
    if len(args) == 1:
        arg = args[0]
        if not _path_like(arg) and (arg in profiles or arg.lower() in NONE_WORDS):
            folder, account = normalize(base), arg
        elif _path_like(arg) or os.path.isdir(folder_of(arg)):
            folder = folder_of(arg)
            return (0, _show(folder, home)) if os.path.isdir(folder) else \
                (1, f"dossier introuvable : {short_path(folder, home)}")
        else:
            return 2, f"dossier ou compte inconnu : {arg}\n{USAGE}"
    else:
        folder, account = folder_of(args[0]), args[1]
    where = short_path(folder, home)
    if not os.path.isdir(folder):
        return 1, f"dossier introuvable : {where}"
    remove = account.lower() in NONE_WORDS
    if not remove and account not in profiles:
        return 1, f"compte inconnu : {account} (voir « ccs list »)"
    try:
        had = remove and folder in _read()
        set(folder, None if remove else account)
    except (OSError, ValueError) as e:
        return 1, f"enregistrement impossible : {e}"
    if remove:
        return 0, (f"{where} n'est plus associé à un compte." if had
                   else f"{where} n'était associé à aucun compte.")
    return 0, (f"{where} → {account} : une session ouverte depuis l'application dans ce projet "
               f"proposera de basculer sur {account}.")
