"""Gardien du mot de passe root (phase 34) : `sudo` sans être bloqué, le mot de passe venant des
appareils de Charles.

Le gardien vit dans le pont de la machine (`ccs bridge`, local ou service). Il tient le mot de passe
**en mémoire seulement** (`Secret`, un `bytearray` remis à zéro à l'expiration, à la révocation et à
l'arrêt), pendant une heure au plus (`KEEP_S`, expiration absolue, jamais prolongée). Le mot de passe
n'est jamais écrit sur disque, dans un journal, dans un message d'erreur ni dans une exception.

Il répond sur un socket Unix, `$XDG_RUNTIME_DIR/ccs/root.sock` (dossier 0700, socket 0600), et
seulement au même utilisateur (uid du pair lu par SO_PEERCRED). Une requête est une ligne JSON :
    {"op": "ask", "command": "..."}   → un octet b"1" suivi du mot de passe, ou b"0" (refus, délai)
    {"op": "status"}                  → ligne JSON (gardé ou non, temps restant ; jamais le secret)
    {"op": "forget"}                  → ligne JSON {"ok": true, "had": bool}
    {"op": "answer", "id", "password"|"cancel"} → ligne JSON (réponse relayée par un autre pont)
    {"op": "watch"}                   → une ligne JSON {"event", "data"} par événement, sans fin

Sans mot de passe gardé, `ask` ouvre une demande (`root.ask`) : les appareils la voient, le premier
qui répond juste gagne (`answer`, mot de passe vérifié par `sudo -k -S -v`, trois essais au plus),
`root.resolved` ferme les autres fenêtres. Une seule demande à la fois : les `ask` suivants attendent
la même. Sans réponse, abandon après `ASK_TIMEOUT_S`.

`ccs-askpass` (appelé par sudo comme `SUDO_ASKPASS`) et `ccs root` sont les clients (`askpass_main`,
`command`). Le mot de passe reçu par le pont dans `root.answer` arrive dans une chaîne JSON : cette
copie-là (immuable en Python) ne peut pas être effacée ; elle est convertie en `Secret` tout de
suite et n'est gardée nulle part.
"""

import asyncio
import json
import logging
import os
import secrets
import shlex
import shutil
import socket
import stat
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger("ccs.root")

KEEP_S = 3600            # durée de vie du mot de passe gardé (absolue)
ASK_TIMEOUT_S = 300      # demande sans réponse : abandonnée
MAX_TRIES = 3            # mauvais mots de passe acceptés par demande
VERIFY_TIMEOUT_S = 30
MAX_COMMAND = 500        # longueur gardée de la commande affichée
MAX_PASSWORD = 1024
MAX_REQUEST = 64 * 1024
SPAWN_WAIT_S = 20        # attente du pont lancé par `ccs root` ou `ccs-askpass`
UNKNOWN_COMMAND = "(commande inconnue)"


class KeeperError(Exception):
    """Refus du gardien : `code` (codes du pont : introuvable, invalide, conflit…) et message.
    Jamais de secret dedans."""

    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f"{code} : {message}")


class AlreadyServed(Exception):
    """Un autre pont de cet utilisateur tient déjà le socket du gardien."""


# --------------------------------------------------------------------------
# Secret
# --------------------------------------------------------------------------

class Secret:
    """Mot de passe en mémoire : un `bytearray` (modifiable, donc effaçable). Ne s'affiche jamais."""

    __slots__ = ("_buf",)

    def __init__(self, data=b""):
        self._buf = bytearray(data)       # copie : l'appelant efface la sienne

    def view(self):
        return memoryview(self._buf)

    def copy(self):
        return Secret(self._buf)

    def wipe(self):
        for i in range(len(self._buf)):
            self._buf[i] = 0
        try:
            self._buf.clear()
        except BufferError:               # encore vu par un tampon : déjà remis à zéro
            pass

    def __len__(self):
        return len(self._buf)

    def __bool__(self):
        return bool(self._buf)

    def __repr__(self):
        return "<Secret masqué>"

    __str__ = __repr__

    def __reduce__(self):                  # jamais copié par pickle (ni sur disque)
        raise TypeError("un Secret ne se sérialise pas")


