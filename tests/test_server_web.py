"""ccs-web : connexion par cookie sécurisé, relais WebSocket vers le pont, en-têtes de sécurité.
Faux ccs-auth et faux pont : aucun vrai service."""

import asyncio
import json
import unittest

from aiohttp import WSMsgType
from aiohttp.test_utils import AioHTTPTestCase

from ccs_app.server import rpc, web
from ccs_app.server.tokens import session_hash

ORIGIN = "https://ccs.mawena.cloud"


class FakeAuth:
    def __init__(self):
        self.calls = []

    async def call(self, method, **params):
        self.calls.append((method, params))
        if method == "login":
            if params.get("password") != "bon":
                return {"status": "refused", "message": "Identifiant, mot de passe ou code incorrect"}
            out = {"status": "ok", "user": "alice", "session": "SESSION-1", "ticket": "T1"}
            if params.get("remember"):
                out["device"] = "DEVICE-1"
            return out
        if method == "check":
            if params.get("session") != "SESSION-1" or getattr(self, "expired", False):
                raise rpc.RpcError("refuse", "Session expirée.")
            return {"user": "alice", "ticket": "T1"}
        if method == "check_app":
            if params.get("token") != "APP-1":
                raise rpc.RpcError("refuse", "Jeton inconnu.")
            return {"user": "alice", "ticket": "T2"}
        if method == "pair":
            return {"status": "ok", "user": "alice", "token": "APP-1", "ticket": "T2"}
        if method == "app_token":
            if not params.get("portier") and params.get("session") != "SESSION-1":
                raise rpc.RpcError("refuse", "Session expirée.")
            return {"token": "APP-2"}
        if method == "tokens":
            return {"tokens": [{"id": "abc", "kind": "app", "name": "PC", "created": 1, "last_used": 2}]}
        return {}


class FakeBridgeClient:
    def __init__(self):
        self.on_event = None
        self.calls = []
        self.closed = False
        self.lost = asyncio.Event()          # posé : la connexion au pont est tombée

    async def wait_closed(self):
        await self.lost.wait()

    async def call(self, method, **params):
        self.calls.append((method, params))
        if method == "boom":
            raise rpc.RpcError("refuse", "non")
        if method == "machines.attach" and params.get("machine") == "eteint":
            raise rpc.RpcError("introuvable", "eteint est hors ligne.")
        if method == "machines.attach" and params.get("machine") == "neuf" and self.on_event:
            self.on_event("machines.ready", {"machine": "neuf", "name": "Neuf"})   # pont 1.0 : il pousse lui-même
        return {"echo": params}

    async def close(self):
        self.closed = True


class FakeBridges:
    def __init__(self):
        self.connected = []

    async def connect(self, user, ticket, shash, client_protocol=0):
        c = FakeBridgeClient()
        self.connected.append((user, ticket, shash, c))
        self.protocols = getattr(self, "protocols", []) + [client_protocol]
        return c


