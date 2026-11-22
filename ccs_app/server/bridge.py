"""Pont CCS d'un utilisateur : tourne sous lui (service `ccs-bridge@<utilisateur>`, ou
`ccs bridge --local` pour `ccs tui` sur la machine même) et fait pour le web, le terminal et
le bureau ce que l'application GTK fait en local : comptes, chats, fichiers, feuille de route…

Toute connexion commence par `hello` : le ticket remis par `ccs-auth` (HMAC de l'empreinte de
la session par la clé du pont) est vérifié ; en mode local, le socket est en 0600 dans le
dossier de l'utilisateur et `hello` suffit. `hello {protocol}` déclare la version du protocole que
le client connaît (absente : ancien client) ; la réponse donne celle du pont et la version de CCS.
Les anciens noms de méthode et de paramètre sont acceptés (`protocol.py`).

Mise à jour de CCS : un pont local (`--local`) relit chaque minute la version installée ; si elle
a changé et qu'aucun travail ne tourne (chat au travail, relais, limite attendue, terminal ou
commande `!` du pont), il ferme ses
chats (les conversations sont enregistrées) et se relance sur le nouveau code (`restart`, repris
par `ccs bridge`). Les appareils se reconnectent seuls et rouvrent leurs conversations. Le service
`ccs-bridge@` du serveur, lui, est relancé par le postinst du paquet `ccs-serveur`.
"""

import asyncio
import copy
import dataclasses
import hashlib
import hmac
import logging
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone

from .. import __version__, account_colors, claude_install, core, daemon, pause, settings
from . import protocol, rpc

log = logging.getLogger("ccs.bridge")

IDLE_STOP = 12 * 3600
_VERSION_LINE = re.compile(r"""^__version__\s*=\s*["']([^"']+)["']""", re.M)


def installed_version(path=None):
    """Version de CCS écrite sur le disque (celle qu'un nouveau processus chargerait), ou None."""
    path = path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "__init__.py")
    try:
        with open(path, encoding="utf-8") as f:
            m = _VERSION_LINE.search(f.read(4096))
    except OSError:
        return None
    return m.group(1) if m else None


