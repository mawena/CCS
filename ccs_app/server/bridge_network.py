"""Réseau maillé depuis le pont (`network.*`) : appareils, chemin de chaque liaison, latence,
inscription, renommage et retrait. Toujours traité sur ce serveur, même quand le web pilote une
autre machine (comme `machines.*`).

Le client `tailscale` local donne l'état (pairs, chemin, adresses publiées) ; `headscale` (sur le
serveur du réseau, compte dans le groupe `headscale`) crée les clés et gère les appareils.
"""

import asyncio
import shutil
import time

from .. import network
from . import rpc

KEY_TTL_S = 15 * 60


def _err(e):
    return rpc.RpcError("introuvable", str(e))


class NetworkApi:
    def __init__(self, bridge, run=None):
        self.bridge = bridge
        self._run = run
        bridge.add_handlers({
            "network.status": self.status, "network.ping": self.ping, "network.key": self.key,
            "network.rename": self.rename, "network.remove": self.remove,
            "network.register": self.register})

    def _server(self):
        return self._run is not None or shutil.which("headscale") is not None

    def _status(self):
        out = {"url": network.SERVER_URL, "domain": network.BASE_DOMAIN,
               "installed": self._run is not None or network.installed(),
               "server": self._server(), "state": "", "self": None, "peers": [], "nodes": []}
        if out["installed"]:
            try:
                out.update(network.status(run=self._run))
            except network.NetworkError as e:
                out["error"] = str(e)
        if out["server"]:
            try:
                out["nodes"] = network.server_nodes(run=self._run)
            except network.NetworkError as e:
                out["server_error"] = str(e)
        return out

    async def status(self, _conn, _params):
        return await asyncio.to_thread(self._status)

    @staticmethod
    def _name(params, key="name"):
        name = params.get(key)
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise rpc.RpcError("invalide", "Nom d'appareil manquant.")
        return name.strip()

    async def ping(self, _conn, params):
        name = self._name(params)
        try:
            return await asyncio.to_thread(network.ping, name, self._run)
        except network.NetworkError as e:
            raise _err(e) from None

    async def key(self, _conn, params):
        if not self._server():
            raise rpc.RpcError("introuvable", "Ce serveur n'héberge pas le réseau (headscale absent).")
        host = params.get("name") or None
        if host is not None and not network.NAME_RE.match(str(host)):
            raise rpc.RpcError("invalide", "Nom invalide : lettres minuscules, chiffres et tirets.")
        try:
            k = await asyncio.to_thread(network.auth_key, network.DEFAULT_USER, network.KEY_TTL, self._run)
        except network.NetworkError as e:
            raise _err(e) from None
        return {"key": k, "url": network.SERVER_URL, "expires_at": time.time() + KEY_TTL_S,
                "linux": network.join_lines(k, host)}

    async def rename(self, _conn, params):
        try:
            await asyncio.to_thread(network.rename, self._name(params), self._name(params, "new"), self._run)
        except network.NetworkError as e:
            raise rpc.RpcError("invalide", str(e)) from None
        return {"ok": True}

    async def remove(self, _conn, params):
        try:
            await asyncio.to_thread(network.remove, self._name(params), self._run)
        except network.NetworkError as e:
            raise _err(e) from None
        return {"ok": True}

    async def register(self, _conn, params):
        key = params.get("key")
        if not isinstance(key, str):
            raise rpc.RpcError("invalide", "Clé manquante.")
        try:
            return {"name": await asyncio.to_thread(network.register, key, network.DEFAULT_USER, self._run)}
        except network.NetworkError as e:
            raise rpc.RpcError("invalide", str(e)) from None

