"""Mode Portier : nginx vérifie l'identité (Portier) et l'annonce dans `X-Portier-Utilisateur`.

Contrat (`Portier/docs/integration.md`) : l'en-tête n'est cru que si l'option est activée,
si la connexion TCP vient de nginx sur la même machine (127.0.0.1 / ::1) et si le nom figure
dans la liste. Sinon, CCS garde sa propre connexion. Désactivé par défaut.

Configuration dans `/etc/ccs/web.json`, clé `portier` :
    {"portier": {"enabled": true, "users": ["charles-gamligo"],
                 "url": "https://portier.mawena.cloud",
                 "logout": "https://portier.mawena.cloud/"}}
`logout` est facultative (par défaut `<url>/`). Les clés d'avant la 1.0.0 (`actif`,
`utilisateurs`, `deconnexion`) sont encore lues quand la nouvelle est absente (à retirer en 2.0).

`ccs-web` et `ccs-auth` lisent tous deux ce fichier (à root, 0644) : `ccs-auth` revérifie
l'option et la liste avant de signer un ticket, `ccs-web` ne peut donc pas s'en passer.
"""

import json
from urllib.parse import quote

from . import paths

HEADER = "X-Portier-Utilisateur"
LOCAL = ("127.0.0.1", "::1")
DISABLED = {"enabled": False, "users": (), "url": "", "logout": ""}
# anciennes clés françaises de `web.json` → nouvelles (lues pendant toute la 1.x)
OLD_KEYS = {"actif": "enabled", "utilisateurs": "users", "deconnexion": "logout"}


def parse(data):
    """Réglages Portier d'après le contenu de `web.json` ; désactivé à la moindre anomalie."""
    section = data.get("portier") if isinstance(data, dict) else None
    if not isinstance(section, dict):
        return dict(DISABLED)
    section = dict(section)
    for old, new in OLD_KEYS.items():
        if old in section:
            section.setdefault(new, section[old])
    users = section.get("users")
    if not isinstance(users, list):
        users = []
    users = tuple(u.strip() for u in users if isinstance(u, str) and u.strip())
    url = section.get("url")
    url = url.strip().rstrip("/") if isinstance(url, str) else ""
    logout = section.get("logout")
    logout = logout.strip() if isinstance(logout, str) and logout.strip() else (f"{url}/" if url else "")
    return {"enabled": section.get("enabled") is True and bool(users), "users": users,
            "url": url, "logout": logout}


def load(path=None):
    try:
        with open(path or paths.web_config(), encoding="utf-8") as f:
            return parse(json.load(f))
    except (OSError, ValueError):
        return dict(DISABLED)


def allows(cfg, user):
    return bool(cfg and cfg.get("enabled")) and isinstance(user, str) and user in cfg["users"]


def trusted_user(cfg, remote, headers):
    """Nom annoncé par nginx s'il est digne de confiance, sinon None."""
    if not (cfg and cfg.get("enabled")) or remote not in LOCAL:
        return None
    user = (headers.get(HEADER) or "").strip()
    return user if allows(cfg, user) else None


def login_url(cfg, origin):
    """Adresse de connexion Portier qui ramène sur CCS (`<url>/connexion?retour=…`)."""
    if not (cfg and cfg.get("enabled") and cfg.get("url")):
        return ""
    return f"{cfg['url']}/connexion?retour={quote(origin.rstrip('/') + '/', safe='')}"
