"""Mot de passe root depuis les appareils (phase 34), côté pont : le gardien (`root_keeper`) et ses
méthodes et événements.

Méthodes :
    root.answer {id, password}    réponse à une demande (ou {id, cancel: true} pour la refuser) ;
                                  {ok, error?}. Le mot de passe est vérifié par `sudo -k -S -v`.
    root.status {}                {machine, kept, expires_at, remaining, pending} (jamais le secret)
    root.forget {}                {had} : efface le mot de passe et abandonne la demande en cours
Événements diffusés à tous les clients connectés :
    root.ask {id, machine, command, expires_at, tries_left, error?}   demande (à nouveau, avec
                                  `error`, après un mauvais mot de passe)
    root.resolved {id, ok}        demande réglée : les autres fenêtres se ferment
    root.used {machine, command, at}   commande lancée avec le mot de passe gardé
    root.forgotten {machine, reason}   mot de passe effacé (expired, forget, revoke, stop)

Un seul pont par utilisateur tient le socket du gardien (le premier lancé, service ou local).
Un autre pont du même utilisateur devient relais : il suit les événements du gardien (`watch`) et
les diffuse à ses propres clients, et lui transmet `root.*` ; si le gardien s'arrête, il prend sa
place. Avis ntfy (sans aucun secret) : à chaque demande, et à chaque commande lancée avec le mot
de passe gardé, avec un bouton « Révoquer » signé à usage unique (`phone_reply`).
"""

import asyncio
import json
import logging
import secrets
import threading
import urllib.parse

from .. import phone, phone_reply, root_keeper, settings
from . import rpc

log = logging.getLogger("ccs.root")

RELAY_RETRY_S = 2