class WebTest(AioHTTPTestCase):
    async def get_application(self):
        self.auth = FakeAuth()
        self.bridges = FakeBridges()
        return web.make_app(self.auth, self.bridges, {"listen": "127.0.0.1:8420", "origin": ORIGIN})

    async def login(self, remember=False):
        r = await self.client.post("/api/login", json={"user": "alice", "password": "bon", "code": "123456",
                                                       "remember": remember})
        self.assertEqual(r.status, 200)
        # cookie Secure : le client de test (http) ne le renverrait pas, on le pose à la main
        for c in r.headers.getall("Set-Cookie", []):
            name, _, rest = c.partition("=")
            if name in ("ccs_session", "ccs_device"):
                self.client.session.cookie_jar.update_cookies({name: rest.split(";")[0]})
        return r

    async def test_health(self):
        r = await self.client.get("/api/health")
        self.assertEqual(r.status, 200)
        data = await r.json()
        self.assertTrue(data["ok"])
        self.assertIn("version", data)

    async def test_login_sets_secure_cookies(self):
        r = await self.login(remember=True)
        body = await r.json()
        self.assertEqual(body, {"status": "ok", "user": "alice"})     # aucun jeton dans le corps
        cookies = r.headers.getall("Set-Cookie")
        sess = next(c for c in cookies if c.startswith("ccs_session="))
        dev = next(c for c in cookies if c.startswith("ccs_device="))
        for c in (sess, dev):
            low = c.lower()
            self.assertIn("httponly", low)
            self.assertIn("secure", low)
            self.assertIn("samesite=strict", low)
            self.assertIn("path=/", low)
        self.assertEqual(self.auth.calls[0][1]["ip"], "127.0.0.1")

    async def test_login_refused_passthrough(self):
        r = await self.client.post("/api/login", json={"user": "alice", "password": "faux"})
        self.assertEqual((await r.json())["status"], "refused")
        self.assertFalse([c for c in r.headers.getall("Set-Cookie", []) if c.startswith("ccs_session=")])

    async def test_login_bad_body(self):
        r = await self.client.post("/api/login", data="pas du json")
        self.assertEqual(r.status, 400)

    async def test_device_cookie_forwarded(self):
        self.client.session.cookie_jar.update_cookies({"ccs_device": "DEVICE-1"})
        await self.client.post("/api/login", json={"user": "alice", "password": "bon"})
        self.assertEqual(self.auth.calls[-1][1]["device"], "DEVICE-1")

    async def test_ws_requires_session(self):
        r = await self.client.get("/api/ws", headers={"Origin": ORIGIN})
        self.assertEqual(r.status, 401)

    async def test_ws_bad_origin_403(self):
        await self.login()
        r = await self.client.get("/api/ws", headers={"Origin": "https://ailleurs.example"})
        self.assertEqual(r.status, 403)

    async def test_ws_relays_with_ticket(self):
        await self.login()
        ws = await self.client.ws_connect("/api/ws", headers={"Origin": ORIGIN})
        user, ticket, shash, bridge = self.bridges.connected[0]
        self.assertEqual((user, ticket, shash), ("alice", "T1", session_hash("SESSION-1")))
        await ws.send_json({"id": 7, "method": "accounts.state", "params": {"a": 1}})
        msg = await ws.receive_json(timeout=5)
        self.assertEqual(msg, {"id": 7, "result": {"echo": {"a": 1}}})
        await ws.send_json({"id": 8, "method": "boom", "params": {}})
        msg = await ws.receive_json(timeout=5)
        self.assertEqual(msg["error"]["code"], "refuse")
        await ws.send_json({"id": 9, "method": "hello", "params": {}})
        msg = await ws.receive_json(timeout=5)
        self.assertEqual(msg["error"]["code"], "refuse")               # hello réservé au relais
        bridge.on_event("chat.event", {"chat_id": "c1"})
        msg = await ws.receive_json(timeout=5)
        self.assertEqual(msg, {"event": "chat.event", "data": {"chat_id": "c1"}})
        await ws.close()
        for _ in range(50):
            if bridge.closed:
                break
            await __import__("asyncio").sleep(0.01)
        self.assertTrue(bridge.closed)

    async def test_ws_machine_relays_through_the_bridge(self):
        await self.login()
        ws = await self.client.ws_connect("/api/ws?machine=pc", headers={"Origin": ORIGIN})
        ready = await ws.receive_json(timeout=5)
        # pont d'avant la 1.0.0 (il ne pousse rien) : ccs-web envoie l'ancien nom à un ancien client
        self.assertEqual(ready, {"event": "machine.ready", "data": {"echo": {"machine": "pc"}}})
        await ws.send_json({"id": 1, "method": "chat.list", "params": {}})
        self.assertEqual((await ws.receive_json(timeout=5))["id"], 1)
        bridge = self.bridges.connected[0][3]
        self.assertEqual(bridge.calls[0], ("machines.attach", {"machine": "pc"}))
        for i, name in enumerate(("machine.attach", "machines.attach")):
            await ws.send_json({"id": 2 + i, "method": name, "params": {"machine": "x"}})
            self.assertEqual((await ws.receive_json(timeout=5))["error"]["code"], "refuse")
        await ws.close()

    async def test_ws_machine_ready_comes_from_the_bridge(self):
        await self.login()
        ws = await self.client.ws_connect("/api/ws?protocol=1&machine=neuf", headers={"Origin": ORIGIN})
        ready = await ws.receive_json(timeout=5)
        self.assertEqual(ready, {"event": "machines.ready", "data": {"machine": "neuf", "name": "Neuf"}})
        self.assertEqual(self.bridges.protocols, [1])
        await ws.send_json({"id": 1, "method": "chat.list", "params": {}})
        self.assertEqual((await ws.receive_json(timeout=5)), {"id": 1, "result": {"echo": {}}})
        await ws.close()

    async def test_ws_old_bridge_new_client_gets_new_ready_name(self):
        await self.login()
        ws = await self.client.ws_connect("/api/ws?protocol=1&machine=pc", headers={"Origin": ORIGIN})
        ready = await ws.receive_json(timeout=5)
        self.assertEqual(ready["event"], "machines.ready")
        await ws.close()

    async def test_ws_machine_down_closes_with_the_reason(self):
        await self.login()
        ws = await self.client.ws_connect("/api/ws?machine=eteint", headers={"Origin": ORIGIN})
        msg = await ws.receive(timeout=5)
        self.assertEqual(msg.type, WSMsgType.CLOSE)
        self.assertEqual(msg.data, web.MACHINE_DOWN)
        self.assertEqual(msg.extra, "eteint est hors ligne.")
        self.assertTrue(self.bridges.connected[0][3].closed)

    async def test_logout_closes_open_websockets(self):
        await self.login()
        ws = await self.client.ws_connect("/api/ws", headers={"Origin": ORIGIN})
        await self.client.post("/api/logout", headers={"Origin": ORIGIN})
        msg = await ws.receive(timeout=5)
        self.assertEqual((msg.type, msg.data), (WSMsgType.CLOSE, 4001))

    async def test_expired_session_closes_websocket(self):
        web.RECHECK_S = 0.05
        self.addCleanup(setattr, web, "RECHECK_S", 300)
        await self.login()
        ws = await self.client.ws_connect("/api/ws", headers={"Origin": ORIGIN})
        self.auth.expired = True
        msg = await ws.receive(timeout=5)
        self.assertEqual((msg.type, msg.data), (WSMsgType.CLOSE, 4001))

    async def test_ws_closed_when_bridge_connection_drops(self):
        """C6 : si la connexion au pont tombe, le WebSocket du navigateur est fermé (il se
        reconnecte) au lieu de rester ouvert sans pont derrière."""
        await self.login()
        ws = await self.client.ws_connect("/api/ws", headers={"Origin": ORIGIN})
        bridge = self.bridges.connected[0][3]
        bridge.lost.set()
        msg = await ws.receive(timeout=5)
        self.assertEqual((msg.type, msg.data), (WSMsgType.CLOSE, web.BRIDGE_LOST))
        for _ in range(50):
            if bridge.closed:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(bridge.closed)

    async def test_ws_oversized_message(self):
        await self.login()
        ws = await self.client.ws_connect("/api/ws", headers={"Origin": ORIGIN})
        await ws.send_str(json.dumps({"id": 1, "method": "x", "params": {"d": "a" * (rpc.MAX_LINE + 10)}}))
        msg = await ws.receive(timeout=10)
        self.assertIn(msg.type, (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR))
        self.assertEqual(ws.close_code, 1009)

    async def test_bearer_app_token(self):
        ws = await self.client.ws_connect("/api/ws", headers={"Authorization": "Bearer APP-1"})
        self.assertEqual(self.bridges.connected[0][:3], ("alice", "T2", session_hash("APP-1")))
        await ws.close()
        r = await self.client.get("/api/ws", headers={"Authorization": "Bearer FAUX"})
        self.assertEqual(r.status, 401)

    async def test_pair_returns_token(self):
        r = await self.client.post("/api/pair", json={"user": "alice", "password": "bon", "code": "1",
                                                      "name": "PC"})
        body = await r.json()
        self.assertEqual(body, {"status": "ok", "user": "alice", "token": "APP-1"})

    async def test_logout_clears_cookie(self):
        await self.login()
        r = await self.client.post("/api/logout", headers={"Origin": ORIGIN})
        self.assertEqual(r.status, 200)
        self.assertIn(("logout", {"session": "SESSION-1"}), self.auth.calls)
        sess = next(c for c in r.headers.getall("Set-Cookie") if c.startswith("ccs_session="))
        self.assertIn("max-age=0", sess.lower())

    async def test_session_endpoint(self):
        r = await self.client.get("/api/session")
        self.assertEqual(r.status, 401)
        await self.login()
        r = await self.client.get("/api/session")
        self.assertEqual(await r.json(), {"user": "alice"})

    async def test_tokens_and_revoke(self):
        await self.login()
        r = await self.client.get("/api/tokens")
        self.assertEqual((await r.json())["tokens"][0]["id"], "abc")
        r = await self.client.post("/api/revoke", json={"token_id": "abc"}, headers={"Origin": ORIGIN})
        self.assertEqual(r.status, 200)
        r = await self.client.post("/api/revoke", json={"token_id": "abc"},
                                   headers={"Origin": "https://ailleurs.example"})
        self.assertEqual(r.status, 403)

    async def test_security_headers_everywhere(self):
        for path in ("/api/health", "/n-existe-pas", "/"):
            r = await self.client.get(path)
            csp = r.headers.get("Content-Security-Policy", "")
            self.assertIn("default-src 'self'", csp, path)
            self.assertIn("frame-ancestors 'none'", csp)
            self.assertIn("script-src 'self'", csp)
            self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(r.headers.get("Referrer-Policy"), "no-referrer")


class ClientIpTest(unittest.TestCase):
    def test_forwarded_for_only_from_localhost(self):
        h = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}
        self.assertEqual(web.client_ip("127.0.0.1", h), "5.6.7.8")
        self.assertEqual(web.client_ip("10.0.0.9", h), "10.0.0.9")
        self.assertEqual(web.client_ip("127.0.0.1", {}), "127.0.0.1")
        self.assertEqual(web.client_ip(None, {}), "?")

    def test_config_defaults(self):
        cfg = web.load_config(path="/nulle/part.json")
        self.assertEqual(cfg, {"listen": "127.0.0.1:8420", "origin": "https://ccs.mawena.cloud"})


if __name__ == "__main__":
    unittest.main()
