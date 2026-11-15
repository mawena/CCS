"""Chemins système du serveur CCS, tous sous `CCS_SERVER_ROOT` (tests) ou `/`."""

import os
import re
from pathlib import Path

_USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}\$?$")


def check_user(user):
    """Nom d'utilisateur Unix sûr pour un chemin ; ValueError sinon."""
    if not isinstance(user, str) or not _USER.match(user):
        raise ValueError(f"nom d'utilisateur invalide : {user!r}")
    return user


def root():
    return Path(os.environ.get("CCS_SERVER_ROOT") or "/")


def run_dir():
    return root() / "run" / "ccs"


def state_dir():
    return root() / "var" / "lib" / "ccs"


def etc_dir():
    return root() / "etc" / "ccs"


def auth_socket():
    return run_dir() / "auth.sock"


def bridge_socket(user):
    return run_dir() / "bridge" / f"{check_user(user)}.sock"


def bridge_key(user):
    return run_dir() / "bridge" / f"{check_user(user)}.key"


def totp_file(user):
    return state_dir() / "totp" / check_user(user)


def sessions_file():
    return state_dir() / "sessions.json"


def web_config():
    return etc_dir() / "web.json"