def to_secret(value):
    """`Secret` d'un mot de passe reçu (chaîne ou octets) ; KeeperError s'il est vide, trop long ou
    contient un retour à la ligne (sudo -S lit une seule ligne)."""
    if isinstance(value, str):
        buf = bytearray(value, "utf-8")
    elif isinstance(value, (bytes, bytearray, memoryview)):
        buf = bytearray(value)
    else:
        raise KeeperError("invalide", "Mot de passe manquant.")
    try:
        if not buf:
            raise KeeperError("invalide", "Mot de passe manquant.")
        if len(buf) > MAX_PASSWORD or b"\n" in buf or b"\r" in buf or b"\0" in buf:
            raise KeeperError("invalide", "Mot de passe illisible.")
        return Secret(buf)
    finally:
        for i in range(len(buf)):
            buf[i] = 0


def clean_command(command):
    """Commande affichée aux appareils : une ligne, `MAX_COMMAND` caractères au plus."""
    text = " ".join(str(command or "").split())
    if not text:
        return UNKNOWN_COMMAND
    return text if len(text) <= MAX_COMMAND else text[:MAX_COMMAND - 1] + "…"


def machine_name():
    return socket.gethostname().split(".")[0] or "machine"


def ricochet_id(fetch=None):
    """Identifiant Ricochet de cette machine (`srv-mawena-cloud`, `lp-work`…), celui que les
    applis connaissent par `machines.list` ; None sans Ricochet ou relais injoignable."""
    try:
        from . import distant
        machines = (fetch or distant.list_machines)()
    except Exception:  # noqa: BLE001 — pas de Ricochet : on garde le nom d'hôte
        return None
    return next((m.id for m in machines if m.local), None)


# --------------------------------------------------------------------------
# Vérification par sudo
# --------------------------------------------------------------------------

def verify_password(secret, popen=subprocess.Popen, timeout=VERIFY_TIMEOUT_S):
    """Vrai si `secret` est le mot de passe sudo de l'utilisateur : `sudo -k -S -v`, le mot de
    passe sur l'entrée standard (jamais en argument), sans terminal, sortie jetée."""
    env = {k: v for k, v in os.environ.items() if k != "SUDO_ASKPASS"}
    env["LC_ALL"] = "C"
    try:
        proc = popen(["sudo", "-k", "-S", "-p", "", "-v"], stdin=subprocess.PIPE,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
                     close_fds=True, start_new_session=True)
    except OSError:
        log.warning("root : sudo introuvable, vérification impossible")
        return False
    try:
        proc.stdin.write(secret.view())
        proc.stdin.write(b"\n")
        proc.stdin.close()
    except OSError:
        pass
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        log.warning("root : sudo ne répond pas, vérification abandonnée")
        return False
    return code == 0


# --------------------------------------------------------------------------
# Gardien
# --------------------------------------------------------------------------

class _Request:
    def __init__(self, rid, command, expires_at, future):
        self.id = rid
        self.command = command
        self.expires_at = expires_at
        self.future = future
        self.tries = 0
        self.verifying = False
        self.timer = None


