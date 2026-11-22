"""Pont : terminaux shell pour la version web et le bureau distant.

Chaque terminal est un shell de connexion de l'utilisateur dans un pseudo-terminal (`setsid
-c` lui donne son terminal de contrôle, comme un vrai terminal). La sortie part en événements
`term.output` (texte UTF-8, morceaux d'au plus 64 Kio) aux appareils attachés ; les 64 derniers
Kio sont gardés pour celui qui se rattache. Un terminal sans appareil depuis 12 h est fermé.
Identifiants `t<boot>-<n>` : `boot` est tiré au hasard à chaque démarrage du pont.
"""

import asyncio
import codecs
import fcntl
import itertools
import os
import pwd
import re
import secrets
import signal
import struct
import subprocess
import termios
import time

from .. import core, limit_events, limit_resume, sessions, settings
from . import rpc
from .bridge_data import safe_path

CHUNK = 64 * 1024
KEEP = 64 * 1024
ABANDON = 12 * 3600
COMMANDS = ("ccs add",)
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def command_argv(command, name):
    if command not in COMMANDS:
        raise rpc.RpcError("refuse", "Commande non autorisée.")
    if not isinstance(name, str) or not _NAME.match(name):
        raise rpc.RpcError("invalide", "Nom de compte invalide (lettres, chiffres, - et _).")
    return [core.ccs_bin(), "add", name]


class _Term:
    def __init__(self, term_id, proc, master, cwd="", name="Terminal"):
        self.cwd = cwd
        self.name = name
        self.term_id = term_id
        self.proc = proc
        self.master = master
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.recent = ""
        self.conns = set()
        self.detached_at = None
        self.closed = False


