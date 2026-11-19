"""Les autres machines de Charles depuis le pont : leur liste (relais Ricochet) et le relais d'une
connexion vers le pont CCS de l'une d'elles.

`machine.attach` ouvre `ssh` par le tunnel Ricochet (options de `distant`) et y lance un petit
programme Python qui branche l'entrée et la sortie de `ssh` sur le pont local de la machine
(`ccs bridge --local`, lancé s'il ne tourne pas : c'est celui de l'application de bureau, les
chats sont donc partagés avec elle). Ensuite, tout ce que la connexion demande part là-bas, sauf
`hello`, `machine.attach` et `machines.*` (voir `Bridge.keeps_local`) ; les événements de là-bas
reviennent sur la connexion. Si le lien tombe, la connexion est fermée : le web se reconnecte.
"""

import asyncio
import logging
import re
import shlex
from pathlib import Path

from .. import core, distant, distant_jobs
from . import rpc

log = logging.getLogger("ccs.bridge.machines")

MACHINE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
HELLO_TIMEOUT = 45

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
        self._fetch = fetch or distant.fetch_machines
        self._spawn = spawn or self._ssh
        self.links = {}                       # connexion → Link
        bridge.close_hooks.append(self._forget)
        bridge.busy_checks.append(lambda: bool(self.links))
        bridge.add_handlers({
            "machines.list": self.list, "machine.attach": self.attach,
            "machines.jobs": self.jobs, "machines.stop": self.stop, "machines.log": self.log,
            "machines.start": self.start, "machines.settings": self.settings,
            "machines.configure": self.configure, "machines.limit": self.limit})

    async def _machines(self):
        if not distant.configured():
            raise rpc.RpcError("introuvable", "Calcul réparti non réglé sur ce serveur "
                               "(~/.config/ricochet/client.toml).")
        try:
            return await asyncio.to_thread(self._fetch)
        except distant.DistantError as e:
            raise rpc.RpcError("introuvable", str(e)) from None

    async def list(self, _conn, _params):
        return await asyncio.to_thread(distant.machines_overview, self._fetch)

    async def jobs(self, _conn, _params):
        return {"jobs": await asyncio.to_thread(distant_jobs.list_jobs)}

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
        relais, jeton = params.get("relais"), params.get("jeton")
        for v in (relais, jeton):
            if v is not None and not isinstance(v, str):
                raise rpc.RpcError("invalide", "Réglage invalide.")
        try:
            await asyncio.to_thread(distant.save_client, relais=relais, jeton=jeton)
        except distant.DistantError as e:
            raise rpc.RpcError("invalide", str(e)) from None
        except OSError as e:
            raise rpc.RpcError("interne", f"Écriture impossible : {e.strerror or e}") from None
        return {"ok": True}

    async def limit(self, _conn, params):
        try:
            await asyncio.to_thread(distant.set_limit, params.get("machine"), params.get("limite"))
        except distant.DistantError as e:
            raise rpc.RpcError("invalide", str(e)) from None
        except OSError as e:
            raise rpc.RpcError("interne", f"Écriture impossible : {e.strerror or e}") from None
        return {"ok": True}

    @staticmethod
    async def _ssh(machine):
        overrides = await asyncio.to_thread(distant.load_overrides)
        argv = ["ssh", *distant.ssh_options(machine, overrides), distant.target(machine, overrides),
                remote_command()]
        return await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=rpc.MAX_LINE + 1)

    async def attach(self, conn, params):
        mid = params.get("machine")
        if not isinstance(mid, str) or not MACHINE_ID.match(mid):
            raise rpc.RpcError("invalide", "Machine invalide.")
        if conn in self.links:
            raise rpc.RpcError("conflit", "Connexion déjà relayée.")
        machine = next((m for m in await self._machines() if m.id == mid), None)
        if machine is None:
            raise rpc.RpcError("introuvable", f"{mid} : machine inconnue du relais Ricochet.")
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
            await asyncio.wait_for(client.call("hello"), HELLO_TIMEOUT)
        except (rpc.RpcError, asyncio.TimeoutError, ConnectionError) as e:
            why = await self._why(proc) or (str(e) if isinstance(e, rpc.RpcError) else "délai dépassé")
            await link.close()
            log.warning("relais vers %s refusé : %s", mid, why)
            raise rpc.RpcError("introuvable", f"{mid} injoignable : {why}") from None
        if conn.closed:
            await link.close()
            raise rpc.RpcError("interne", "Connexion fermée.")

        def on_event(name, data):
            if not conn.closed:
                asyncio.ensure_future(conn.push(name, data))
        client.on_event = on_event

        async def forward(method, p):
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
        return {"machine": mid, "name": machine.name or mid}

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
