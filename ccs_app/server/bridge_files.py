"""Gestion des fichiers depuis le web : télécharger, envoyer, créer, renommer, supprimer, copier,
déplacer ; `files.roots` donne les dossiers de départ du gestionnaire de fichiers.

Tout reste dans les dossiers permis (`bridge_data.safe_path`). Les transferts passent par le RPC,
morceau par morceau (`CHUNK` octets au plus), parce qu'une ligne RPC est bornée ; un envoi s'écrit
d'abord dans un fichier d'attente « .nom.ccs-envoi », renommé à la fin : un envoi coupé ne laisse
jamais un fichier à moitié écrit sous son vrai nom.
"""
import asyncio
import base64
import binascii
import os
import secrets
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from . import rpc
from .bridge_data import EXTRA_ROOTS, _home, _under, safe_path

CHUNK = 1024 * 1024                    # octets par morceau (≈ 1,4 Mo une fois en base64)
MAX_TRANSFER = 200 * 1024 * 1024       # taille maximale d'un fichier téléchargé ou envoyé
MAX_COPY = 2 * 1024 * 1024 * 1024      # taille maximale d'une copie (le disque du serveur est compté)
PART = ".ccs-envoi"
ARCHIVE_TTL = 3600                     # une archive non téléchargée est effacée au bout d'une heure


def _archives():
    """Dossier privé des archives de dossiers en attente de téléchargement."""
    folder = Path(tempfile.gettempdir()) / f"ccs-archives-{os.getuid()}"
    folder.mkdir(mode=0o700, exist_ok=True)
    return folder


def _archive_path(token):
    if not isinstance(token, str) or len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
        raise rpc.RpcError("invalide", "Archive invalide.")
    return _archives() / f"{token}.zip"


def _sweep(folder, now=None):
    """Efface les archives trop vieilles (téléchargement abandonné)."""
    now = now or time.time()
    for old in folder.glob("*.zip*"):
        try:
            if now - old.stat().st_mtime > ARCHIVE_TTL:
                old.unlink()
        except OSError:
            pass


def _name(value):
    """Nom d'une entrée, sans chemin : ni « / », ni « . » ou « .. », ni caractère nul."""
    if (not isinstance(value, str) or not value.strip() or value in (".", "..") or "/" in value
            or "\0" in value or len(value.encode("utf-8", "surrogatepass")) > 255):
        raise rpc.RpcError("invalide", "Nom refusé : pas de « / », pas vide, 255 octets au plus.")
    return value


def _entry(value):
    """Chemin d'une entrée sans suivre son dernier maillon : un lien se renomme ou se supprime
    lui-même, jamais sa cible."""
    if not isinstance(value, str) or not value or "\0" in value or not os.path.isabs(value):
        raise rpc.RpcError("refuse", "Chemin refusé.")
    value = os.path.normpath(value)
    return safe_path(os.path.dirname(value)) / _name(os.path.basename(value))


def _folder(value):
    path = safe_path(value)
    if not path.is_dir():
        raise rpc.RpcError("introuvable", "Dossier introuvable.")
    return path


def _protected(path, root):
    """Dossiers qu'on ne renomme ni ne supprime : le dossier personnel, les racines permises, le
    projet ouvert et tout ce qui le contient."""
    p = str(path)
    tops = [_home(), *EXTRA_ROOTS] + ([os.path.realpath(root)] if isinstance(root, str) and root else [])
    return any(_under(top, p) for top in tops)


def _count(path):
    n = 0
    for _folder_, dirs, files in os.walk(path):
        n += len(dirs) + len(files)
        if n > 100000:
            break
    return n


def _weight(path):
    """Octets d'un fichier ou d'un dossier entier ; s'arrête dès que `MAX_COPY` est dépassé."""
    if not path.is_dir() or path.is_symlink():
        return path.lstat().st_size
    total = 0
    for folder, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:
                pass
        if total > MAX_COPY:
            break
    return total


def _free_name(folder, name):
    """« nom (copie).ext », « nom (copie 2).ext »… : premier nom libre dans `folder`."""
    stem, ext = os.path.splitext(name)
    for i in range(1, 1000):
        candidate = f"{stem} (copie{'' if i == 1 else f' {i}'}){ext}"
        if not os.path.lexists(folder / candidate):
            return candidate
    raise rpc.RpcError("existe", f"« {name} » existe déjà.")


