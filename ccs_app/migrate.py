"""Migration des anciens noms de fichiers (passage aux noms anglais de la 1.0.0).

À retirer en 2.0 : pendant toute la 1.x, chaque chemin renommé passe par `renamed()` au moment
où CCS s'en sert (le premier lancement qui y touche fait la migration, une fois pour toutes).

Règle : l'ancien fichier (ou dossier) est renommé si le nouveau n'existe pas encore ; si les
deux existent, le nouveau est gardé et l'ancien laissé tel quel (jamais effacé). Deux
processus qui migrent en même temps ne se gênent pas : `os.rename` est atomique, le second
ne trouve plus l'ancien nom et s'arrête là.

Anciens noms (`$STORE` = dossier des comptes, voir `docs/interfaces.md`, § 4) :

    $STORE/serveurs.json            → $STORE/servers.json
    $STORE/etiquettes/              → $STORE/labels/
    $STORE/quiet_held.json          → $STORE/quiet-held.json
    $STORE/projects.json            → $STORE/project-accounts.json
    ~/.config/ccs/distant.toml      → ${XDG_CONFIG_HOME}/ccs/machines.toml
    ~/.cache/ccs/distant.json       → ${XDG_CACHE_HOME}/ccs/machines.json
    ~/.cache/ccs/distant/travaux/   → ${XDG_CACHE_HOME}/ccs/machines/jobs/
    ~/.cache/ccs/effacer/           → ${XDG_CACHE_HOME}/ccs/clear/
"""

import os
from pathlib import Path


def renamed(new, *old):
    """Chemin `new`, après avoir renommé le premier ancien chemin existant de `old` si `new`
    n'existe pas. Ne lève jamais : en cas d'échec, l'ancien reste où il est."""
    new = Path(new)
    for o in old:
        o = Path(o)
        if new.exists() or new.is_symlink():
            break
        if o == new or not (o.exists() or o.is_symlink()):
            continue
        try:
            new.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.rename(o, new)
        except OSError:
            pass
        break
    return new


def store_file(new, old):
    """Fichier ou dossier `new` du dossier des comptes, migré depuis `old` (même dossier)."""
    from . import core
    store = core.paths().store
    return renamed(store / new, store / old)