class TermHub:
    def __init__(self, bridge, shell=None, clock=time.time):
        self.bridge = bridge
        self.shell = shell
        self.clock = clock
        self.terms = {}
        self.boot = secrets.token_hex(3)
        self._ids = itertools.count(1)
        bridge.close_hooks.append(self._forget)
        bridge.tick_hooks.append(self.sweep)
        bridge.tick_hooks.append(self.limits_pass)
        getattr(bridge, "restart_checks", []).append(lambda: any(not t.closed for t in self.terms.values()))
        self._resumes = {}           # session_id → instants des relances après une limite
        bridge.add_handlers({
            "term.open": self.open, "term.input": self.input, "term.resize": self.resize,
            "term.attach": self.attach, "term.list": self.list, "term.close": self.close,
        })

    def _shell(self):
        if self.shell:
            return self.shell
        try:
            return pwd.getpwuid(os.getuid()).pw_shell or "/bin/bash"
        except KeyError:
            return "/bin/bash"

    def _get(self, params):
        term = self.terms.get(params.get("term_id"))
        if term is None or term.closed:
            raise rpc.RpcError("introuvable", "Terminal inconnu ou fermé.")
        return term

    def _forget(self, conn):
        for term in self.terms.values():
            if conn in term.conns:
                term.conns.discard(conn)
                if not term.conns:
                    term.detached_at = self.clock()

    @staticmethod
    def _size(fd, cols, rows):
        cols = cols if isinstance(cols, int) and 0 < cols < 1000 else 80
        rows = rows if isinstance(rows, int) and 0 < rows < 1000 else 24
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    async def open(self, conn, params):
        cwd = params.get("cwd")
        if isinstance(cwd, str) and cwd.startswith("~"):
            cwd = os.path.normpath(os.path.expanduser(cwd))
        if not isinstance(cwd, str) or not os.path.isdir(cwd):
            raise rpc.RpcError("invalide", "Dossier introuvable.")
        safe_path(cwd)                       # dossier personnel ou dossiers de sites seulement
        if params.get("command") is not None:
            argv = command_argv(params.get("command"), params.get("name"))
        else:
            argv = [self._shell(), "-l"]
        master, slave = os.openpty()
        self._size(slave, params.get("cols"), params.get("rows"))
        env = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor")
        try:
            proc = subprocess.Popen(["setsid", "-c", *argv], stdin=slave, stdout=slave,
                                    stderr=slave, cwd=cwd, env=env, close_fds=True)
        except OSError:
            os.close(master)
            raise rpc.RpcError("interne", "Impossible de lancer le terminal.") from None
        finally:
            os.close(slave)
        os.set_blocking(master, False)
        name = params.get("name") if params.get("command") is not None else os.path.basename(cwd.rstrip("/"))
        term = _Term(f"t{self.boot}-{next(self._ids)}", proc, master, cwd, name or "Terminal")
        term.conns.add(conn)
        self.terms[term.term_id] = term
        asyncio.get_running_loop().add_reader(master, self._readable, term)
        return {"term_id": term.term_id}

    def _readable(self, term):
        try:
            data = os.read(term.master, CHUNK)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            asyncio.ensure_future(self._finish(term))
            return
        text = term.decoder.decode(data)
        if text:
            term.recent = (term.recent + text)[-KEEP:]
            for conn in list(term.conns):
                asyncio.ensure_future(conn.push("term.output", {"term_id": term.term_id, "data": text}))

    async def _finish(self, term):
        if term.closed:
            return
        term.closed = True
        loop = asyncio.get_running_loop()
        try:
            loop.remove_reader(term.master)
        except (ValueError, OSError):
            pass
        try:
            os.close(term.master)
        except OSError:
            pass
        code = await asyncio.to_thread(term.proc.wait)
        for conn in list(term.conns):
            await conn.push("term.exit", {"term_id": term.term_id, "code": code})
        self.terms.pop(term.term_id, None)

    async def input(self, _conn, params):
        term = self._get(params)
        data = params.get("data")
        if not isinstance(data, str):
            raise rpc.RpcError("invalide", "Saisie manquante.")
        raw = data.encode("utf-8")
        while raw:
            try:
                n = os.write(term.master, raw)
            except BlockingIOError:
                await asyncio.sleep(0.01)
                continue
            except OSError:
                raise rpc.RpcError("introuvable", "Terminal fermé.") from None
            raw = raw[n:]
        return {}

    async def resize(self, _conn, params):
        term = self._get(params)
        self._size(term.master, params.get("cols"), params.get("rows"))
        return {}

    async def attach(self, conn, params):
        term = self._get(params)
        term.conns.add(conn)
        term.detached_at = None
        return {"output": term.recent}

    async def list(self, _conn, _params):
        return {"terms": [{"term_id": t.term_id, "cwd": t.cwd, "name": t.name} for t in self.terms.values() if not t.closed]}

    async def close(self, _conn, params):
        await self._kill(self._get(params))
        return {}

    async def _kill(self, term):
        try:
            os.killpg(term.proc.pid, signal.SIGHUP)
        except (ProcessLookupError, PermissionError):
            pass
        await self._finish(term)

    async def sweep(self):
        now = self.clock()
        for term in list(self.terms.values()):
            if not term.conns and term.detached_at is not None and now - term.detached_at > ABANDON:
                await self._kill(term)

    async def limits_pass(self):
        """Claude lancé à la main dans un de ces terminaux et bloqué par une limite : « continue »
        quand le compte a changé ou que la limite est levée (`limit_resume`)."""
        terms = {t.term_id: t for t in self.terms.values() if not t.closed}
        if not terms:
            return

        def work():
            marks = limit_events.load_all()
            if not any(e.outcome in limit_events.RESUMABLE for e in marks.values()):
                return []
            try:
                enabled = limit_resume.config(settings.load_settings())["enabled"]
            except Exception:
                enabled = True
            return limit_resume.terminal_resumes(marks, sessions.list_sessions(),
                                                 {k: t.proc.pid for k, t in terms.items()},
                                                 time.time(), self._resumes, enabled)
        for key, _sid in await asyncio.to_thread(work):
            try:
                os.write(terms[key].master, (limit_resume.TEXT + "\r").encode())
            except OSError:
                pass

    async def close_all(self):
        for term in list(self.terms.values()):
            await self._kill(term)
