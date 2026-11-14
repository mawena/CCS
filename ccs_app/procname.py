"""Nom de processus lisible (top, ps, Moniteur système, journal) : ccs-gui, ccs-daemon…"""

import ctypes
import sys

PR_SET_NAME = 15
NAMES = {"gui": "ccs-gui", "daemon": "ccs-daemon", "tray": "ccs-tray"}
DEFAULT = "ccs"


def name_for(argv):
    """Nom de processus selon la sous-commande (sans sous-commande : l'interface graphique)."""
    args = [a for a in argv if not a.startswith("-")]
    if not args:
        return NAMES["gui"]
    return NAMES.get(args[0], DEFAULT)


def apply(name):
    """Pose le nom ; renvoie True si le noyau l'a pris. Ne lève jamais d'exception."""
    ok = False
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        ok = libc.prctl(PR_SET_NAME, name.encode()[:15], 0, 0, 0) == 0
    except Exception:
        pass
    try:
        import setproctitle  # facultatif
        setproctitle.setproctitle(name)
    except Exception:
        pass
    return ok


def setup(argv=None):
    name = name_for(sys.argv[1:] if argv is None else argv)
    apply(name)
    return name
