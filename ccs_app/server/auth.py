"""ccs-auth : le seul service du serveur qui tourne en root, et il ne fait que ceci.

Il vérifie une connexion (compte Ubuntu par PAM, groupe `ccs`, `root` refusé, code TOTP),
tient les sessions et les jetons, démarre le pont de l'utilisateur et remet à `ccs-web` un
ticket que seul ce pont sait vérifier. Il n'écoute que sur `/run/ccs/auth.sock`, ouvert au
seul groupe `ccs-web`. Rien de secret ne va au journal.
"""

import asyncio
import grp
import hashlib
import hmac
import logging
import os
import pwd
import secrets
import stat
import subprocess
import time

from . import pam_auth, paths, portier, rpc, totp
from .ratelimit import Limiter
from .tokens import TokenStore, session_hash

log = logging.getLogger("ccs.auth")

REFUSED = {"status": "refused", "message": "Identifiant, mot de passe ou code incorrect"}
PENDING_TTL = 600
WEB_GROUP = "ccs-web"


def _group_exists(name):
    try:
        grp.getgrnam(name)
        return True
    except KeyError:
        return False


def _chown(path, user):
    """Le fichier ou le dossier appartient à l'utilisateur ; un dossier au groupe ccs-web.
    Jamais à travers un lien symbolique (le dossier du pont appartient à l'utilisateur)."""
    pw = pwd.getpwnam(user)
    gid = -1
    if os.path.isdir(path) and not os.path.islink(path) and _group_exists(WEB_GROUP):
        gid = grp.getgrnam(WEB_GROUP).gr_gid
    os.chown(path, pw.pw_uid, gid, follow_symlinks=False)


def start_bridge(user, timeout=20):
    """Démarre `ccs-bridge@<user>` par systemd et attend son socket."""
    subprocess.run(["systemctl", "start", f"ccs-bridge@{paths.check_user(user)}.service"],
                   check=False, timeout=timeout, capture_output=True)
    sock = paths.bridge_socket(user)
    deadline = time.monotonic() + 10
    while not sock.exists() and time.monotonic() < deadline:
        time.sleep(0.1)


