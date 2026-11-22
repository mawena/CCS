"""Client du pont CCS, commun au bureau GTK et à `ccs tui`.

Deux transports : le socket du pont local de l'utilisateur (lancé par `ccs bridge --local` s'il
ne répond pas), ou le WebSocket d'un serveur CCS avec un jeton d'application. La connexion se
rétablit seule ; `on_state` reçoit "online", "offline", "reconnected" ou "auth" (jeton refusé).

Pont local plus ancien que ce client (CCS mis à jour, pont d'avant la relance automatique) : s'il
ne fait rien (aucun chat au travail, aucun terminal), le client l'arrête (SIGTERM sur le pid du pair du socket,
même utilisateur) et en lance un neuf. Un pont occupé est gardé tel quel.
"""

import asyncio
import itertools
import json
import os
import signal
import socket
import struct
import subprocess
import threading
import time

import aiohttp

from .. import __version__, core
from ..server import protocol, rpc

BUSY = ("starting", "busy", "permission")
RESPAWN_S = 30          # pont local lancé il y a moins longtemps : on attend, sans en relancer un


class AuthError(Exception):
    """Le serveur refuse le jeton (révoqué ou inconnu) : il faut appairer à nouveau."""


def default_socket():
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/ccs-{os.getuid()}"
    return os.path.join(base, "ccs", "bridge.sock")


def spawn_local_bridge():
    subprocess.Popen([core.ccs_bin(), "bridge", "--local"], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


class _LocalLink:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer

    async def send(self, msg):
        self.writer.write(rpc.encode(msg))
        await self.writer.drain()

    async def recv(self):
        return await rpc.read_message(self.reader)

    async def close(self):
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except (ConnectionError, RuntimeError):
            pass


def version_tuple(text):
    """« 0.37.0 » → (0, 37, 0) ; None si ce n'est pas une version."""
    try:
        return tuple(int(x) for x in str(text).split("-")[0].split("."))
    except (TypeError, ValueError):
        return None


def peer_pid(writer):
    """Pid du processus à l'autre bout d'un socket Unix, s'il tourne sous le même utilisateur."""
    sock = writer.get_extra_info("socket")
    try:
        pid, uid, _gid = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                             struct.calcsize("3i")))
    except (AttributeError, OSError, struct.error):
        return None
    return pid if uid == os.getuid() and pid > 0 else None


class LocalTransport:
    needs_hello = True

    def __init__(self, path=None, spawn=spawn_local_bridge, timeout=10, version=__version__,
                 kill=os.kill, clock=time.monotonic):
        self.path = str(path or default_socket())
        self.spawn = spawn
        self.timeout = timeout
        self.version = version
        self._kill = kill
        self._clock = clock
        self._spawned_at = None
        self._replaced = False
        self.label = "local"

    async def _open(self):
        r, w = await asyncio.open_unix_connection(self.path, limit=rpc.MAX_LINE + 1)
        return _LocalLink(r, w)

    async def outdated(self, client, link, hello):
        """Après `hello` : vrai si le pont, plus ancien que ce client et sans chat au travail, vient
        d'être arrêté (il faut se reconnecter : un pont neuf sera lancé). Une fois par client."""
        mine, theirs = version_tuple(self.version), version_tuple((hello or {}).get("version"))
        if self._replaced or self.spawn is None or not mine or not theirs or theirs >= mine:
            return False
        try:
            chats = (await client.call("chat.list")).get("chats") or []
            terms = (await client.call("term.list")).get("terms") or []
        except rpc.RpcError:
            return False
        if terms or any(c.get("state") in BUSY for c in chats):
            return False                 # un chat travaille, un terminal est ouvert : gardé tel quel
        pid = peer_pid(link.writer)
        if pid is None or pid == os.getpid():
            return False
        self._replaced = True
        try:
            self._kill(pid, signal.SIGTERM)
        except OSError:
            return False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 5
        while loop.time() < deadline:    # attendre qu'il ne réponde plus
            try:
                probe = await self._open()
            except (FileNotFoundError, ConnectionRefusedError):
                break
            await probe.close()
            await asyncio.sleep(0.1)
        self._spawned_at = None
        return True

    async def connect(self):
        try:
            return await self._open()
        except (FileNotFoundError, ConnectionRefusedError):
            recent = self._spawned_at is not None and self._clock() - self._spawned_at < RESPAWN_S
            if recent or self.spawn is None:
                raise ConnectionError("pont local injoignable") from None
        self._spawned_at = self._clock()
        self.spawn()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout
        while True:
            await asyncio.sleep(0.1)
            try:
                return await self._open()
            except (FileNotFoundError, ConnectionRefusedError):
                if loop.time() > deadline:
                    raise ConnectionError("le pont local ne démarre pas") from None