class Keeper:
    """Mot de passe gardé et demande en cours. À utiliser dans la boucle asyncio du pont.
    `listeners` : fonctions `(événement, données)` appelées pour chaque événement (`root.ask`,
    `root.resolved`, `root.used`, `root.forgotten`) ; elles peuvent rendre une coroutine."""

    def __init__(self, machine=None, clock=time.time, verify=verify_password, keep_s=KEEP_S,
                 ask_timeout=ASK_TIMEOUT_S, max_tries=MAX_TRIES, vault=None):
        self.machine = machine or machine_name()
        if machine is None:
            # Le nom Ricochet est cherché à part (appel réseau) ; le nom d'hôte sert en attendant.
            def resolve():
                rid = ricochet_id()
                if rid:
                    self.machine = rid
            threading.Thread(target=resolve, name="ccs-root-nom", daemon=True).start()
        self.clock = clock
        self.verify = verify
        self.keep_s = keep_s
        self.ask_timeout = ask_timeout
        self.max_tries = max_tries
        self.listeners = []
        self._secret = None
        self._expires_at = 0.0
        self._expiry = None
        self._request = None
        # Coffre chiffré (`root_vault`) : avec lui, le mot de passe est gardé pour toujours
        # (`keep_s` ignoré), relu au démarrage et revérifié une fois avant le premier usage.
        self.vault = vault
        self._unverified = False
        if vault is not None:
            secret = vault.load(Secret)
            if secret is not None:
                self._secret = secret
                self._unverified = True
                log.info("root : mot de passe relu dans le coffre chiffré")

    @property
    def forever(self):
        return self.vault is not None

    # ---- événements -------------------------------------------------------------------

    def _emit(self, event, data):
        for fn in list(self.listeners):
            try:
                res = fn(event, dict(data))
                if asyncio.iscoroutine(res):
                    asyncio.ensure_future(res)
            except Exception:  # noqa: BLE001 — un appareil injoignable n'arrête pas le gardien
                log.warning("root : diffusion de %s impossible", event)

    def _ask_data(self, req, error=None):
        data = {"id": req.id, "machine": self.machine, "command": req.command,
                "expires_at": req.expires_at, "tries_left": self.max_tries - req.tries}
        if error:
            data["error"] = error
        return data

    # ---- mot de passe gardé ---------------------------------------------------------

    def kept(self):
        """Vrai si un mot de passe est gardé ; l'efface s'il a expiré."""
        if self._secret is not None and not self.forever and self.clock() >= self._expires_at:
            self._drop("expired")
        return self._secret is not None

    def busy(self):
        """Vrai si une relance du pont perdrait quelque chose : demande en cours, ou mot de passe
        gardé en mémoire seulement (celui du coffre est relu au démarrage)."""
        return (self.kept() and not self.forever) or self._request is not None

    def status(self):
        kept = self.kept()
        req = self._request
        if self.forever:
            # Gardé pour toujours : pas de bandeau « root gardé » dans les interfaces (elles ne
            # l'affichent que si `kept`) ; `stored` dit qu'il est dans le coffre.
            return {"machine": self.machine, "kept": False, "stored": kept, "forever": True,
                    "expires_at": None, "remaining": 0,
                    "pending": self._ask_data(req) if req is not None else None}
        return {"machine": self.machine, "kept": kept,
                "expires_at": self._expires_at if kept else None,
                "remaining": max(0, int(self._expires_at - self.clock())) if kept else 0,
                "pending": self._ask_data(req) if req is not None else None}

    def store(self, secret):
        """Garde `secret` (le gardien en devient le seul propriétaire) pour `keep_s` secondes."""
        self._drop(None)
        self._secret = secret
        self._unverified = False
        if self.forever:
            self.vault.save(secret)
            return
        self._expires_at = self.clock() + self.keep_s
        try:
            self._expiry = asyncio.get_running_loop().call_later(self.keep_s, self.kept)
        except RuntimeError:              # hors boucle (tests) : `kept()` vérifie l'heure
            self._expiry = None
        log.info("root : mot de passe gardé en mémoire pour %d s", self.keep_s)

    def _drop(self, reason):
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None
        if self._secret is None:
            return False
        self._secret.wipe()
        self._secret = None
        self._expires_at = 0.0
        if self.forever and reason not in (None, "stop"):
            self.vault.delete()
        if reason:
            log.info("root : mot de passe effacé (%s)", reason)
            self._emit("root.forgotten", {"machine": self.machine, "reason": reason})
        return True

    def forget(self, reason="forget"):
        """Efface le mot de passe et abandonne la demande en cours. Vrai s'il y en avait un."""
        req = self._request
        if req is not None:
            self._finish(req, False)
        return self._drop(reason)

    def close(self):
        """Arrêt du pont : tout est effacé."""
        self.forget("stop")

    # ---- demandes ---------------------------------------------------------------------

    def _new_request(self, command):
        loop = asyncio.get_running_loop()
        req = _Request(secrets.token_urlsafe(9), command, self.clock() + self.ask_timeout,
                       loop.create_future())
        req.timer = loop.call_later(self.ask_timeout, self._timeout, req)
        self._request = req
        log.info("root : demande %s envoyée aux appareils", req.id)
        self._emit("root.ask", self._ask_data(req))
        return req

    def _timeout(self, req):
        if self._request is req:
            log.info("root : demande %s sans réponse, abandonnée", req.id)
            self._finish(req, False)

    def _finish(self, req, ok):
        if self._request is not req:
            return
        self._request = None
        if req.timer is not None:
            req.timer.cancel()
        if not req.future.done():
            req.future.set_result(ok)
        self._emit("root.resolved", {"id": req.id, "ok": ok})

    def _used(self, command):
        self._emit("root.used", {"machine": self.machine, "command": command, "at": self.clock()})

    async def ask(self, command):
        """Mot de passe pour lancer `command` : une copie (`Secret`, à effacer par l'appelant),
        ou None (refusé, trois mauvais essais, délai, oublié). Sans mot de passe gardé, attend la
        réponse des appareils à la demande en cours (ouverte s'il n'y en a pas)."""
        command = clean_command(command)
        if self.kept() and self._unverified:
            # Relu du coffre : le mot de passe a pu changer depuis (passwd).
            ok = await asyncio.to_thread(self.verify, self._secret)
            if ok:
                self._unverified = False
            elif self._unverified:            # pas remplacé pendant la vérification
                log.info("root : mot de passe du coffre refusé par sudo, redemandé")
                self._drop("changed")
        if self.kept():
            self._used(command)
            return self._secret.copy()
        req = self._request
        opened = req is None
        if opened:
            req = self._new_request(command)
        ok = await asyncio.shield(req.future)
        if not ok or not self.kept():
            return None
        if not opened:            # la demande montrait une autre commande : celle-ci est signalée
            self._used(command)
        return self._secret.copy()

    async def answer(self, rid, password=None, cancel=False):
        """Réponse d'un appareil à la demande `rid`. {"ok": bool, "error"?: texte}.
        KeeperError si la demande est inconnue ou déjà réglée."""
        req = self._request
        if req is None or not isinstance(rid, str) or rid != req.id:
            raise KeeperError("introuvable", "Demande inconnue ou déjà réglée.")
        if cancel is True:
            log.info("root : demande %s refusée par un appareil", req.id)
            self._finish(req, False)
            return {"ok": False, "error": "Demande refusée."}
        secret = to_secret(password)
        if req.verifying:
            secret.wipe()
            raise KeeperError("conflit", "Un autre appareil a répondu : vérification en cours.")
        req.verifying = True
        try:
            ok = await asyncio.to_thread(self.verify, secret)
        except Exception as e:  # noqa: BLE001 — seule la nature de l'erreur est notée
            log.warning("root : vérification impossible (%s)", type(e).__name__)
            ok = False
        finally:
            req.verifying = False
        if self._request is not req:
            secret.wipe()
            raise KeeperError("introuvable", "Demande expirée ou abandonnée.")
        if ok:
            self.store(secret)
            self._finish(req, True)
            return {"ok": True}
        secret.wipe()
        req.tries += 1
        if req.tries >= self.max_tries:
            log.info("root : demande %s abandonnée après %d mauvais essais", req.id, req.tries)
            self._finish(req, False)
            return {"ok": False, "error": f"Mot de passe refusé {req.tries} fois : demande abandonnée."}
        error = f"Mot de passe refusé (essai {req.tries} sur {self.max_tries})."
        log.info("root : mauvais mot de passe pour la demande %s", req.id)
        self._emit("root.ask", self._ask_data(req, error))
        return {"ok": False, "error": error}


