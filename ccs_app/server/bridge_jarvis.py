"""Oreilles de Jarvis : le pont relaie une oreille « bouton » (version web, applis) vers le cerveau.

`ccs-web` n'a aucun droit : c'est le pont, qui tourne sous l'utilisateur, qui joint le cerveau
(`jarvis_link`) : directement par le réseau maillé quand la machine y est en ligne, sinon par le
tunnel Ricochet (secours). Une connexion au pont porte au
plus une oreille :

- `jarvis.open {fingerprint?, first}` : tunnel, TLS épinglé, WebSocket, puis envoi de `first`
  (le premier message de l'oreille, `hello` ou `pair`, tel quel : le cerveau exige un premier
  message moins de 3 s après l'ouverture). Empreinte absente : celle du réglage
  `jarvis.fingerprint` ; une empreinte donnée et vérifiée y est enregistrée.
- `jarvis.send {text}` ou `{binary}` (base64) : message suivant, relayé sans être lu (taille
  seulement : 64 Kio de texte, une trame de son de 16 000 échantillons).
- Événements poussés : `jarvis.message {text}` ou `{binary}` (base64), puis `jarvis.closed
  {reason}` quand le cerveau ferme ou que le lien tombe.
- `jarvis.close` ; la fermeture de la connexion ferme aussi le lien et arrête le tunnel.
- `jarvis.settings` / `jarvis.configure {machine?, port?}` : réglages (jamais relayés vers une
  machine pilotée, voir `Bridge.keeps_local`).
"""

import asyncio
import base64
import binascii
import copy
import logging

from .. import distant, settings
from . import jarvis_link, rpc

log = logging.getLogger("ccs.bridge.jarvis")


def _config():
    return settings.load_settings()["jarvis"]


def _save(**values):
    s = copy.deepcopy(settings.load_settings())
    s["jarvis"].update(values)
    bad = []
    cleaned = settings._clean(s, settings.DEFAULTS, "", bad)
    if any(p.startswith("jarvis.") for p in bad):
        raise rpc.RpcError("invalide", "Réglage de Jarvis invalide.")
    settings.save_settings(cleaned)


class Link:
    def __init__(self, ws, proc):
        self.ws = ws
        self.proc = proc
        self.reader = None

    async def close(self):
        if self.reader is not None and self.reader is not asyncio.current_task():
            self.reader.cancel()
        await self.ws.close()
        await jarvis_link.stop_process(self.proc)