class FileOps:
    def __init__(self, bridge):
        bridge.add_handlers({
            "files.download": self.download, "files.upload": self.upload,
            "files.mkdir": self.mkdir, "files.create": self.create,
            "files.rename": self.rename, "files.delete": self.delete,
            "files.info": self.info, "files.roots": self.roots, "files.paste": self.paste,
            "files.archive": self.archive,
        })

    async def roots(self, _conn, _params):
        """Dossiers de départ du gestionnaire : le dossier personnel, puis les racines du serveur."""
        home = _home()
        return {"home": home, "roots": [home] + [r for r in EXTRA_ROOTS if os.path.isdir(r)]}

    async def paste(self, _conn, params):
        """Colle `path` dans le dossier `dir` : copie (`mode` « copy ») ou déplacement (« move »).
        Une copie dans son propre dossier prend un nom libre (« nom (copie) »)."""
        path = _entry(params.get("path"))
        folder = _folder(params.get("dir"))
        mode, root = params.get("mode"), params.get("root")
        if mode not in ("copy", "move"):
            raise rpc.RpcError("invalide", "Action inconnue.")

        def work():
            if not os.path.lexists(path):
                raise rpc.RpcError("introuvable", "Fichier introuvable.")
            is_dir = path.is_dir() and not path.is_symlink()
            if is_dir and _under(str(folder), str(path)):
                raise rpc.RpcError("refuse", "Un dossier ne se colle pas dans lui-même.")
            name = path.name
            if mode == "move":
                if _protected(path, root):
                    raise rpc.RpcError("refuse", "Ce dossier ne se déplace pas d'ici.")
                if folder == path.parent:
                    raise rpc.RpcError("invalide", f"« {name} » est déjà dans ce dossier.")
                if os.path.lexists(folder / name):
                    raise rpc.RpcError("existe", f"« {name} » existe déjà dans ce dossier.")
            else:
                if _weight(path) > MAX_COPY:
                    raise rpc.RpcError("trop_gros", "Trop gros pour être copié d'ici (2 Go au plus).")
                if os.path.lexists(folder / name):
                    if folder != path.parent:
                        raise rpc.RpcError("existe", f"« {name} » existe déjà dans ce dossier.")
                    name = _free_name(folder, name)
            target = folder / name
            try:
                if mode == "move":
                    shutil.move(str(path), str(target))
                elif is_dir:
                    shutil.copytree(path, target, symlinks=True)
                else:
                    shutil.copy2(path, target, follow_symlinks=False)
            except (OSError, shutil.Error) as e:
                raise rpc.RpcError("refuse", f"{'Déplacement' if mode == 'move' else 'Copie'} impossible : "
                                             f"{getattr(e, 'strerror', None) or e}.") from None
            return {"path": str(target)}
        return await asyncio.to_thread(work)

    async def info(self, _conn, params):
        """Ce qu'une suppression emporterait : dossier ou non, nombre d'entrées dedans."""
        path = _entry(params.get("path"))

        def work():
            if not os.path.lexists(path):
                raise rpc.RpcError("introuvable", "Fichier introuvable.")
            is_dir = path.is_dir() and not path.is_symlink()
            return {"dir": is_dir, "count": _count(path) if is_dir else 0,
                    "size": 0 if is_dir else path.lstat().st_size}
        return await asyncio.to_thread(work)

    async def archive(self, _conn, params):
        """Met un dossier entier dans une archive .zip, téléchargée ensuite par `files.download`
        avec `archive` (le jeton rendu) ; l'archive est effacée à la fin du téléchargement."""
        path = safe_path(params.get("path"))

        def work():
            if not path.is_dir():
                raise rpc.RpcError("introuvable", "Dossier introuvable.")
            if _weight(path) > MAX_COPY:
                raise rpc.RpcError("trop_gros", "Dossier trop gros pour être archivé (2 Go au plus).")
            folder = _archives()
            _sweep(folder)
            token = secrets.token_hex(16)
            target = folder / f"{token}.zip"
            part = folder / f"{token}.zip.part"
            try:
                with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                    for root, dirs, files in os.walk(path):
                        dirs.sort()
                        base = Path(root)
                        rel = base.relative_to(path.parent)
                        if not files and not dirs:
                            z.writestr(f"{rel.as_posix()}/", b"")
                        for name in sorted(files):
                            item = base / name
                            if item.is_symlink() or not item.is_file():
                                continue
                            try:
                                z.write(item, (rel / name).as_posix())
                            except OSError:
                                continue      # illisible : on passe
                    if part.stat().st_size > MAX_TRANSFER:
                        raise rpc.RpcError("trop_gros", "Archive trop grosse pour être téléchargée (200 Mo au plus).")
                part.rename(target)
            except BaseException:
                part.unlink(missing_ok=True)
                raise
            return {"archive": token, "name": f"{path.name or 'racine'}.zip", "size": target.stat().st_size}
        return await asyncio.to_thread(work)

    async def download(self, _conn, params):
        archive = params.get("archive")
        path = _archive_path(archive) if archive is not None else safe_path(params.get("path"))
        offset = params.get("offset", 0)
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise rpc.RpcError("invalide", "Position invalide.")

        def work():
            if not path.is_file():
                raise rpc.RpcError("introuvable", "Fichier introuvable.")
            size = path.stat().st_size
            if size > MAX_TRANSFER:
                raise rpc.RpcError("trop_gros", "Fichier trop gros pour être téléchargé (200 Mo au plus).")
            try:
                with open(path, "rb") as f:
                    f.seek(offset)
                    data = f.read(CHUNK)
            except OSError:
                raise rpc.RpcError("introuvable", "Fichier illisible.") from None
            done = offset + len(data) >= size
            if done and archive is not None:
                path.unlink(missing_ok=True)      # archive livrée : plus besoin de la garder
            return {"size": size, "data": base64.b64encode(data).decode("ascii"), "done": done}
        return await asyncio.to_thread(work)

    async def upload(self, _conn, params):
        folder = _folder(params.get("dir"))
        name = _name(params.get("name"))
        offset, last, replace = params.get("offset", 0), params.get("last") is True, params.get("replace") is True
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise rpc.RpcError("invalide", "Position invalide.")
        try:
            data = base64.b64decode(params.get("data") or "", validate=True)
        except (binascii.Error, TypeError, ValueError):
            raise rpc.RpcError("invalide", "Données invalides.") from None
        if len(data) > CHUNK or offset + len(data) > MAX_TRANSFER:
            raise rpc.RpcError("trop_gros", "Fichier trop gros pour être envoyé (200 Mo au plus).")
        target, part = folder / name, folder / f".{name}{PART}"

        def work():
            if os.path.lexists(target) and (not replace or target.is_dir()):
                raise rpc.RpcError("existe", f"« {name} » existe déjà.")
            try:
                if offset == 0:
                    part.write_bytes(data)
                else:
                    if not part.is_file() or part.stat().st_size != offset:
                        raise rpc.RpcError("conflit", "Envoi interrompu : recommence.")
                    with open(part, "ab") as f:
                        f.write(data)
                if last:
                    os.replace(part, target)
            except OSError as e:
                part.unlink(missing_ok=True)
                raise rpc.RpcError("refuse", f"Écriture impossible : {e.strerror or e}.") from None
            return {"received": offset + len(data), "done": last}
        return await asyncio.to_thread(work)

    async def _new(self, params, make):
        folder = _folder(params.get("dir"))
        name = _name(params.get("name"))

        def work():
            target = folder / name
            if os.path.lexists(target):
                raise rpc.RpcError("existe", f"« {name} » existe déjà.")
            try:
                make(target)
            except OSError as e:
                raise rpc.RpcError("refuse", f"Création impossible : {e.strerror or e}.") from None
            return {"path": str(target)}
        return await asyncio.to_thread(work)

    async def mkdir(self, _conn, params):
        return await self._new(params, lambda p: p.mkdir())

    async def create(self, _conn, params):
        return await self._new(params, lambda p: p.touch(exist_ok=False))

    async def rename(self, _conn, params):
        path = _entry(params.get("path"))
        name = _name(params.get("name"))
        root = params.get("root")

        def work():
            if not os.path.lexists(path):
                raise rpc.RpcError("introuvable", "Fichier introuvable.")
            if _protected(path, root):
                raise rpc.RpcError("refuse", "Ce dossier ne se renomme pas d'ici.")
            target = path.parent / name
            if os.path.lexists(target):
                raise rpc.RpcError("existe", f"« {name} » existe déjà.")
            try:
                os.rename(path, target)
            except OSError as e:
                raise rpc.RpcError("refuse", f"Renommage impossible : {e.strerror or e}.") from None
            return {"path": str(target)}
        return await asyncio.to_thread(work)

    async def delete(self, _conn, params):
        path = _entry(params.get("path"))
        root = params.get("root")

        def work():
            if not os.path.lexists(path):
                raise rpc.RpcError("introuvable", "Fichier introuvable.")
            if _protected(path, root):
                raise rpc.RpcError("refuse", "Ce dossier ne se supprime pas d'ici.")
            try:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except OSError as e:
                raise rpc.RpcError("refuse", f"Suppression impossible : {e.strerror or e}.") from None
            return {"ok": True}
        return await asyncio.to_thread(work)

