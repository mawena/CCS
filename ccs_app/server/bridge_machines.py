"""Les autres machines de Charles depuis le pont : leur liste (relais Ricochet) et le relais d'une
connexion vers le pont CCS de l'une d'elles.

`machines.attach` ouvre `ssh` par le tunnel Ricochet (options de `distant`) et y lance un petit
programme Python qui branche l'entrée et la sortie de `ssh` sur le pont local de la machine
(`ccs bridge --local`, lancé s'il ne tourne pas : c'est celui de l'application de bureau, les
chats sont donc partagés avec elle). Ensuite, tout ce que la connexion demande part là-bas, sauf
`hello` et `machines.*` (voir `Bridge.keeps_local`) ; les événements de là-bas reviennent sur la
connexion. Une fois le lien prêt, le pont pousse lui-même l'événement `machines.ready` sur la
connexion. Si le lien tombe, la connexion est fermée : le web se reconnecte. Un pont distant plus
ancien (son `hello` ne donne pas `protocol`) reçoit les anciens noms (`protocol.to_legacy`).
"""

import asyncio
import logging
import re
import shlex
from pathlib import Path

from .. import core, distant, distant_jobs
from . import protocol, rpc

log = logging.getLogger("ccs.bridge.machines")

MACHINE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
HELLO_TIMEOUT = 45
CHATS_TIMEOUT = 20      # par machine, pour la vue « toutes les machines »

# Exécuté sur l'autre machine (python3 suffit, quelle que soit la version de CCS installée).
REMOTE = r'''
import os, shutil, socket, subprocess, sys, threading, time
base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp/ccs-%d" % os.getuid()
path = os.path.join(base, "ccs", "bridge.sock")
def connect():
    s = socket.socket(socket.AF_UNIX)
    s.connect(path)
    return s
try:
    s = connect()
except OSError:
    ccs = shutil.which("ccs") or shutil.which("claude-accounts")
    if not ccs:
        sys.exit("CCS n'est pas installé sur cette machine")
    subprocess.Popen([ccs, "bridge", "--local"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(200):
        time.sleep(0.1)
        try:
            s = connect()
            break
        except OSError:
            pass
    else:
        sys.exit("le pont local de CCS ne démarre pas")
def up():
    while True:
        b = os.read(0, 65536)
        if not b:
            break
        s.sendall(b)
    try:
        s.shutdown(socket.SHUT_WR)
    except OSError:
        pass
threading.Thread(target=up, daemon=True).start()
out = sys.stdout.buffer
while True:
    b = s.recv(65536)
    if not b:
        break
    out.write(b)
    out.flush()
'''


def remote_command():
    return "exec python3 -c " + shlex.quote(REMOTE)


def public(m):
    return distant._public(m)


def _job_id(params):
    jid = params.get("id")
    if not isinstance(jid, str) or not distant_jobs.ID_RE.match(jid):
        raise rpc.RpcError("invalide", "Travail invalide.")
    return jid


class Link:
    """Lien d'une connexion du pont vers le pont d'une autre machine."""

    def __init__(self, machine_id, proc, client):
        self.machine = machine_id
        self.proc = proc
        self.client = client
        self.watch = None

    async def close(self):
        if self.watch is not None:
            self.watch.cancel()
        await self.client.close()
        if self.proc.returncode is None:
            try:
                self.proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.proc.wait(), 5)
            except asyncio.TimeoutError:
                self.proc.kill()