# --------------------------------------------------------------------------
# Socket
# --------------------------------------------------------------------------

def runtime_dirs():
    """Dossiers d'exécution possibles, dans l'ordre : `$XDG_RUNTIME_DIR`, `/run/user/<uid>` s'il
    existe et est à nous (service systemd du pont, sans XDG_RUNTIME_DIR), `/tmp/ccs-<uid>`."""
    uid = os.getuid()
    out = []
    env = os.environ.get("XDG_RUNTIME_DIR")
    if env:
        out.append(env)
    run = f"/run/user/{uid}"
    try:
        st = os.stat(run)
        if stat.S_ISDIR(st.st_mode) and st.st_uid == uid:
            out.append(run)
    except OSError:
        pass
    out.append(f"/tmp/ccs-{uid}")
    return list(dict.fromkeys(out))


def socket_path():
    return os.path.join(runtime_dirs()[0], "ccs", "root.sock")


def socket_paths():
    return [os.path.join(d, "ccs", "root.sock") for d in runtime_dirs()]


def peer_uid(sock):
    """uid du processus à l'autre bout d'un socket Unix (SO_PEERCRED)."""
    creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    return struct.unpack("3i", creds)[1]


def private_dir(path):
    """Crée `path` (0700) et vérifie qu'il est à nous, comme son parent ; OSError sinon."""
    uid = os.getuid()
    parent = os.path.dirname(path)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    for p in (parent, path):
        st = os.lstat(p)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != uid:
            raise PermissionError(f"dossier du gardien peu sûr : {p}")
    os.chmod(path, 0o700)


def _send_json(writer, data):
    writer.write(json.dumps(data, ensure_ascii=False).encode("utf-8") + b"\n")


