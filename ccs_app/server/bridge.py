"""Pont CCS d'un utilisateur : tourne sous lui (service `ccs-bridge@<utilisateur>`, ou
`ccs bridge --local` pour `ccs tui` sur la machine même) et fait pour le web, le terminal et
le bureau ce que l'application GTK fait en local : comptes, chats, fichiers, feuille de route…

Toute connexion commence par `hello` : le ticket remis par `ccs-auth` (HMAC de l'empreinte de
la session par la clé du pont) est vérifié ; en mode local, le socket est en 0600 dans le
dossier de l'utilisateur et `hello` suffit.
"""

import asyncio
import copy
import dataclasses
import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone

from .. import core, daemon, pause, settings
from . import rpc

log = logging.getLogger("ccs.bridge")

IDLE_STOP = 12 * 3600


class Bridge:
    def __init__(self, user, key, local=False, clock=time.time, start_daemon=True,
                 install_claude=True):
        self.user = user
        self.key = key
        self.local = local
        self.clock = clock
        self.start_daemon = start_daemon
        self.install_claude = install_claude
        self.clients = set()
        self.busy_checks = []        # fonctions qui disent « un travail est en cours »
        self.close_hooks = []        # appelées à la fermeture d'une connexion
        self.tick_hooks = []         # coroutines appelées chaque minute (ménage)
        self.last_activity = clock()
        self._server = None
        self._handlers = {}
        self._stop = asyncio.Event()
        self.add_handlers({
            "accounts.state": self.accounts_state,
            "accounts.refresh": self.accounts_refresh,
            "accounts.switch": self.accounts_switch,
            "pause.set": self.pause_set,
            "settings.get": self.settings_get,
            "settings.set": self.settings_set,
        })

    # ---- serveur ---------------------------------------------------------------------

    def add_handlers(self, handlers):
        self._handlers.update(handlers)

    def handlers(self):
        out = {"hello": self.hello}
        for name, fn in self._handlers.items():
            out[name] = self._guarded(fn)
        return out

    def _guarded(self, fn):
        async def handler(conn, params):
            if not conn.peer.get("ok"):
                # le refus part d'abord, la connexion est fermée juste après
                asyncio.get_running_loop().call_later(0.05, conn.close)
                raise rpc.RpcError("refuse", "Connexion non authentifiée.")
            self.last_activity = self.clock()
            return await fn(conn, params)
        return handler

    async def hello(self, conn, params):
        if not self.local:
            t, h = params.get("ticket"), params.get("session_hash")
            if not isinstance(t, str) or not isinstance(h, str) or self.key is None:
                raise rpc.RpcError("refuse", "Ticket manquant.")
            expected = hmac.new(self.key, h.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, t):
                log.warning("ticket refusé")
                raise rpc.RpcError("refuse", "Ticket invalide.")
        conn.peer["ok"] = True
        self.last_activity = self.clock()
        return {"user": self.user}

    def _on_connect(self, conn):
        self.clients.add(conn)

    def _on_close(self, conn):
        self.clients.discard(conn)
        for hook in self.close_hooks:
            hook(conn)
        self.last_activity = self.clock()

    async def start(self, socket_path):
        self._server = rpc.RpcServer(self.handlers(), on_connect=self._on_connect,
                                     on_close=self._on_close)
        await self._server.start_unix(socket_path, 0o600 if self.local else 0o660)

    async def stop(self):
        self._stop.set()
        if self._server is not None:
            await self._server.close()
            self._server = None

    def should_stop(self):
        if self.clients or any(check() for check in self.busy_checks):
            return False
        return self.clock() - self.last_activity > IDLE_STOP

    async def serve(self, socket_path):
        await self.start(socket_path)
        log.info("pont de %s prêt sur %s", self.user, socket_path)
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=60)
            except asyncio.TimeoutError:
                for hook in self.tick_hooks:
                    try:
                        await hook()
                    except Exception:
                        log.exception("ménage du pont")
                if self.should_stop():
                    log.info("pont de %s arrêté : inactif depuis 12 h", self.user)
                    break
        await self.stop()

    async def broadcast(self, event, data):
        for conn in list(self.clients):
            if conn.peer.get("ok"):
                await conn.push(event, data)

    # ---- comptes et réglages ---------------------------------------------------------

    async def accounts_state(self, _conn, _params):
        def work():
            now = datetime.now(timezone.utc)
            st = pause.pause_state(now)
            return {
                "user": self.user,
                "profiles": [dataclasses.asdict(p) for p in core.list_profiles()],
                "active": core.active_profile_name(),
                "state": core.load_json(daemon.state_path()),
                "pause": None if st is None else {
                    "until": st.until.isoformat() if st.until else None,
                    "label": pause.label(st, now)},
                "pause_choices": pause.choices(now),
            }
        return await asyncio.to_thread(work)

    async def accounts_refresh(self, _conn, _params):
        def work():
            if not daemon.request_refresh():
                daemon.collect_once()
        await asyncio.to_thread(work)
        return {}

    async def accounts_switch(self, _conn, params):
        name = params.get("name")
        names = [p.name for p in await asyncio.to_thread(core.list_profiles)]
        if name not in names:
            raise rpc.RpcError("invalide", "Compte inconnu.")
        res = await asyncio.to_thread(core.run_ccs, ["switch", name])
        return {"ok": getattr(res, "returncode", 1) == 0}

    async def pause_set(self, _conn, params):
        choice = params.get("choice")
        if not isinstance(choice, str):
            raise rpc.RpcError("invalide", "Choix de pause manquant.")
        try:
            st = await asyncio.to_thread(pause.apply, choice)
        except (ValueError, KeyError):
            raise rpc.RpcError("invalide", "Choix de pause inconnu.") from None
        return {"paused": st is not None}

    async def settings_get(self, _conn, _params):
        return {"settings": await asyncio.to_thread(settings.load_settings)}

    async def settings_set(self, _conn, params):
        path, value = params.get("path"), params.get("value")
        keys = path.split(".") if isinstance(path, str) and path else []
        default = settings.DEFAULTS
        for k in keys:
            if not isinstance(default, dict) or k not in default:
                raise rpc.RpcError("invalide", f"Réglage inconnu : {path}")
            default = default[k]

        def work():
            s = copy.deepcopy(settings.load_settings())
            node = s
            for k in keys[:-1]:
                node = node.setdefault(k, {})
            node[keys[-1]] = value
            bad = []
            cleaned = settings._clean(s, settings.DEFAULTS, "", bad)
            if path in bad:
                return False
            settings.save_settings(cleaned)
            return True
        if not await asyncio.to_thread(work):
            raise rpc.RpcError("invalide", f"Valeur refusée pour {path}.")
        return {}