class _WebLink:
    def __init__(self, session, ws):
        self.session, self.ws = session, ws

    async def send(self, msg):
        await self.ws.send_str(json.dumps(msg, ensure_ascii=False))

    async def recv(self):
        msg = await self.ws.receive()
        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
            except ValueError:
                return {}
            return data if isinstance(data, dict) else {}
        return None

    async def close(self):
        await self.ws.close()
        await self.session.close()


class WebTransport:
    needs_hello = False

    def __init__(self, server):
        self.server = server
        self.label = server.name

    async def connect(self):
        session = aiohttp.ClientSession(headers={"User-Agent": "CCS"})
        try:
            ws = await session.ws_connect(self.server.url + f"/api/ws?protocol={protocol.PROTOCOL}",
                                          max_msg_size=rpc.MAX_LINE,
                                          headers={"Authorization": f"Bearer {self.server.token}"},
                                          heartbeat=30, timeout=20)
        except aiohttp.WSServerHandshakeError as e:
            await session.close()
            if e.status in (401, 403):
                raise AuthError("Jeton refusé : appaire de nouveau ce serveur.") from None
            raise ConnectionError(f"Serveur : erreur {e.status}") from None
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as e:
            await session.close()
            raise ConnectionError(f"Serveur injoignable : {e}") from None
        return _WebLink(session, ws)