class KeeperServer:
    """Le socket du gardien. `peer` : fonction qui lit l'uid du pair (tests)."""

    def __init__(self, keeper, path=None, peer=peer_uid):
        self.keeper = keeper
        self.path = str(path or socket_path())
        self._peer = peer
        self._server = None
        self._watchers = set()

    async def start(self):
        """Ouvre le socket ; AlreadyServed si un autre pont le tient déjà (il répond)."""
        private_dir(os.path.dirname(self.path))
        if await _alive(self.path):
            raise AlreadyServed(self.path)
        try:
            os.unlink(self.path)                  # reste d'un pont arrêté
        except FileNotFoundError:
            pass
        self._server = await asyncio.start_unix_server(self._serve, self.path, limit=MAX_REQUEST)
        os.chmod(self.path, 0o600)
        log.info("root : gardien prêt")

    async def close(self):
        for w in list(self._watchers):
            w.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            try:
                os.unlink(self.path)
            except OSError:
                pass

    async def _serve(self, reader, writer):
        try:
            try:
                uid = self._peer(writer.get_extra_info("socket"))
            except OSError:
                uid = None
            if uid != os.getuid():
                log.warning("root : connexion refusée (uid %s)", uid)
                return
            try:
                line = await asyncio.wait_for(reader.readline(), 10)
                req = json.loads(line)
            except (asyncio.TimeoutError, ValueError, asyncio.LimitOverrunError):
                return
            if not isinstance(req, dict):
                return
            await self._handle(req, reader, writer)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            try:
                writer.close()
            except RuntimeError:
                pass

    async def _handle(self, req, reader, writer):
        op = req.get("op")
        if op == "ask":
            secret = await self.keeper.ask(req.get("command"))
            if secret is None:
                writer.write(b"0")
                await writer.drain()
                return
            # Un seul tampon, effacé seulement après la fermeture : le transport d'asyncio peut
            # garder une vue sur lui tant que tout n'est pas parti.
            msg = bytearray(len(secret) + 1)
            msg[0] = 0x31
            msg[1:] = secret.view()
            secret.wipe()
            try:
                writer.write(msg)
                writer.close()
                await writer.wait_closed()
            finally:
                for i in range(len(msg)):
                    msg[i] = 0
        elif op == "status":
            _send_json(writer, self.keeper.status())
            await writer.drain()
        elif op == "forget":
            _send_json(writer, {"ok": True, "had": self.keeper.forget("forget")})
            await writer.drain()
        elif op == "answer":
            try:
                res = await self.keeper.answer(req.get("id"), req.get("password"),
                                               cancel=req.get("cancel") is True)
            except KeeperError as e:
                res = {"ok": False, "code": e.code, "error": e.message}
            req.clear()                           # la chaîne du mot de passe n'est plus tenue ici
            _send_json(writer, res)
            await writer.drain()
        elif op == "watch":
            await self._watch(reader, writer)

    async def _watch(self, reader, writer):
        def push(event, data):
            if not writer.is_closing():
                _send_json(writer, {"event": event, "data": data})
        self.keeper.listeners.append(push)
        self._watchers.add(writer)
        try:
            while await reader.read(4096):
                pass
        finally:
            self._watchers.discard(writer)
            self.keeper.listeners.remove(push)


async def _alive(path):
    """Vrai si un gardien de cet utilisateur répond sur `path`."""
    try:
        await async_request("status", path=path, timeout=3)
        return True
    except (OSError, ValueError, asyncio.TimeoutError):
        return False


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------

async def async_open(path=None, timeout=5):
    """(reader, writer) vers le gardien, après avoir vérifié qu'il est bien de notre uid."""
    paths = [path] if path else socket_paths()
    last = FileNotFoundError("gardien injoignable")
    for p in paths:
        try:
            r, w = await asyncio.wait_for(asyncio.open_unix_connection(p, limit=MAX_REQUEST), timeout)
        except (OSError, asyncio.TimeoutError) as e:
            last = e if isinstance(e, OSError) else ConnectionError("délai dépassé")
            continue
        try:
            ok = peer_uid(w.get_extra_info("socket")) == os.getuid()
        except OSError:
            ok = False
        if ok:
            return r, w
        w.close()
        last = ConnectionRefusedError("socket d'un autre utilisateur")
    raise last