class JarvisApi:
    def __init__(self, bridge, tunnel=None, timeout=jarvis_link.OPEN_TIMEOUT):
        self.bridge = bridge
        self._tunnel = tunnel or self._route
        self.timeout = timeout
        self.links = {}                       # connexion → Link
        self._opening = set()
        bridge.close_hooks.append(self._forget)
        bridge.busy_checks.append(lambda: bool(self.links))
        bridge.stop_hooks.append(self._close_all)
        bridge.add_handlers({
            "jarvis.settings": self.settings, "jarvis.configure": self.configure,
            "jarvis.open": self.open, "jarvis.send": self.send, "jarvis.close": self.close})

    @classmethod
    async def _route(cls, machine, port):
        """Réseau maillé d'abord (connexion directe), tunnel Ricochet en secours."""
        direct = await jarvis_link.open_mesh(machine, port)
        if direct is not None:
            return direct
        return await cls._ricochet(machine, port)

    @staticmethod
    async def _ricochet(machine, port):
        if not distant.configured():
            raise jarvis_link.LinkError("relais Ricochet non réglé sur ce serveur "
                                        "(~/.config/ricochet/client.toml)")
        return await jarvis_link.open_tunnel(machine, port)

    async def settings(self, _conn, _params):
        cfg = await asyncio.to_thread(_config)
        fp = jarvis_link.parse_fingerprint(cfg["fingerprint"])
        return {"machine": cfg["machine"], "port": cfg["port"],
                "fingerprint": cfg["fingerprint"],
                "fingerprint_short": jarvis_link.short_fingerprint(fp) if fp else ""}

    async def configure(self, conn, params):
        values = {}
        if params.get("machine") is not None:
            values["machine"] = params["machine"]
        if params.get("port") is not None:
            values["port"] = params["port"]
        if values:
            await asyncio.to_thread(_save, **values)
        return await self.settings(conn, {})

    async def open(self, conn, params):
        if conn in self.links or conn in self._opening:
            raise rpc.RpcError("conflit", "Une oreille est déjà ouverte sur cette connexion.")
        first = params.get("first")
        if not isinstance(first, str) or not first or len(first.encode("utf-8")) > jarvis_link.MAX_TEXT_OUT:
            raise rpc.RpcError("invalide", "Premier message de l'oreille manquant.")
        cfg = await asyncio.to_thread(_config)
        given = params.get("fingerprint") or ""
        fp = jarvis_link.parse_fingerprint(given or cfg["fingerprint"])
        if given and fp is None:
            raise rpc.RpcError("invalide", "Empreinte du cerveau invalide.")
        if fp is None:
            raise rpc.RpcError("introuvable", "Empreinte du cerveau inconnue : colle l'adresse "
                               "d'appairage donnée par « jarvis pair ».")
        where = f"{cfg['machine']}:{cfg['port']}"
        self._opening.add(conn)
        sock = proc = None
        try:
            try:
                sock, proc = await self._tunnel(cfg["machine"], cfg["port"])
                ws = await asyncio.wait_for(jarvis_link.connect(sock, fp), self.timeout)
            except (jarvis_link.LinkError, asyncio.TimeoutError, OSError) as e:
                if sock is not None:
                    sock.close()
                why = await jarvis_link.process_error(proc) or (
                    str(e) if isinstance(e, jarvis_link.LinkError) else "délai dépassé")
                await jarvis_link.stop_process(proc)
                log.warning("Jarvis injoignable (%s) : %s", where, why)
                raise rpc.RpcError("introuvable", f"Jarvis est injoignable ({where}) : {why}.") from None
            link = Link(ws, proc)
            if conn.closed:
                await link.close()
                raise rpc.RpcError("interne", "Connexion fermée.")
            try:
                await ws.send_text(first)
            except (jarvis_link.LinkError, ConnectionError) as e:
                await link.close()
                raise rpc.RpcError("introuvable", f"Jarvis est injoignable ({where}) : {e}.") from None
            self.links[conn] = link
        finally:
            self._opening.discard(conn)
        if given and given != cfg["fingerprint"]:
            try:
                await asyncio.to_thread(_save, fingerprint=given)
            except (OSError, rpc.RpcError):
                log.warning("empreinte de Jarvis non enregistrée")
        link.reader = asyncio.ensure_future(self._relay(conn, link))
        log.info("oreille relayée vers Jarvis (%s)", where)
        return {"machine": cfg["machine"], "port": cfg["port"],
                "fingerprint_short": jarvis_link.short_fingerprint(fp)}

    async def _relay(self, conn, link):
        reason = ""
        try:
            while True:
                msg = await link.ws.recv()
                if msg is None:
                    reason = link.ws.close_reason
                    break
                kind, data = msg
                payload = {"text": data} if kind == "text" else {"binary": base64.b64encode(data).decode()}
                await conn.push("jarvis.message", payload)
                if conn.closed:
                    break
        except jarvis_link.LinkError as e:
            reason = str(e)
        except asyncio.CancelledError:
            return
        if self.links.get(conn) is link:
            del self.links[conn]
            await conn.push("jarvis.closed", {"reason": reason})
            await link.close()

    async def send(self, conn, params):
        link = self.links.get(conn)
        if link is None or link.ws.closed:
            raise rpc.RpcError("introuvable", "Aucune oreille ouverte.")
        text, binary = params.get("text"), params.get("binary")
        try:
            if isinstance(text, str):
                if len(text.encode("utf-8")) > jarvis_link.MAX_TEXT_OUT:
                    raise rpc.RpcError("trop_gros", "Message trop gros.")
                await link.ws.send_text(text)
            elif isinstance(binary, str):
                if len(binary) > (jarvis_link.MAX_BINARY_OUT + 2) // 3 * 4:
                    raise rpc.RpcError("trop_gros", "Trame de son trop grosse.")
                try:
                    data = base64.b64decode(binary, validate=True)
                except (binascii.Error, ValueError):
                    raise rpc.RpcError("invalide", "Trame invalide.") from None
                if not data or len(data) > jarvis_link.MAX_BINARY_OUT:
                    raise rpc.RpcError("trop_gros", "Trame de son trop grosse.")
                await link.ws.send_binary(data)
            else:
                raise rpc.RpcError("invalide", "Message attendu (text ou binary).")
        except (jarvis_link.LinkError, ConnectionError):
            raise rpc.RpcError("introuvable", "Lien avec Jarvis rompu.") from None
        return {}

    async def close(self, conn, _params):
        link = self.links.pop(conn, None)
        if link is not None:
            await link.close()
        return {}

    def _forget(self, conn):
        link = self.links.pop(conn, None)
        if link is not None:
            asyncio.ensure_future(link.close())

    async def _close_all(self):
        links, self.links = list(self.links.values()), {}
        for link in links:
            await link.close()
