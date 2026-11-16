"""Gestion des fichiers depuis le web : télécharger, envoyer, créer, renommer, supprimer.

Tout reste dans les dossiers permis (`bridge_data.safe_path`). Les transferts passent par le RPC,
morceau par morceau (`CHUNK` octets au plus), parce qu'une ligne RPC est bornée ; un envoi s'écrit
d'abord dans un fichier d'attente « .nom.ccs-envoi », renommé à la fin : un envoi coupé ne laisse
jamais un fichier à moitié écrit sous son vrai nom.
"""
import asyncio
import base64
import binascii
import os
import shutil

from . import rpc
from .bridge_data import EXTRA_ROOTS, _home, _under, safe_path

CHUNK = 1024 * 1024                    # octets par morceau (≈ 1,4 Mo une fois en base64)
MAX_TRANSFER = 200 * 1024 * 1024       # taille maximale d'un fichier téléchargé ou envoyé
PART = ".ccs-envoi"


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


class FileOps:
    def __init__(self, bridge):
        bridge.add_handlers({
            "files.download": self.download, "files.upload": self.upload,
            "files.mkdir": self.mkdir, "files.create": self.create,
            "files.rename": self.rename, "files.delete": self.delete,
            "files.info": self.info,
        })

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

    async def download(self, _conn, params):
        path = safe_path(params.get("path"))
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
            return {"size": size, "data": base64.b64encode(data).decode("ascii"),
                    "done": offset + len(data) >= size}
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