async def async_request(op, path=None, timeout=5, **fields):
    """Requête JSON au gardien (status, forget, answer) ; réponse (dict). OSError, ValueError."""
    r, w = await async_open(path, timeout)
    try:
        w.write(json.dumps({"op": op, **fields}).encode("utf-8") + b"\n")
        fields.clear()
        await w.drain()
        line = await asyncio.wait_for(r.readline(), timeout)
    finally:
        w.close()
    data = json.loads(line)
    if not isinstance(data, dict):
        raise ValueError("réponse inattendue du gardien")
    return data


def _connect(timeout):
    last = FileNotFoundError("gardien injoignable")
    for p in socket_paths():
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect(p)
            if peer_uid(s) != os.getuid():
                raise ConnectionRefusedError("socket d'un autre utilisateur")
            return s
        except OSError as e:
            s.close()
            last = e
    raise last


def request(op, timeout=5):
    """Requête JSON au gardien (status, forget), en bloquant. OSError, ValueError."""
    with _connect(timeout) as s:
        s.sendall(json.dumps({"op": op}).encode("utf-8") + b"\n")
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    res = json.loads(data)
    if not isinstance(res, dict):
        raise ValueError("réponse inattendue du gardien")
    return res


def fetch_password(command, timeout=ASK_TIMEOUT_S + 30):
    """Mot de passe pour `command` (`Secret`), ou None (refus, délai). OSError si le gardien
    est injoignable."""
    with _connect(5) as s:
        s.settimeout(timeout)
        s.sendall(json.dumps({"op": "ask", "command": command}).encode("utf-8") + b"\n")
        buf = bytearray(MAX_PASSWORD + 2)
        view = memoryview(buf)
        n = 0
        try:
            while n < len(buf):
                try:
                    got = s.recv_into(view[n:])
                except ConnectionResetError:      # refusé par le gardien (autre uid…)
                    return None
                if not got:
                    break
                n += got
            if n < 2 or buf[0:1] != b"1":
                return None
            return Secret(view[1:n])
        finally:
            for i in range(len(buf)):
                buf[i] = 0


def ping():
    try:
        request("status", timeout=3)
        return True
    except (OSError, ValueError):
        return False


def ensure_keeper(spawn=None, wait_s=SPAWN_WAIT_S, sleep=time.sleep):
    """Vrai si le gardien répond ; sinon lance le pont local (`ccs bridge --local`) et l'attend."""
    if ping():
        return True
    try:
        (spawn or _spawn_bridge)()
    except OSError:
        return False
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        sleep(0.1)
        if ping():
            return True
    return False