class BridgeClient:
    def __init__(self, transport, retry_delays=(1, 2, 4, 8, 15, 30)):
        self.transport = transport
        self.retry_delays = tuple(retry_delays)
        self.on_event = None
        self.on_state = None
        self._link = None
        self._pending = {}
        self._ids = itertools.count(1)
        self._reader = None
        self._retry = None
        self._closing = False
        self.bridge_version = None
        self._quiet = set()

    @property
    def online(self):
        return self._link is not None

    def _state(self, state):
        if self.on_state:
            try:
                self.on_state(state)
            except Exception:
                pass

    async def _establish(self):
        link = await self.transport.connect()
        self._link = link
        self._reader = asyncio.ensure_future(self._read_loop(link))
        if self.transport.needs_hello:
            try:
                hello = await self.call("hello", protocol=protocol.PROTOCOL)
            except rpc.RpcError:
                await self._drop(link)
                raise ConnectionError("pont : bonjour refusé") from None
            self.bridge_version = (hello or {}).get("version")
            outdated = getattr(self.transport, "outdated", None)
            if outdated is not None:
                self._quiet.add(link)           # le pont arrêté ferme ce lien : pas une coupure
                if await outdated(self, link, hello):
                    await self._drop(link)      # ancien pont arrêté : le neuf est lancé ici
                    await self._establish()
                    return
                self._quiet.discard(link)

    async def connect(self):
        self._closing = False
        await self._establish()
        self._state("online")

    async def _drop(self, link):
        """Ferme un lien abandonné exprès : sa fin n'annonce pas de coupure (pas de reconnexion)."""
        self._quiet.add(link)
        if self._link is link:
            self._link = None
        await link.close()

    async def _read_loop(self, link):
        try:
            while True:
                msg = await link.recv()
                if msg is None:
                    break
                if "event" in msg:
                    if self.on_event:
                        try:
                            self.on_event(msg["event"], msg.get("data") or {})
                        except Exception:
                            pass
                    continue
                fut = self._pending.pop(msg.get("id"), None)
                if fut is None or fut.done():
                    continue
                if "error" in msg:
                    err = msg["error"] or {}
                    fut.set_exception(rpc.RpcError(err.get("code", "interne"), err.get("message", "")))
                else:
                    fut.set_result(msg.get("result") or {})
        except (rpc.RpcError, ConnectionError, aiohttp.ClientError, asyncio.IncompleteReadError):
            pass
        finally:
            if self._link is link:
                self._link = None
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(rpc.RpcError("interne", "Connexion perdue."))
            self._pending.clear()
            if link in self._quiet:
                self._quiet.discard(link)
            elif not self._closing:
                self._state("offline")
                if self.retry_delays and (self._retry is None or self._retry.done()):
                    self._retry = asyncio.ensure_future(self._reconnect())

    async def _reconnect(self):
        delays = itertools.chain(self.retry_delays, itertools.repeat(self.retry_delays[-1]))
        for delay in delays:
            await asyncio.sleep(delay)
            if self._closing:
                return
            try:
                await self._establish()
            except AuthError:
                self._state("auth")
                return
            except (ConnectionError, OSError, rpc.RpcError):
                continue
            self._state("reconnected")
            return

    async def call(self, method, **params):
        link = self._link
        if link is None:
            raise rpc.RpcError("interne", "Hors ligne.")
        mid = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        try:
            await link.send({"id": mid, "method": method, "params": params})
        except (ConnectionError, RuntimeError, aiohttp.ClientError):
            self._pending.pop(mid, None)
            raise rpc.RpcError("interne", "Connexion perdue.") from None
        return await fut

    async def close(self):
        self._closing = True
        if self._retry is not None:
            self._retry.cancel()
        link, self._link = self._link, None
        if link is not None:
            await link.close()
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):
                pass


class SyncBridgeClient:
    """Même client, utilisable depuis une interface (GTK, urwid) : une boucle asyncio tourne dans
    un fil ; réponses et événements reviennent par `dispatch(fonction, *arguments)`."""

    def __init__(self, transport, dispatch, retry_delays=(1, 2, 4, 8, 15, 30)):
        self.dispatch = dispatch
        self.client = BridgeClient(transport, retry_delays)
        self.on_event = None
        self.on_state = None
        self.client.on_event = lambda n, d: self.on_event and self.dispatch(self.on_event, n, d)
        self.client.on_state = lambda s: self.on_state and self.dispatch(self.on_state, s)
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True, name="ccs-client")
        self._connected = None
        self.error = None

    def start(self):
        self._thread.start()
        self._connected = asyncio.run_coroutine_threadsafe(self._connect(), self.loop)

    async def _connect(self):
        try:
            await self.client.connect()
            return True
        except (AuthError, ConnectionError, OSError, rpc.RpcError) as e:
            self.error = e
            if isinstance(e, AuthError):
                self.client.on_state and self.client.on_state("auth")
            elif self.client.retry_delays:
                self.client.on_state and self.client.on_state("offline")
                self.client._retry = asyncio.ensure_future(self.client._reconnect())
            return False

    async def _call(self, method, params):
        await asyncio.wrap_future(self._connected)
        return await self.client.call(method, **params)

    def call(self, method, callback=None, **params):
        fut = asyncio.run_coroutine_threadsafe(self._call(method, params), self.loop)
        if callback is not None:
            def done(f):
                err = f.exception()
                self.dispatch(callback, None if err else f.result(), err)
            fut.add_done_callback(done)
        return fut

    def call_sync(self, method, timeout=30, **params):
        return self.call(method, **params).result(timeout)

    def stop(self):
        if not self._thread.is_alive():
            return
        asyncio.run_coroutine_threadsafe(self.client.close(), self.loop).result(10)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(10)