class AuthService:
    def __init__(self, tokens, pam_check=pam_auth.authenticate, allowed=pam_auth.allowed,
                 spawn_bridge=start_bridge, clock=time.time, host="ccs.mawena.cloud",
                 refuse_delay=1.0, chown=_chown, limiter=None, portier_config=portier.load):
        self.tokens = tokens
        self.pam_check = pam_check
        self.allowed = allowed
        self.spawn_bridge = spawn_bridge
        self.clock = clock
        self.host = host
        self.refuse_delay = refuse_delay
        self.chown = chown
        self.limiter = limiter or Limiter()
        self.portier_config = portier_config
        self.sleep = asyncio.sleep
        self._pending = {}          # jeton d'inscription → {user, secret, expires, pair}

    def handlers(self):
        def wrap(method):
            async def handler(_conn, params):
                return await method(params)
            return handler
        return {name: wrap(getattr(self, attr)) for name, attr in (
            ("login", "login"), ("enroll", "enroll"), ("pair", "pair"), ("check", "check"),
            ("check_app", "check_app"), ("logout", "logout"), ("app_token", "app_token"),
            ("tokens", "tokens_list"), ("revoke", "revoke"), ("portier", "portier"))}

    # ---- outils ----------------------------------------------------------------------

    @staticmethod
    def _str(params, key):
        v = params.get(key)
        return v if isinstance(v, str) else ""

    def _keys(self, user, ip):
        return ("u:" + user, "ip:" + ip)

    def _blocked(self, user, ip):
        now = self.clock()
        wait = max(self.limiter.retry_after(k, now) for k in self._keys(user, ip))
        return {"status": "blocked", "retry_after": wait} if wait else None

    async def _refuse(self, user, ip, started, reason, count=True):
        if count:
            now = self.clock()
            for k in self._keys(user, ip):
                self.limiter.failure(k, now)
        log.warning("connexion refusée : %r depuis %s (%s)", user[:40], ip, reason)
        remaining = self.refuse_delay - (asyncio.get_running_loop().time() - started)
        if remaining > 0:
            await self.sleep(remaining)
        return dict(REFUSED)

    def _canonical_key(self, user):
        p = paths.canonical_key(user)
        p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(p.parent, 0o700)
        try:
            fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as f:
                key = f.read(64)
            if len(key) == 32:
                return key
        except FileNotFoundError:
            pass
        key = secrets.token_bytes(32)
        tmp = p.with_name(f".{p.name}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        os.replace(tmp, p)
        return key

    def _ensure_key(self, user):
        """Copie de la clé dans le dossier du pont (à l'utilisateur, groupe ccs-web, 2750).
        L'utilisateur peut y poser n'importe quoi : la copie n'est lue que sans suivre de lien,
        et réécrite en supprimant l'entrée puis en créant un fichier neuf (O_EXCL)."""
        key = self._canonical_key(user)
        d = paths.bridge_dir(user)
        d.parent.mkdir(parents=True, exist_ok=True)          # /run/ccs/bridge : à root
        if d.is_symlink():
            d.unlink()
        d.mkdir(exist_ok=True)
        os.chmod(d, 0o2750)
        self.chown(d, user)
        key_path = paths.bridge_key(user)
        try:
            fd = os.open(key_path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as f:
                st = os.fstat(f.fileno())
                current = f.read(64)
            if current == key and stat.S_ISREG(st.st_mode) and st.st_nlink == 1 \
                    and stat.S_IMODE(st.st_mode) == 0o600:
                return key
        except OSError:
            pass
        try:
            os.unlink(key_path)                               # l'entrée seule, jamais sa cible
        except FileNotFoundError:
            pass
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        self.chown(key_path, user)
        return key

    async def _ticket(self, user, token):
        key = self._ensure_key(user)
        if not paths.bridge_socket(user).exists():
            await asyncio.to_thread(self.spawn_bridge, user)
        return hmac.new(key, session_hash(token).encode(), hashlib.sha256).hexdigest()

    async def _open(self, user, ip, remember=False, pair=None):
        for k in self._keys(user, ip):
            self.limiter.success(k)
        if pair is not None:
            token = self.tokens.new_app(user, pair[:60] or "appareil")
            log.info("appareil appairé : %s depuis %s", user, ip)
            return {"status": "ok", "user": user, "token": token,
                    "ticket": await self._ticket(user, token)}
        session = self.tokens.new_session(user)
        out = {"status": "ok", "user": user, "session": session,
               "ticket": await self._ticket(user, session)}
        if remember:
            out["device"] = self.tokens.new_device(user)
        log.info("connexion : %s depuis %s", user, ip)
        return out

    # ---- connexion -------------------------------------------------------------------

    async def _authenticate(self, params, pair=None):
        started = asyncio.get_running_loop().time()
        user, password = self._str(params, "user"), self._str(params, "password")
        code, device, ip = self._str(params, "code"), self._str(params, "device"), self._str(params, "ip")
        blocked = self._blocked(user, ip)
        if blocked:
            log.warning("connexion bloquée : %r depuis %s", user[:40], ip)
            return blocked
        # PAM est appelé même pour un compte refusé : même durée, aucun indice sur le motif
        pam_ok = bool(user and password) and await asyncio.to_thread(self.pam_check, user, password)
        ok = pam_ok and self.allowed(user)
        if not ok:
            return await self._refuse(user, ip, started, "compte ou mot de passe")
        secret = totp.load(user)
        if secret is None:
            pending = secrets.token_urlsafe(24)
            secret = totp.new_secret()
            self._pending[pending] = {"user": user, "secret": secret, "pair": pair,
                                      "remember": bool(params.get("remember")),
                                      "expires": self.clock() + PENDING_TTL}
            log.info("inscription du code commencée : %s", user)
            return {"status": "enroll", "pending": pending, "secret": secret,
                    "qr_svg": totp.qr_svg(totp.uri(user, secret, self.host))}
        if pair is None and device and self.tokens.check_device(device, user):
            return await self._open(user, ip, remember=False)
        if not code:
            return {"status": "code"}
        if not totp.verify(secret, code, self.clock()):
            return await self._refuse(user, ip, started, "code")
        return await self._open(user, ip, remember=bool(params.get("remember")), pair=pair)

    async def login(self, params):
        return await self._authenticate(params)

    async def pair(self, params):
        return await self._authenticate(params, pair=self._str(params, "name") or "appareil")

    async def enroll(self, params):
        started = asyncio.get_running_loop().time()
        ip = self._str(params, "ip")
        entry = self._pending.get(self._str(params, "pending"))
        if entry is None or entry["expires"] < self.clock():
            self._pending.pop(self._str(params, "pending"), None)
            return await self._refuse("", ip, started, "inscription expirée", count=False)
        user = entry["user"]
        blocked = self._blocked(user, ip)
        if blocked:
            return blocked
        if not totp.verify(entry["secret"], self._str(params, "code"), self.clock()):
            return await self._refuse(user, ip, started, "premier code")
        totp.save(user, entry["secret"])
        del self._pending[self._str(params, "pending")]
        log.info("code enregistré : %s", user)
        remember = bool(params.get("remember")) or entry["remember"]
        return await self._open(user, ip, remember=remember, pair=entry["pair"])

    # ---- sessions et jetons ----------------------------------------------------------

    def _portier_user(self, params):
        """Utilisateur annoncé par Portier (via `ccs-web`) : revérifié ici, d'après la
        configuration lue à chaque appel, pour que `ccs-web` ne puisse pas s'en passer."""
        user = self._str(params, "portier")
        if not (portier.allows(self.portier_config(), user) and self.allowed(user)):
            log.warning("mode Portier refusé : %r", user[:40])
            raise rpc.RpcError("refuse", "Mode Portier refusé.")
        return user

    def _session_user(self, params):
        if self._str(params, "app"):
            user = self.tokens.check_app(self._str(params, "app"))
            if user is None:
                raise rpc.RpcError("refuse", "Jeton inconnu ou révoqué.")
            return user
        if self._str(params, "portier"):
            return self._portier_user(params)
        user = self.tokens.check_session(self._str(params, "session"))
        if user is None:
            raise rpc.RpcError("refuse", "Session expirée.")
        return user

    async def check(self, params):
        user = self._session_user(params)
        return {"user": user, "ticket": await self._ticket(user, self._str(params, "session"))}

    async def check_app(self, params):
        token = self._str(params, "token")
        user = self.tokens.check_app(token)
        if user is None:
            raise rpc.RpcError("refuse", "Jeton inconnu ou révoqué.")
        return {"user": user, "ticket": await self._ticket(user, token)}

    async def portier(self, params):
        """Ticket du pont pour un utilisateur vérifié par Portier : jeton éphémère, propre à une
        connexion, jamais enregistré (rien à révoquer : Portier tient la session)."""
        user = self._portier_user(params)
        token = "portier:" + secrets.token_urlsafe(24)
        return {"user": user, "token": token, "ticket": await self._ticket(user, token)}

    async def logout(self, params):
        self.tokens.end_session(self._str(params, "session"))
        return {}

    async def app_token(self, params):
        if self._str(params, "app"):
            raise rpc.RpcError("refuse", "Un jeton d'appareil ne crée pas d'autre jeton.")
        user = self._session_user(params)
        return {"token": self.tokens.new_app(user, self._str(params, "name")[:60] or "appareil")}

    async def tokens_list(self, params):
        return {"tokens": self.tokens.list_tokens(self._session_user(params))}

    async def revoke(self, params):
        user = self._session_user(params)
        return {"revoked": self.tokens.revoke(user, self._str(params, "token_id"))}


async def serve():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    svc = AuthService(TokenStore(paths.sessions_file()))
    server = rpc.RpcServer(svc.handlers())
    group = WEB_GROUP if _group_exists(WEB_GROUP) else None
    await server.start_unix(paths.auth_socket(), 0o660, group)
    log.info("ccs-auth prêt sur %s", paths.auth_socket())
    await asyncio.Event().wait()
