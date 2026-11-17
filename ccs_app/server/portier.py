"""Mode Portier : nginx vérifie l'identité (Portier) et l'annonce dans `X-Portier-Utilisateur`.

Contrat (`Portier/docs/integration.md`) : l'en-tête n'est cru que si l'option est activée,
si la connexion TCP vient de nginx sur la même machine (127.0.0.1 / ::1) et si le nom figure
dans la liste. Sinon, CCS garde sa propre connexion. Désactivé par défaut.

Configuration dans `/etc/ccs/web.json`, clé `portier` :
    {"portier": {"actif": true, "utilisateurs": ["charles-gamligo"],
                 "url": "https://portier.mawena.cloud",
                 "deconnexion": "https://portier.mawena.cloud/"}}
`deconnexion` est facultative (par défaut `<url>/`).

`ccs-web` et `ccs-auth` lisent tous deux ce fichier (à root, 0644) : `ccs-auth` revérifie
l'option et la liste avant de signer un ticket, `ccs-web` ne peut donc pas s'en passer.
"""

import json
from urllib.parse import quote

from . import paths

HEADER = "X-Portier-Utilisateur"
LOCAL = ("127.0.0.1", "::1")
DISABLED = {"actif": False, "utilisateurs": (), "url": "", "deconnexion": ""}


def parse(data):
    """Réglages Portier d'après le contenu de `web.json` ; désactivé à la moindre anomalie."""
    section = data.get("portier") if isinstance(data, dict) else None
    if not isinstance(section, dict):
        return dict(DISABLED)
    users = section.get("utilisateurs")
    if not isinstance(users, list):
        users = []
    users = tuple(u.strip() for u in users if isinstance(u, str) and u.strip())
    url = section.get("url")
    url = url.strip().rstrip("/") if isinstance(url, str) else ""
    logout = section.get("deconnexion")
    logout = logout.strip() if isinstance(logout, str) and logout.strip() else (f"{url}/" if url else "")
    return {"actif": section.get("actif") is True and bool(users), "utilisateurs": users,
            "url": url, "deconnexion": logout}


def load(path=None):
    try:
        with open(path or paths.web_config(), encoding="utf-8") as f:
            return parse(json.load(f))
    except (OSError, ValueError):
        return dict(DISABLED)


def allows(cfg, user):
    return bool(cfg and cfg.get("actif")) and isinstance(user, str) and user in cfg["utilisateurs"]


def trusted_user(cfg, remote, headers):
    """Nom annoncé par nginx s'il est digne de confiance, sinon None."""
    if not (cfg and cfg.get("actif")) or remote not in LOCAL:
        return None
    user = (headers.get(HEADER) or "").strip()
    return user if allows(cfg, user) else None


def login_url(cfg, origin):
    """Adresse de connexion Portier qui ramène sur CCS (`<url>/connexion?retour=…`)."""
    if not (cfg and cfg.get("actif") and cfg.get("url")):
        return ""
    return f"{cfg['url']}/connexion?retour={quote(origin.rstrip('/') + '/', safe='')}"