def _spawn_bridge():
    from . import core
    subprocess.Popen([core.ccs_bin(), "bridge", "--local"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def askpass_path():
    """Chemin de `ccs-askpass` (version installée, dépôt, PATH), ou None."""
    here = Path(__file__)
    if here.parts[:4] == ("/", "usr", "lib", "ccs"):
        return "/usr/bin/ccs-askpass"
    sibling = here.resolve().parent.parent / "bin" / "ccs-askpass"
    if sibling.exists():
        return str(sibling)
    return shutil.which("ccs-askpass")


# --------------------------------------------------------------------------
# ccs-askpass
# --------------------------------------------------------------------------

_SUDO_SHORT_WITH_VALUE = set("CDghpRrTtUu")
_SUDO_LONG_WITH_VALUE = {"--chdir", "--chroot", "--close-from", "--command-timeout", "--group",
                         "--host", "--other-user", "--prompt", "--role", "--type", "--user"}


def sudo_command(argv):
    """Commande lancée par `sudo <options> <commande…>` (argv de sudo), ou None."""
    if not argv or os.path.basename(argv[0]) != "sudo":
        return None
    args = list(argv[1:])
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            i += 1
            break
        if a.startswith("--"):
            i += 2 if a in _SUDO_LONG_WITH_VALUE else 1
            continue
        if a.startswith("-") and len(a) > 1:
            i += 1
            for j, c in enumerate(a[1:]):
                if c in _SUDO_SHORT_WITH_VALUE:
                    if j == len(a) - 2:   # valeur dans l'argument suivant
                        i += 1
                    break
            continue
        break
    rest = args[i:]
    return shlex.join(rest) if rest else "sudo " + shlex.join(args)


def parent_command(ppid=None):
    """Commande de sudo, le parent de `ccs-askpass` (lue dans /proc), ou None."""
    try:
        with open(f"/proc/{ppid or os.getppid()}/cmdline", "rb") as f:
            raw = f.read()
    except OSError:
        return None
    argv = [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]
    return sudo_command(argv)


def askpass_main(argv=None, out=None, fetch=fetch_password, ensure=ensure_keeper):
    """`ccs-askpass` : écrit le mot de passe suivi d'un retour à la ligne sur la sortie standard
    (0), ou rien (1). L'invite de sudo (argv[1]) est ignorée."""
    command = clean_command(parent_command() or os.environ.get("CCS_ROOT_COMMAND"))
    secret = None
    try:
        try:
            secret = fetch(command)
        except OSError:
            if not ensure():
                print("ccs-askpass : le gardien du mot de passe (pont CCS) ne répond pas", file=sys.stderr)
                return 1
            secret = fetch(command)
    except (OSError, ValueError):
        print("ccs-askpass : le gardien du mot de passe ne répond pas", file=sys.stderr)
        return 1
    if secret is None:
        print("ccs-askpass : pas de mot de passe (refusé, abandonné ou délai dépassé)", file=sys.stderr)
        return 1
    out = out or sys.stdout.buffer
    try:
        out.write(secret.view())
        out.write(b"\n")
        out.flush()
    except OSError:
        return 1
    finally:
        secret.wipe()
    return 0


# --------------------------------------------------------------------------
# ccs root
# --------------------------------------------------------------------------

USAGE = """usage : ccs root -- <commande…>   lance la commande avec sudo, mot de passe demandé aux appareils
       ccs root status              mot de passe gardé ou non, temps restant
       ccs root forget           efface tout de suite le mot de passe gardé"""

STATUS_WORDS = ("etat", "état", "status")
FORGET_WORDS = ("oublier", "forget")


def _minutes(seconds):
    m = max(1, round(seconds / 60))
    return f"{m} min"


def status_text(st):
    machine = st.get("machine") or "cette machine"
    if st.get("stored"):
        lines = [f"Mot de passe root gardé (chiffré) sur {machine}, sans limite de durée. "
                 "Pour l'effacer : ccs root oublier."]
    elif st.get("kept"):
        lines = [f"Mot de passe root gardé en mémoire sur {machine} : encore {_minutes(st.get('remaining', 0))}."]
    else:
        lines = [f"Aucun mot de passe root gardé sur {machine}."]
    pending = st.get("pending")
    if isinstance(pending, dict):
        lines.append(f"Demande en attente sur les appareils : {pending.get('command')}")
    return "\n".join(lines)


def run_root(cmd, ensure=ensure_keeper, call=subprocess.call):
    """`ccs root -- <commande>` : `sudo -k -A`, le mot de passe venant du gardien (`-k` : sudo
    le redemande à chaque fois, chaque commande passe donc par le gardien et est signalée)."""
    askpass = askpass_path()
    if askpass is None:
        print("ccs root : ccs-askpass introuvable", file=sys.stderr)
        return 1
    if not ensure():
        print("ccs root : le pont local de CCS ne démarre pas", file=sys.stderr)
        return 1
    env = dict(os.environ, SUDO_ASKPASS=askpass, CCS_ROOT_COMMAND=shlex.join(cmd))
    try:
        return call(["sudo", "-k", "-A", "--", *cmd], env=env)
    except KeyboardInterrupt:
        return 130
    except OSError:
        print("ccs root : sudo introuvable", file=sys.stderr)
        return 127


def command(argv, ensure=ensure_keeper, call=subprocess.call, req=request):
    """`ccs root …` (arguments après « root »)."""
    if not argv or argv[0] in ("-h", "--help", "aide"):
        print(USAGE)
        return 0 if argv else 2
    word = argv[0]
    if word == "--":
        if len(argv) < 2:
            print(USAGE, file=sys.stderr)
            return 2
        return run_root(argv[1:], ensure=ensure, call=call)
    if word in STATUS_WORDS:
        try:
            print(status_text(req("status")))
        except (OSError, ValueError):
            print("Aucun mot de passe root gardé (le pont local de CCS ne tourne pas).")
        return 0
    if word in FORGET_WORDS:
        try:
            had = req("forget").get("had")
        except (OSError, ValueError):
            had = False
        print("Mot de passe root effacé." if had else "Aucun mot de passe root n'était gardé.")
        return 0
    print(f"ccs root : action inconnue « {word} » (une commande se lance après « -- »)\n{USAGE}",
          file=sys.stderr)
    return 2