class RootApi:
    def __init__(self, bridge, keeper=None, path=None, run=None, urlopen=None,
                 listener_factory=None, load_settings=None):
        self.bridge = bridge
        self.keeper = keeper or root_keeper.Keeper(clock=bridge.clock)
        self.keeper.listeners.append(self._on_event)
        self.server = root_keeper.KeeperServer(self.keeper, path)
        self.owner = False
        self.revokes = phone_reply.Replies()
        self.listener = None
        self._relay = None
        self._loop = None
        self._run = run                      # exécuteur des envois ntfy (tests : appel direct)
        self._urlopen = urlopen
        self._listener_factory = listener_factory or phone_reply.Listener
        self._load_settings = load_settings or settings.load_settings
        bridge.prepare_hooks.append(self.start)
        bridge.stop_hooks.append(self.stop)
        bridge.busy_checks.append(self.keeper.busy)
        bridge.add_handlers({"root.answer": self.answer, "root.status": self.status,
                             "root.forget": self.forget})

    # ---- gardien ou relais ------------------------------------------------------------

    async def start(self):
        self._loop = asyncio.get_running_loop()
        if not await self._own():
            self._relay = asyncio.ensure_future(self._relay_loop())

    async def _own(self):
        try:
            await self.server.start()
        except root_keeper.AlreadyServed:
            return False
        except OSError as e:
            log.warning("root : socket du gardien impossible à ouvrir (%s)", type(e).__name__)
            return False
        self.owner = True
        return True

    async def _relay_loop(self):
        """Suit le gardien d'un autre pont ; reprend sa place s'il s'arrête."""
        while True:
            try:
                r, w = await root_keeper.async_open(self.server.path)
                try:
                    w.write(b'{"op": "watch"}\n')
                    await w.drain()
                    while True:
                        line = await r.readline()
                        if not line:
                            break
                        msg = json.loads(line)
                        await self.bridge.broadcast(msg["event"], msg["data"])
                finally:
                    w.close()
            except (OSError, ValueError, KeyError, TypeError, asyncio.TimeoutError):
                pass
            await asyncio.sleep(RELAY_RETRY_S)
            if await self._own():
                return

    async def stop(self):
        if self._relay is not None:
            self._relay.cancel()
            self._relay = None
        self.keeper.close()
        await self.server.close()
        self.owner = False
        self._stop_listener()

    # ---- méthodes ---------------------------------------------------------------------

    async def answer(self, _conn, params):
        rid = params.get("id")
        password = params.pop("password", None)
        cancel = params.get("cancel") is True
        try:
            if self.owner:
                try:
                    return await self.keeper.answer(rid, password, cancel=cancel)
                except root_keeper.KeeperError as e:
                    raise rpc.RpcError(e.code, e.message) from None
            try:
                res = await root_keeper.async_request(
                    "answer", path=self.server.path, timeout=root_keeper.VERIFY_TIMEOUT_S + 10,
                    id=rid, password=password, cancel=cancel)
            except (OSError, ValueError, asyncio.TimeoutError):
                raise rpc.RpcError("introuvable", "Gardien du mot de passe injoignable.") from None
            if res.get("code"):
                raise rpc.RpcError(res["code"], str(res.get("error") or res["code"]))
            return res
        finally:
            password = None

    async def status(self, _conn, _params):
        if self.owner:
            return self.keeper.status()
        try:
            return await root_keeper.async_request("status", path=self.server.path)
        except (OSError, ValueError, asyncio.TimeoutError):
            return {"machine": self.keeper.machine, "kept": False, "expires_at": None,
                    "remaining": 0, "pending": None}

    async def forget(self, _conn, _params):
        if self.owner:
            return {"had": self.keeper.forget("forget")}
        try:
            res = await root_keeper.async_request("forget", path=self.server.path)
        except (OSError, ValueError, asyncio.TimeoutError):
            return {"had": False}
        return {"had": bool(res.get("had"))}

    # ---- événements du gardien ------------------------------------------------------

    def _on_event(self, event, data):
        try:
            if event == "root.ask" and "error" not in data:
                self._phone_ask(data)
            elif event == "root.used":
                self._phone_used(data)
            elif event == "root.forgotten":
                self.revokes.settle_all()
                self._stop_listener()
        except Exception as e:  # noqa: BLE001 — un avis manqué n'empêche pas la diffusion
            log.warning("root : avis téléphone impossible (%s)", type(e).__name__)
        return self.bridge.broadcast(event, data)

    def _phone(self):
        s = self._load_settings()
        if not phone.ready(s):
            return None, None
        return s, phone.config(s)

    def _send(self, cfg, msg, actions=None, click=None):
        def work():
            phone.deliver(cfg, msg, self._urlopen, actions=actions, click=click)
        if self._run is not None:
            self._run(work)
        else:
            threading.Thread(target=work, name="ccs-telephone-root", daemon=True).start()

    def _phone_ask(self, data):
        s, cfg = self._phone()
        if cfg is None:
            return
        # Toucher l'avis ouvre la popup de l'appli CCS (Android, iPhone) sur cette machine.
        machine = urllib.parse.quote(str(data.get("machine") or ""), safe="")
        self._send(cfg, phone_reply.root_ask_message(data.get("machine"), data.get("command"),
                                                     cfg["show_content"]),
                   click=f"ccs://root?machine={machine}")

    def _phone_used(self, data):
        s, cfg = self._phone()
        if cfg is None:
            return
        topic = phone_reply.reply_topic(s)
        rid = secrets.token_urlsafe(6)
        ttl = max(60, self.keeper.status()["remaining"])
        token = self.revokes.issue(rid, ttl=ttl)
        msg = phone_reply.root_used_message(data.get("machine"), data.get("command"), cfg["show_content"])
        self._send(cfg, msg, phone_reply.revoke_header(cfg, topic, rid, token))
        if self.listener is None:
            self.listener = self._listener_factory(cfg, topic, self._on_body)
            self.listener.start()

    def _on_body(self, body):
        """Réponse publiée sur le sujet secret (fil d'écoute) : « Révoquer » vérifié."""
        if self.revokes.verify(body, decisions=("revoke",)) is None:
            return
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._revoke)

    def _revoke(self):
        log.info("root : mot de passe révoqué depuis le téléphone")
        self.keeper.forget("revoke")

    def _stop_listener(self):
        listener, self.listener = self.listener, None
        if listener is not None:
            listener.stop()
