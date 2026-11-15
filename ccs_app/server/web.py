"""ccs-web : le seul service du serveur joignable depuis Internet (derrière nginx), sans droits.

Il sert la version web, transmet les connexions à `ccs-auth` et relaie chaque WebSocket vers le
pont de l'utilisateur connecté, en présentant le ticket que `ccs-auth` a remis. Il ne garde
aucun secret : session et appareil sont des cookies `HttpOnly`, `Secure`, `SameSite=Strict`.
"""

import asyncio
import json
import logging
from pathlib import Path

from aiohttp import WSMsgType, web

from .. import __version__
from . import paths, rpc
from .tokens import DEVICE_AGE, MAX_AGE, session_hash

log = logging.getLogger("ccs.web")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
DEFAULT_CONFIG = {"listen": "127.0.0.1:8420", "origin": "https://ccs.mawena.cloud"}
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
SESSION, DEVICE = "ccs_session", "ccs_device"
RECHECK_S = 300          # une session expirée ou révoquée ferme ses WebSocket au plus tard après ce délai
CLOSED_BY_AUTH = 4001


def load_config(path=None):
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(path or paths.web_config(), encoding="utf-8") as f:
            data = json.load(f)
        for k in cfg:
            if isinstance(data.get(k), str) and data[k].strip():
                cfg[k] = data[k].strip().rstrip("/")
    except (OSError, ValueError, AttributeError):
        pass
    return cfg


def client_ip(remote, headers):
    """Adresse du client : celle que nginx transmet, seulement si la connexion vient de lui."""
    if remote in ("127.0.0.1", "::1"):
        fwd = headers.get("X-Forwarded-For", "")
        last = fwd.split(",")[-1].strip() if fwd else ""
        if last:
            return last
    return remote or "?"


class AuthClient:
    """Client de `ccs-auth` (reconnexion à la demande)."""

    def __init__(self, path=None):
        self.path = path or paths.auth_socket()
        self._client = None
        self._lock = asyncio.Lock()

    async def call(self, method, **params):
        async with self._lock:
            if self._client is None or not self._client.connected:
                self._client = rpc.RpcClient()
                await self._client.connect_unix(self.path)
        return await self._client.call(method, **params)


class BridgeConnector:
    async def connect(self, user, ticket, shash):
        c = rpc.RpcClient()
        await c.connect_unix(paths.bridge_socket(user))
        await c.call("hello", ticket=ticket, session_hash=shash)
        return c


