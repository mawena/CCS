"""Coffre du mot de passe root (phase 34, gardé pour toujours depuis la 1.3.0).

Le mot de passe validé sur un appareil est écrit chiffré (AES-256-GCM) pour survivre aux
redémarrages du pont et de la machine :

- la clé (32 octets aléatoires) dans `~/.config/ccs/root.key` (0600) ;
- le chiffré dans `~/.local/state/ccs/root.vault` (0600), dans un autre dossier : une sauvegarde
  ou une copie de l'un sans l'autre ne révèle rien ;
- données associées : `/etc/machine-id` et l'uid, donc un coffre copié sur une autre machine ou un
  autre compte ne s'ouvre pas.

Limite assumée : un programme qui tourne sous ce même compte peut lire les deux fichiers. Il
pourrait de toute façon lancer `ccs root` et obtenir root tant que le mot de passe est gardé.
Le chiffrement protège donc le disque, les sauvegardes et les copies, pas le compte lui-même.
`ccs root oublier` (ou « Révoquer ») efface le coffre et la clé.
"""

import logging
import os
from pathlib import Path

log = logging.getLogger("ccs.root")

VERSION = b"ccs-root-v1"
NONCE_LEN = 12


def _xdg(var, default):
    return Path(os.environ.get(var) or Path.home() / default)


def key_path():
    return _xdg("XDG_CONFIG_HOME", ".config") / "ccs" / "root.key"


def vault_path():
    return _xdg("XDG_STATE_HOME", ".local/state") / "ccs" / "root.vault"


def _aad():
    try:
        mid = Path("/etc/machine-id").read_bytes().strip()
    except OSError:
        mid = b""
    return VERSION + b"|" + mid + b"|" + str(os.getuid()).encode()


def _write_private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _read_private(path):
    """Contenu d'un fichier à nous et illisible des autres ; None sinon."""
    try:
        st = path.lstat()
    except FileNotFoundError:
        return None
    if st.st_uid != os.getuid() or st.st_mode & 0o077 or not path.is_file():
        log.warning("root : %s n'est pas privé, ignoré", path.name)
        return None
    return path.read_bytes()


def _cipher(key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(bytes(key))


def available():
    try:
        import cryptography.hazmat.primitives.ciphers.aead  # noqa: F401
        return True
    except ImportError:
        return False


def _key(create):
    key = _read_private(key_path())
    if key is not None and len(key) == 32:
        return bytearray(key)
    if not create:
        return None
    key = bytearray(os.urandom(32))
    _write_private(key_path(), bytes(key))
    return key


def save(secret):
    """Chiffre et écrit `secret` (un `Secret`). Faux si impossible (jamais d'exception)."""
    if not available():
        log.warning("root : python3-cryptography manque, mot de passe gardé en mémoire seulement")
        return False
    try:
        key = _key(create=True)
        nonce = os.urandom(NONCE_LEN)
        plain = bytes(secret.view())
        try:
            data = nonce + _cipher(key).encrypt(nonce, plain, _aad())
        finally:
            del plain
            key[:] = bytes(len(key))
        _write_private(vault_path(), data)
        log.info("root : mot de passe gardé chiffré sur le disque")
        return True
    except Exception as e:  # noqa: BLE001 — jamais le secret dans un message
        log.warning("root : coffre impossible à écrire (%s)", type(e).__name__)
        return False


def load(secret_cls):
    """Le mot de passe du coffre (`secret_cls(bytes)`), ou None (absent, illisible, autre machine)."""
    if not available():
        return None
    try:
        data = _read_private(vault_path())
        if not data or len(data) <= NONCE_LEN:
            return None
        key = _key(create=False)
        if key is None:
            return None
        try:
            plain = bytearray(_cipher(key).decrypt(data[:NONCE_LEN], data[NONCE_LEN:], _aad()))
        finally:
            key[:] = bytes(len(key))
        secret = secret_cls(plain)
        plain[:] = bytes(len(plain))
        return secret
    except Exception as e:  # noqa: BLE001
        log.warning("root : coffre illisible (%s), ignoré", type(e).__name__)
        return None


def delete():
    """Efface le coffre et sa clé. Vrai s'il y avait quelque chose."""
    had = False
    for p in (vault_path(), key_path()):
        try:
            size = p.stat().st_size
            with open(p, "r+b") as f:       # écrase avant d'effacer
                f.write(b"\0" * size)
                f.flush()
                os.fsync(f.fileno())
            p.unlink()
            had = True
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning("root : %s impossible à effacer (%s)", p.name, type(e).__name__)
    return had