class Bridge:
    def __init__(self, user, key, local=False, clock=time.time, start_daemon=True,
                 install_claude=True, popen=subprocess.Popen, daemon_pid=None, installer=None,
                 version_on_disk=installed_version):
        self.user = user
        self.key = key
        self.local = local
        self.clock = clock
        self.start_daemon = start_daemon
        self.install_claude = install_claude
        self._popen = popen
        self._daemon_pid = daemon_pid or daemon.running_pid
        self._installer = installer or claude_install
        self._daemon_proc = None
        self.clients = set()
        self.busy_checks = []        # fonctions qui disent « un travail est en cours »
        self.close_hooks = []        # appelées à la fermeture d'une connexion
        self.tick_hooks = []         # coroutines appelées chaque minute (ménage)
        self.stop_hooks = []         # coroutines appelées à l'arrêt du pont (chats fermés)
        self.restart_checks = []     # « on perdrait ceci à une relance » (terminaux, commandes)
        self._version_on_disk = version_on_disk
        self.restart = False         # arrêté pour se relancer sur le code mis à jour
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
        conn.peer["protocol"] = protocol.client_protocol(params.get("protocol"))
        self.last_activity = self.clock()
        return {"user": self.user, "protocol": protocol.PROTOCOL, "version": __version__}

    @staticmethod
    def keeps_local(method):
        """Sur une connexion relayée vers une autre machine, ce qui reste traité ici (noms déjà
        ramenés aux nouveaux par `protocol.normalize`)."""
        return method == "hello" or method.startswith("machines.")

    def _on_connect(self, conn):
        self.clients.add(conn)

    def _on_close(self, conn):
        self.clients.discard(conn)
        for hook in self.close_hooks:
            hook(conn)
        self.last_activity = self.clock()

    async def start(self, socket_path):
        self._server = rpc.RpcServer(self.handlers(), on_connect=self._on_connect,
                                     on_close=self._on_close, keep_local=self.keeps_local,
                                     normalize=protocol.normalize,
                                     downgrade=protocol.downgrade_result)
        await self._server.start_unix(socket_path, 0o600 if self.local else 0o660)

    async def prepare(self):
        """Sans session graphique (VPS), personne ne lance le service `ccs-daemon` : le pont le
        lance s'il ne tourne pas. Claude Code est installé s'il manque."""
        await asyncio.to_thread(remove_old_cache)
        if self.start_daemon and await asyncio.to_thread(self._daemon_pid) is None:
            try:
                self._daemon_proc = self._popen([core.ccs_bin(), "daemon"],
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                start_new_session=True)
                log.info("service de fond lancé par le pont")
            except OSError:
                log.warning("service de fond impossible à lancer")
        if self.install_claude and not await asyncio.to_thread(self._installer.installed):
            asyncio.ensure_future(self._install_claude())

    async def _install_claude(self):
        await self.broadcast("notice", {"text": "Installation de Claude Code en cours…"})
        ok, text = await asyncio.to_thread(self._installer.install)
        await self.broadcast("notice", {"text": "Claude Code installé." if ok else
                                        f"Claude Code n'a pas pu s'installer : {text}"})

    async def stop(self):
        self._stop.set()
        for hook in self.stop_hooks:
            try:
                await hook()
            except Exception:
                log.exception("arrêt du pont")
        if self._daemon_proc is not None:
            if self._daemon_proc.poll() is None:
                self._daemon_proc.terminate()
                await asyncio.to_thread(self._daemon_proc.wait, 10)
            self._daemon_proc = None
        if self._server is not None:
            await self._server.close()
            self._server = None

    def should_stop(self):
        if self.clients or any(check() for check in self.busy_checks):
            return False
        return self.clock() - self.last_activity > IDLE_STOP

    def should_restart(self):
        """Pont local dont CCS a été mis à jour (version sur le disque différente de celle chargée)
        et qui ne fait rien qu'on perdrait : il peut se relancer sur le nouveau code."""
        if not self.local or any(check() for check in self.busy_checks + self.restart_checks):
            return False
        found = self._version_on_disk()
        return bool(found) and found != __version__

    async def serve(self, socket_path):
        await self.start(socket_path)
        await self.prepare()
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
                if self.should_restart():
                    log.info("pont de %s relancé : CCS mis à jour (%s → %s)", self.user, __version__,
                             self._version_on_disk())
                    self.restart = True
                    break
                if self.should_stop():
                    log.info("pont de %s arrêté : inactif depuis 12 h", self.user)
                    break
        await self.stop()

    async def broadcast(self, event, data):
        for conn in list(self.clients):
            if conn.peer.get("ok"):
                # anciennes valeurs pour un ancien client : compatibilité 1.x, à retirer en 2.0
                await conn.push(event, protocol.event_data(conn, event, data))

    # ---- comptes et réglages ---------------------------------------------------------

    async def accounts_state(self, _conn, _params):
        def work():
            now = datetime.now(timezone.utc)
            st = pause.pause_state(now)
            profiles = core.list_profiles()
            names = [p.name for p in profiles]
            chosen = settings.load_settings().get("appearance", {}).get("account_colors") or {}
            return {
                "user": self.user,
                "home": os.path.expanduser("~"),
                "colors": {n: account_colors.color_for(n, names, chosen) for n in names},
                "profiles": [dataclasses.asdict(p) for p in profiles],
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


def remove_old_cache():
    """Retire une fois l'ancien dossier `~/.cache/ccs/distant-en-cours/` (abandonné en 0.32.0)."""
    old = core.ccs_dir("cache") / "distant-en-cours"
    if old.is_dir() and not old.is_symlink():
        shutil.rmtree(old, ignore_errors=True)


def build(user, key, local=False, chat=None, **kwargs):
    """Pont complet, tel que le lance `ccs bridge` : comptes et réglages, chats, données
    (projets, fichiers, feuille de route, tâches, analyse) et terminaux. `chat` : options du
    moteur de chat (`claude`, `environ`), pour le banc d'essai."""
    from . import (bridge_admin, bridge_chat, bridge_data, bridge_files, bridge_git,
                   bridge_machines, bridge_term, bridge_work)
    b = Bridge(user, key, local=local, **kwargs)
    b.hubs = {"chat": bridge_chat.ChatHub(b, **(chat or {})), "data": bridge_data.DataApi(b),
              "term": bridge_term.TermHub(b), "work": bridge_work.WorkApi(b),
              "admin": bridge_admin.AdminApi(b), "git": bridge_git.GitApi(b),
              "files": bridge_files.FileOps(b), "machines": bridge_machines.MachinesApi(b)}
    return b