def make_app(auth, bridges, config):
    allowed = {config["origin"], f"http://{config['listen']}"}
    app = web.Application(client_max_size=rpc.MAX_LINE)
    open_ws = {}             # jeton (session ou application) → WebSocket ouverts

    async def close_all(token):
        for ws in list(open_ws.pop(token, ())):
            await ws.close(code=CLOSED_BY_AUTH, message=b"session terminee")

    async def add_headers(_request, response):
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers.setdefault("Cache-Control", "no-store")
    app.on_response_prepare.append(add_headers)

    def ip(request):
        return client_ip(request.remote, request.headers)

    def origin_ok(request):
        origin = request.headers.get("Origin")
        return origin is None or origin in allowed

    async def body(request):
        try:
            data = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise web.HTTPBadRequest(text="JSON attendu") from None
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text="objet JSON attendu")
        return data

    def set_cookie(resp, name, value, max_age):
        resp.set_cookie(name, value, max_age=max_age, path="/", secure=True, httponly=True,
                        samesite="Strict")

    def login_reply(result):
        """Réponse au navigateur : les jetons partent en cookies, jamais dans le corps."""
        public = {k: v for k, v in result.items() if k not in ("session", "device", "ticket")}
        resp = web.json_response(public)
        if result.get("status") == "ok" and result.get("session"):
            set_cookie(resp, SESSION, result["session"], MAX_AGE)
            if result.get("device"):
                set_cookie(resp, DEVICE, result["device"], DEVICE_AGE)
        return resp

    async def safe_call(method, **params):
        try:
            return await auth.call(method, **params)
        except rpc.RpcError as e:
            if e.code == "refuse":
                raise web.HTTPUnauthorized(text=e.message) from None
            raise web.HTTPServiceUnavailable(text="Service de connexion indisponible.") from None
        except OSError:
            raise web.HTTPServiceUnavailable(text="Service de connexion indisponible.") from None

    async def health(_request):
        return web.json_response({"ok": True, "version": __version__})

    async def login(request):
        if not origin_ok(request):
            raise web.HTTPForbidden()
        d = await body(request)
        result = await safe_call("login", user=str(d.get("user") or ""), password=str(d.get("password") or ""),
                                 code=str(d.get("code") or ""), remember=bool(d.get("remember")),
                                 device=request.cookies.get(DEVICE, ""), ip=ip(request))
        return login_reply(result)

    async def enroll(request):
        if not origin_ok(request):
            raise web.HTTPForbidden()
        d = await body(request)
        result = await safe_call("enroll", pending=str(d.get("pending") or ""), code=str(d.get("code") or ""),
                                 remember=bool(d.get("remember")), ip=ip(request))
        if "token" in result:                       # appairage d'un appareil
            return web.json_response({k: v for k, v in result.items() if k != "ticket"})
        return login_reply(result)

    async def pair(request):
        d = await body(request)
        result = await safe_call("pair", user=str(d.get("user") or ""), password=str(d.get("password") or ""),
                                 code=str(d.get("code") or ""), name=str(d.get("name") or "appareil"),
                                 ip=ip(request))
        return web.json_response({k: v for k, v in result.items() if k != "ticket"})

    async def logout(request):
        if not origin_ok(request):
            raise web.HTTPForbidden()
        session = request.cookies.get(SESSION)
        if session:
            await safe_call("logout", session=session)
            await close_all(session)
        resp = web.json_response({})
        resp.del_cookie(SESSION, path="/")
        return resp

    async def session_info(request):
        who = await identify(request)
        if who is None:
            raise web.HTTPUnauthorized()
        return web.json_response({"user": who[0]})

    async def tokens(request):
        return web.json_response(await safe_call("tokens", session=request.cookies.get(SESSION, "")))

    async def revoke(request):
        if not origin_ok(request):
            raise web.HTTPForbidden()
        d = await body(request)
        return web.json_response(await safe_call("revoke", session=request.cookies.get(SESSION, ""),
                                                 token_id=str(d.get("token_id") or "")))

    async def identify(request):
        """(utilisateur, ticket, jeton) d'après le jeton d'application ou le cookie de session."""
        header = request.headers.get("Authorization", "")
        try:
            if header.startswith("Bearer "):
                token = header[7:].strip()
                r = await auth.call("check_app", token=token)
            else:
                token = request.cookies.get(SESSION, "")
                if not token:
                    return None
                r = await auth.call("check", session=token)
        except rpc.RpcError:
            return None
        return r["user"], r["ticket"], token

    async def ws_handler(request):
        if not origin_ok(request):
            raise web.HTTPForbidden()
        who = await identify(request)
        if who is None:
            raise web.HTTPUnauthorized()
        user, ticket, token = who
        ws = web.WebSocketResponse(max_msg_size=rpc.MAX_LINE, heartbeat=30)
        await ws.prepare(request)
        try:
            bridge = await bridges.connect(user, ticket, session_hash(token))
        except (OSError, rpc.RpcError):
            log.warning("pont de %s injoignable", user)
            await ws.close(code=1011, message=b"pont injoignable")
            return ws

        def on_event(name, data):
            if not ws.closed:
                asyncio.ensure_future(ws.send_json({"event": name, "data": data}))
        bridge.on_event = on_event

        async def handle(msg):
            mid = msg.get("id")
            method, params = msg.get("method"), msg.get("params") or {}
            if not isinstance(method, str) or method == "hello" or not isinstance(params, dict):
                reply = {"id": mid, "error": {"code": "refuse", "message": "Requête refusée."}}
            else:
                try:
                    reply = {"id": mid, "result": await bridge.call(method, **params)}
                except rpc.RpcError as e:
                    reply = {"id": mid, "error": {"code": e.code, "message": e.message}}
            if not ws.closed:
                await ws.send_json(reply)

        open_ws.setdefault(token, set()).add(ws)

        async def recheck():
            bearer = request.headers.get("Authorization", "").startswith("Bearer ")
            while not ws.closed:
                await asyncio.sleep(RECHECK_S)
                try:
                    if bearer:
                        await auth.call("check_app", token=token)
                    else:
                        await auth.call("check", session=token)
                except rpc.RpcError as e:
                    if e.code == "refuse":
                        await ws.close(code=CLOSED_BY_AUTH, message=b"session expiree")
                        return
                except OSError:
                    pass
        watcher = asyncio.ensure_future(recheck())
        tasks = set()
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if isinstance(data, dict):
                    t = asyncio.ensure_future(handle(data))
                    tasks.add(t)
                    t.add_done_callback(tasks.discard)
        finally:
            watcher.cancel()
            for t in tasks:
                t.cancel()
            open_ws.get(token, set()).discard(ws)
            await bridge.close()
        return ws

    async def index(_request):
        return web.FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    app.router.add_get("/api/health", health)
    app.router.add_post("/api/login", login)
    app.router.add_post("/api/enroll", enroll)
    app.router.add_post("/api/pair", pair)
    app.router.add_post("/api/logout", logout)
    app.router.add_get("/api/session", session_info)
    app.router.add_get("/api/tokens", tokens)
    app.router.add_post("/api/revoke", revoke)
    app.router.add_get("/api/ws", ws_handler)
    app.router.add_get("/", index)
    app.router.add_static("/", WEB_DIR, show_index=False, follow_symlinks=False)
    return app


async def serve():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = load_config()
    host, _, port = config["listen"].rpartition(":")
    app = make_app(AuthClient(), BridgeConnector(), config)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host or "127.0.0.1", int(port)).start()
    log.info("ccs-web prêt sur %s (site %s)", config["listen"], config["origin"])
    await asyncio.Event().wait()
