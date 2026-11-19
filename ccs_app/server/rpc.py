"""Protocole des services CCS : un objet JSON par ligne sur un socket Unix.

Requête `{"id", "method", "params"}` ; réponse `{"id", "result"}` ou `{"id", "error":
{"code", "message"}}` ; événement poussé par le serveur `{"event", "data"}`. Une ligne fait au
plus `MAX_LINE` octets. Rien de plus gros n'est envoyé : une réponse devient l'erreur `trop_gros`
pour cet appel seulement, un événement est laissé de côté, une requête est refusée avant
l'envoi ; la connexion reste utilisable. Une ligne reçue trop grosse ferme la connexion.
"""

import asyncio
import itertools
import json
import logging
import os
import shutil

log = logging.getLogger("ccs.rpc")

MAX_LINE = 8 * 1024 * 1024
CODES = ("refuse", "introuvable", "invalide", "trop_gros", "interne", "conflit", "occupe")


class RpcError(Exception):
    def __init__(self, code, message=""):
        self.code = code
        self.message = message or code
        super().__init__(f"{code} : {self.message}")


def encode(msg):
    return json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


async def read_message(reader):
    """Message suivant (dict), ou None à la fin du flux."""
    try:
        line = await reader.readline()
    except (ValueError, asyncio.LimitOverrunError):
        raise RpcError("trop_gros", "Message trop gros.") from None
    if not line:
        return None
    if len(line) > MAX_LINE + 1:
        raise RpcError("trop_gros", "Message trop gros.")
    try:
        msg = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RpcError("invalide", "JSON invalide.") from None
    if not isinstance(msg, dict):
        raise RpcError("invalide", "Un objet JSON est attendu.")
    return msg


def _error(mid, code, message):
    return {"id": mid, "error": {"code": code, "message": message}}


class Connection:
    """Une connexion côté serveur ; `peer` est libre (utilisateur, ticket…)."""

    def __init__(self, writer):
        self._writer = writer
        self._lock = asyncio.Lock()
        self.peer = {}
        self.closed = False

    async def send(self, msg):
        if self.closed:
            return
        data = encode(msg)
        if len(data) > MAX_LINE:
            if "event" in msg:
                log.warning("événement %s trop gros (%d octets) : non envoyé", msg.get("event"), len(data))
                return
            data = encode(_error(msg.get("id"), "trop_gros", "Réponse trop grosse pour être envoyée."))
        async with self._lock:
            try:
                self._writer.write(data)
                await self._writer.drain()
            except (ConnectionError, RuntimeError):
                self.closed = True

    async def push(self, event, data):
        await self.send({"event": event, "data": data})

    def close(self):
        self.closed = True
        try:
            self._writer.close()
        except RuntimeError:
            pass


class RpcServer:
    """`keep_local(method)` : sur une connexion relayée (`peer["forward"]`, appel asynchrone
    `forward(method, params)`), les méthodes pour lesquelles elle répond vrai restent traitées
    ici ; toutes les autres partent au relais."""

    def __init__(self, handlers, on_connect=None, on_close=None, keep_local=None):
        self.handlers = dict(handlers)
        self.keep_local = keep_local or (lambda method: False)
        self.on_connect = on_connect
        self.on_close = on_close
        self._server = None
        self._conns = set()

    async def start_unix(self, path, mode, group=None):
        path = str(path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        self._server = await asyncio.start_unix_server(self._serve, path, limit=MAX_LINE + 1)
        os.chmod(path, mode)
        if group:
            shutil.chown(path, group=group)

    async def close(self):
        if self._server is not None:
            self._server.close()
            for conn in list(self._conns):
                conn.close()
            await self._server.wait_closed()
            self._server = None

    async def _serve(self, reader, writer):
        conn = Connection(writer)
        self._conns.add(conn)
        tasks = set()
        try:
            if self.on_connect:
                self.on_connect(conn)
            while not conn.closed:
                try:
                    msg = await read_message(reader)
                except RpcError as e:
                    await conn.send(_error(None, e.code, e.message))
                    if e.code == "trop_gros":
                        break
                    continue
                if msg is None:
                    break
                task = asyncio.create_task(self._handle(conn, msg))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            for task in tasks:
                task.cancel()
            conn.close()
            self._conns.discard(conn)
            if self.on_close:
                try:
                    self.on_close(conn)
                except Exception:
                    log.exception("fermeture de connexion")

    async def _handle(self, conn, msg):
        mid = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}
        if not isinstance(method, str) or not isinstance(params, dict):
            await conn.send(_error(mid, "invalide", "Requête invalide."))
            return
        forward = conn.peer.get("forward")
        if forward is not None and not self.keep_local(method):
            async def handler(_conn, p):
                return await forward(method, p)
        else:
            handler = self.handlers.get(method)
        if handler is None:
            await conn.send(_error(mid, "introuvable", f"Méthode inconnue : {method}"))
            return
        try:
            result = await handler(conn, params)
        except RpcError as e:
            await conn.send(_error(mid, e.code, e.message))
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("méthode %s", method)
            await conn.send(_error(mid, "interne", "Erreur interne du service."))
            return
        await conn.send({"id": mid, "result": result if result is not None else {}})


class RpcClient:
    def __init__(self):
        self.on_event = None
        self._reader = self._writer = None
        self._pending = {}
        self._ids = itertools.count(1)
        self._task = None
        self._lock = asyncio.Lock()
        self._ended = asyncio.Event()

    async def connect_unix(self, path):
        reader, writer = await asyncio.open_unix_connection(str(path), limit=MAX_LINE + 1)
        self.attach(reader, writer)

    def attach(self, reader, writer):
        self._reader, self._writer = reader, writer
        self._task = asyncio.create_task(self._read_loop())

    @property
    def connected(self):
        return self._task is not None and not self._task.done()

    async def _read_loop(self):
        try:
            while True:
                msg = await read_message(self._reader)
                if msg is None:
                    break
                if "event" in msg:
                    if self.on_event:
                        try:
                            self.on_event(msg["event"], msg.get("data") or {})
                        except Exception:
                            log.exception("événement %s", msg.get("event"))
                    continue
                fut = self._pending.pop(msg.get("id"), None)
                if fut is None or fut.done():
                    continue
                if "error" in msg:
                    err = msg["error"] or {}
                    fut.set_exception(RpcError(err.get("code", "interne"), err.get("message", "")))
                else:
                    fut.set_result(msg.get("result") or {})
        except (RpcError, ConnectionError):
            pass
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RpcError("interne", "Connexion fermée."))
            self._pending.clear()
            self._ended.set()

    async def wait_closed(self):
        """Attend la fin de la connexion (fermée par l'autre côté, coupée ou illisible)."""
        await self._ended.wait()

    async def call(self, method, **params):
        if not self.connected:
            raise RpcError("interne", "Connexion fermée.")
        mid = next(self._ids)
        data = encode({"id": mid, "method": method, "params": params})
        if len(data) > MAX_LINE:
            raise RpcError("trop_gros", "Requête trop grosse.")
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        async with self._lock:
            self._writer.write(data)
            await self._writer.drain()
        return await fut

    async def close(self):
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except (ConnectionError, RuntimeError):
                pass
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
