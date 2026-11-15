"""Installation de Claude Code par l'installeur officiel, pour l'utilisateur courant (jamais
en root : Claude Code s'installe et se met à jour dans le dossier de l'utilisateur)."""

import os
import shutil
import subprocess
from pathlib import Path

INSTALL = "curl -fsSL https://claude.ai/install.sh | bash"
TIMEOUT = 600


def installed(which=shutil.which, home=None):
    if which("claude"):
        return True
    base = Path(home or os.environ.get("HOME") or Path.home())
    local = base / ".local" / "bin" / "claude"
    return local.is_file() and os.access(local, os.X_OK)


def install(run=subprocess.run, timeout=TIMEOUT):
    """(réussi, texte). Refuse en root ; ne lève jamais."""
    if os.geteuid() == 0:
        return False, "Claude Code ne s'installe pas en root : lance-le sous ton utilisateur."
    try:
        res = run(["sh", "-c", INSTALL], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "L'installation de Claude Code a dépassé 10 minutes."
    except OSError as e:
        return False, f"Installation impossible : {e}"
    out = ((res.stdout or "") + (res.stderr or "")).strip()
    tail = "\n".join(out.splitlines()[-5:])
    return res.returncode == 0, tail or ("Claude Code installé." if res.returncode == 0 else "Échec de l'installation.")