class MachinesApi:
    def __init__(self, bridge, fetch=None, spawn=None):
        self.bridge = bridge
        self._fetch = fetch or distant.list_machines
        self._spawn = spawn or self._ssh
        self.links = {}                       # connexion → Link
        bridge.close_hooks.append(self._forget)
        bridge.busy_checks.append(lambda: bool(self.links))
        bridge.add_handlers({
            "machines.list": self.list, "machines.attach": self.attach,
            "machines.chats": self.chats,
            "machines.jobs": self.jobs, "machines.stop": self.stop, "machines.log": self.log,
            "machines.start": self.start, "machines.settings": self.settings,
            "machines.configure": self.configure, "machines.limit": self.limit,
            "machines.add": self.add})

    async def _machines(self):
        if not distant.available():
            raise rpc.RpcError("introuvable", "Calcul réparti non réglé sur ce serveur "
                               "(~/.config/ricochet/client.toml).")
        try:
            return await asyncio.to_thread(self._fetch)
        except distant.DistantError as e:
            raise rpc.RpcError("introuvable", str(e)) from None

    async def list(self, _conn, _params):
        return await asyncio.to_thread(distant.machines_overview, self._fetch)

    async def jobs(self, conn, _params):
        jobs = await asyncio.to_thread(distant_jobs.list_jobs)
        if protocol.legacy(conn):
            # anciens états français pour les applis déjà installées : compatibilité 1.x, à retirer en 2.0
            jobs = [distant_jobs.legacy_view(j) for j in jobs]
        return {"jobs": jobs}

    async def stop(self, _conn, params):
        jid = _job_id(params)
        if not await asyncio.to_thread(distant_jobs.stop, jid):
            raise rpc.RpcError("introuvable", "Travail introuvable ou déjà fini.")
        return {"ok": True}

    async def log(self, _conn, params):
        jid = _job_id(params)
        tail = params.get("tail", 20000)
        if isinstance(tail, bool) or not isinstance(tail, int) or tail < 0:
            raise rpc.RpcError("invalide", "Longueur de journal invalide.")
        if await asyncio.to_thread(distant_jobs.get, jid) is None:
            raise rpc.RpcError("introuvable", "Travail introuvable.")
        return {"text": await asyncio.to_thread(distant_jobs.read_log, jid, min(tail, 1_000_000))}

    async def start(self, _conn, params):
        line = params.get("command")
        if not isinstance(line, str) or not line.strip():
            raise rpc.RpcError("invalide", "Commande vide.")
        try:
            shlex.split(line)  # vérification seulement : la ligne part entière au shell
        except ValueError as e:
            raise rpc.RpcError("invalide", f"Commande mal écrite : {e}.") from None
        command = [line.strip()]
        cwd = params.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            raise rpc.RpcError("invalide", "Dossier manquant.")
        home = core.paths().home.resolve()
        folder = Path(cwd).expanduser().resolve()
        if not folder.is_relative_to(home):
            raise rpc.RpcError("refuse", "Le dossier doit être dans le dossier personnel.")
        if not folder.is_dir():
            raise rpc.RpcError("introuvable", f"Dossier introuvable : {cwd}")
        machine = params.get("machine") or None
        if machine is not None and (not isinstance(machine, str) or not MACHINE_ID.match(machine)):
            raise rpc.RpcError("invalide", "Machine invalide.")
        when = params.get("when") or ""
        if not isinstance(when, str) or (when not in ("", "nuit") and not distant.WHEN_RE.match(when)):
            raise rpc.RpcError("invalide", "Heure de départ invalide : « nuit » ou HH:MM.")
        try:
            jid = await asyncio.to_thread(distant_jobs.start, command, str(folder),
                                          machine=machine, when=when)
        except distant.DistantError as e:
            raise rpc.RpcError("interne", str(e)) from None
        return {"id": jid}

    async def settings(self, _conn, _params):
        return await asyncio.to_thread(distant.client_settings)

    async def configure(self, _conn, params):
        relay, token = params.get("relay"), params.get("token")
        for v in (relay, token):
            if v is not None and not isinstance(v, str):
                raise rpc.RpcError("invalide", "Réglage invalide.")
        try:
            await asyncio.to_thread(distant.save_client, relay=relay, token=token)
        except distant.DistantError as e:
            raise rpc.RpcError("invalide", str(e)) from None
        except OSError as e:
            raise rpc.RpcError("interne", f"Écriture impossible : {e.strerror or e}") from None
        return {"ok": True}

    async def limit(self, _conn, params):
        try:
            await asyncio.to_thread(distant.set_limit, params.get("machine"), params.get("limit"))
        except distant.DistantError as e:
            raise rpc.RpcError("invalide", str(e)) from None
        except OSError as e:
            raise rpc.RpcError("interne", f"Écriture impossible : {e.strerror or e}") from None
        return {"ok": True}

    async def add(self, _conn, params):
        """Déclare une machine dans Ricochet : renvoie la commande à coller sur elle."""
        mid, name, user, limit = (params.get(k) for k in ("machine", "name", "user", "limit"))
        full = params.get("full", False)
        for v in (mid, name, user):
            if v is not None and not isinstance(v, str):
                raise rpc.RpcError("invalide", "Paramètre invalide.")
        if not isinstance(full, bool):
            raise rpc.RpcError("invalide", "Paramètre invalide.")
        try:
            return await asyncio.to_thread(distant.add_machine, mid, name=name, user=user, limit=limit,
                                           full=full)
        except distant.DistantError as e:
            raise rpc.RpcError("invalide", str(e)) from None
        except OSError as e:
            raise rpc.RpcError("interne", f"Écriture impossible : {e.strerror or e}") from None

    @staticmethod
    async def _ssh(machine):
        overrides = await asyncio.to_thread(distant.load_overrides)
        argv = ["ssh", *distant.ssh_options(machine, overrides), distant.target(machine, overrides),
                remote_command()]
        return await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=rpc.MAX_LINE + 1)

    async def connect(self, mid, timeout=HELLO_TIMEOUT):
        """Lien vers le pont CCS de la machine `mid` (ssh, puis `hello`) → (machine, Link,
        réponse de `hello`). Lève `RpcError` si la machine est inconnue, ce serveur, hors ligne
        ou injoignable. Sert au relais (`attach`) et à Jarvis (`bridge_pilot`)."""
        machine = next((m for m in await self._machines() if distant.same_machine(m.id, mid)), None)
        if machine is None:
            raise rpc.RpcError("introuvable", f"{mid} : machine inconnue (Ricochet et réseau maillé).")
        if machine.local:
            raise rpc.RpcError("invalide", f"{mid} est ce serveur.")
        if not machine.online:
            raise rpc.RpcError("introuvable", f"{mid} est hors ligne.")
        try:
            proc = await self._spawn(machine)
        except distant.DistantError as e:
            raise rpc.RpcError("introuvable", str(e)) from None
        except OSError as e:
            raise rpc.RpcError("interne", f"ssh impossible à lancer : {e}") from None
        client = rpc.RpcClient()
        client.attach(proc.stdout, proc.stdin)
        link = Link(mid, proc, client)
        try:
            remote = await asyncio.wait_for(client.call("hello", protocol=protocol.PROTOCOL), timeout)
        except (rpc.RpcError, asyncio.TimeoutError, ConnectionError) as e:
            why = await self._why(proc) or (str(e) if isinstance(e, rpc.RpcError) else "délai dépassé")
            await link.close()
            log.warning("relais vers %s refusé : %s", mid, why)
            raise rpc.RpcError("introuvable", f"{mid} injoignable : {why}") from None
        return machine, link, remote

    async def chats(self, _conn, _params):
        """Sessions des autres machines en ligne, pour une liste unique côté client :
        `{"machines": [{"id", "name", "chats": [...]} ou {..., "error": "..."}]}`. Les sessions
        de ce serveur restent celles de `chat.list`. Une machine en panne n'empêche pas les autres."""
        try:
            machines = await self._machines()
        except rpc.RpcError:
            return {"machines": []}
        far = [m for m in machines if m.online and not m.local]

        async def one(m):
            out = {"id": m.id, "name": m.name or m.id}
            link = None
            try:
                _machine, link, remote = await self.connect(m.id, CHATS_TIMEOUT)
                if not (isinstance(remote, dict) and remote.get("protocol")):
                    name, p = protocol.to_legacy("chat.list", {})
                    r = protocol.upgrade_result("chat.list", await link.client.call(name, **p))
                else:
                    r = await asyncio.wait_for(link.client.call("chat.list"), CHATS_TIMEOUT)
                out["chats"] = list((r or {}).get("chats") or [])
            except rpc.RpcError as e:
                out["error"] = e.message
            except (asyncio.TimeoutError, ConnectionError, OSError) as e:
                out["error"] = f"{m.id} injoignable : {e or 'délai dépassé'}"
            finally:
                if link is not None:
                    await link.close()
            return out
        return {"machines": list(await asyncio.gather(*(one(m) for m in far)))}

    async def attach(self, conn, params):
        mid = params.get("machine")
        if not isinstance(mid, str) or not MACHINE_ID.match(mid):
            raise rpc.RpcError("invalide", "Machine invalide.")
        if conn in self.links:
            raise rpc.RpcError("conflit", "Connexion déjà relayée.")
        machine, link, remote = await self.connect(mid)
        client = link.client
        if conn.closed:
            await link.close()
            raise rpc.RpcError("interne", "Connexion fermée.")

        old_remote = not (isinstance(remote, dict) and remote.get("protocol"))

        def on_event(name, data):
            if not conn.closed:
                # noms et valeurs : compatibilité 1.x, à retirer en 2.0
                if old_remote:
                    data = protocol.upgrade_event(name, data)
                name = protocol.event_for(conn, name)
                data = protocol.event_data(conn, protocol.EVENT_ALIASES.get(name, name), data)
                asyncio.ensure_future(conn.push(name, data))
        client.on_event = on_event

        async def forward(method, p):
            if old_remote:          # pont d'avant la 1.0.0 : compatibilité 1.x, à retirer en 2.0
                name, p = protocol.to_legacy(method, p)
                return protocol.upgrade_result(method, await client.call(name, **p))
            return await client.call(method, **p)

        async def watch():
            await client.wait_closed()
            log.info("relais vers %s coupé", mid)
            conn.close()                      # le web voit le pont tomber et se reconnecte
        self.links[conn] = link
        conn.peer["forward"] = forward
        conn.peer["machine"] = mid
        link.watch = asyncio.ensure_future(watch())
        log.info("connexion relayée vers %s", mid)
        ready = {"machine": mid, "name": machine.name or mid}
        # `machine.ready` pour un ancien client : compatibilité 1.x, à retirer en 2.0
        await conn.push(protocol.event_for(conn, "machines.ready"), ready)
        return ready

    @staticmethod
    async def _why(proc):
        """Dernière ligne d'erreur de ssh ou du programme distant, si le processus est fini."""
        try:
            await asyncio.wait_for(proc.wait(), 2)
            err = (await asyncio.wait_for(proc.stderr.read(), 2)).decode("utf-8", "replace")
        except (asyncio.TimeoutError, AttributeError):
            return ""
        lines = [x.strip() for x in err.strip().splitlines() if x.strip()]
        return lines[-1][:300] if lines else ""

    def _forget(self, conn):
        link = self.links.pop(conn, None)
        if link is not None:
            asyncio.ensure_future(link.close())
