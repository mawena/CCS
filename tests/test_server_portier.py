"""Mode Portier : réglages, en-tête de confiance, ccs-web et ccs-auth.
Faux ccs-auth, faux pont, aucune vraie configuration système."""

import hashlib
import hmac
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from aiohttp import web as aioweb
from aiohttp.test_utils import AioHTTPTestCase

from ccs_app.server import auth, paths, portier, rpc, web
from ccs_app.server.tokens import TokenStore, session_hash

from .test_server_web import ORIGIN, FakeAuth, FakeBridges

CFG = portier.parse({"portier": {"actif": True, "utilisateurs": ["charles"],
                                 "url": "https://portier.mawena.cloud/"}})
HEADER = {portier.HEADER: "charles"}


class PortierFakeAuth(FakeAuth):
    async def call(self, method, **params):
        if method == "portier":
            self.calls.append((method, params))
            if params.get("portier") != "charles":
                raise rpc.RpcError("refuse", "Mode Portier refusé.")
            return {"user": "charles", "token": "portier:X", "ticket": "TP"}
        return await super().call(method, **params)


class ParseTest(unittest.TestCase):
    def test_disabled_by_default(self):
        self.assertFalse(portier.parse({})["actif"])
        self.assertFalse(portier.load("/nulle/part.json")["actif"])
        self.assertFalse(portier.parse({"portier": {"actif": "oui", "utilisateurs": ["a"]}})["actif"])
        self.assertFalse(portier.parse({"portier": {"actif": True, "utilisateurs": []}})["actif"])

    def test_logout_from_url_or_explicit(self):
        self.assertEqual(CFG["deconnexion"], "https://portier.mawena.cloud/")
        cfg = portier.parse({"portier": {"actif": True, "utilisateurs": ["a"], "url": "https://p",
                                         "deconnexion": "https://p/sortie"}})
        self.assertEqual(cfg["deconnexion"], "https://p/sortie")

    def test_load_from_web_json(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"listen": "127.0.0.1:8420", "portier": {"actif": True, "utilisateurs": ["charles"]}}, f)
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(portier.load(f.name)["utilisateurs"], ("charles",))

    def test_login_url_encodes_return(self):
        self.assertEqual(portier.login_url(CFG, ORIGIN),
                         "https://portier.mawena.cloud/connexion?retour=https%3A%2F%2Fccs.mawena.cloud%2F")
        self.assertEqual(portier.login_url(portier.DISABLED, ORIGIN), "")

    def test_trusted_user_rules(self):
        self.assertEqual(portier.trusted_user(CFG, "127.0.0.1", HEADER), "charles")
        self.assertEqual(portier.trusted_user(CFG, "::1", HEADER), "charles")
        self.assertIsNone(portier.trusted_user(CFG, "10.0.0.9", HEADER))            # IP non locale
        self.assertIsNone(portier.trusted_user(CFG, "127.0.0.1", {portier.HEADER: "mallory"}))
        self.assertIsNone(portier.trusted_user(CFG, "127.0.0.1", {}))
        self.assertIsNone(portier.trusted_user(portier.DISABLED, "127.0.0.1", HEADER))


class PortierWebTest(AioHTTPTestCase):
    remote = None            # adresse imposée au client (sinon 127.0.0.1)
    cfg = CFG

    async def get_application(self):
        self.auth = PortierFakeAuth()
        self.bridges = FakeBridges()
        app = web.make_app(self.auth, self.bridges, {"listen": "127.0.0.1:8420", "origin": ORIGIN,
                                                     "portier": self.cfg})
        if self.remote:
            @aioweb.middleware
            async def spoof(request, handler):
                return await handler(request.clone(remote=self.remote))
            app.middlewares.insert(0, spoof)
        return app

    def portier_calls(self):
        return [c for c in self.auth.calls if c[0] == "portier"]


class HeaderAcceptedTest(PortierWebTest):
    async def test_session_without_login_page(self):
        r = await self.client.get("/api/session", headers=HEADER)
        self.assertEqual(r.status, 200)
        self.assertEqual(await r.json(), {"user": "charles", "portier": True})

    async def test_websocket_gets_ticket_from_auth(self):
        ws = await self.client.ws_connect("/api/ws", headers={**HEADER, "Origin": ORIGIN})
        await ws.send_json({"id": 1, "method": "ping", "params": {}})
        self.assertEqual((await ws.receive_json())["id"], 1)
        await ws.close()
        user, ticket, shash, _ = self.bridges.connected[0]
        self.assertEqual((user, ticket, shash), ("charles", "TP", session_hash("portier:X")))

    async def test_logout_redirects_to_portier(self):
        r = await self.client.post("/api/logout", headers=HEADER)
        self.assertEqual(await r.json(), {"redirect": "https://portier.mawena.cloud/"})

    async def test_login_page_offers_portier(self):
        r = await self.client.get("/api/portier")
        self.assertEqual(await r.json(), {"actif": True, "connexion": portier.login_url(CFG, ORIGIN)})

    async def test_tokens_use_portier_identity(self):
        await self.client.get("/api/tokens", headers=HEADER)
        self.assertIn(("tokens", {"portier": "charles"}), self.auth.calls)

    async def test_app_token_wins_over_header(self):
        r = await self.client.get("/api/session", headers={**HEADER, "Authorization": "Bearer APP-1"})
        self.assertEqual(await r.json(), {"user": "alice"})
        self.assertEqual(self.portier_calls(), [])

    async def test_without_header_usual_login(self):
        r = await self.client.get("/api/session")
        self.assertEqual(r.status, 401)


class NameNotListedTest(PortierWebTest):
    async def test_refused_and_auth_not_asked(self):
        r = await self.client.get("/api/session", headers={portier.HEADER: "mallory"})
        self.assertEqual(r.status, 401)
        r = await self.client.post("/api/logout", headers={portier.HEADER: "mallory"})
        self.assertEqual(await r.json(), {})
        self.assertEqual(self.portier_calls(), [])


class RemoteNotLocalTest(PortierWebTest):
    remote = "10.0.0.9"

    async def test_header_ignored(self):
        r = await self.client.get("/api/session", headers=HEADER)
        self.assertEqual(r.status, 401)
        self.assertEqual(self.portier_calls(), [])


class OptionDisabledTest(PortierWebTest):
    cfg = portier.parse({"portier": {"actif": False, "utilisateurs": ["charles"], "url": "https://p"}})

    async def test_header_ignored(self):
        r = await self.client.get("/api/session", headers=HEADER)
        self.assertEqual(r.status, 401)
        self.assertEqual(self.portier_calls(), [])
        r = await self.client.get("/api/portier")
        self.assertEqual(await r.json(), {"actif": False, "connexion": ""})

    async def test_no_portier_key_at_all(self):
        app = web.make_app(self.auth, self.bridges, {"listen": "127.0.0.1:8420", "origin": ORIGIN})
        self.assertIsNotNone(app)


class AuthPortierTest(unittest.IsolatedAsyncioTestCase):
    """ccs-auth revérifie l'option et la liste avant de signer un ticket."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-portier-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"CCS_SERVER_ROOT": self.tmp})
        env.start()
        self.addCleanup(env.stop)
        self.cfg = dict(CFG, utilisateurs=("charles", "bob"))
        self.svc = auth.AuthService(TokenStore(paths.sessions_file()), pam_check=lambda u, p: False,
                                    allowed=lambda u: u == "charles", spawn_bridge=lambda u: None,
                                    refuse_delay=0, chown=lambda path, user: None,
                                    portier_config=lambda: self.cfg)

    async def test_ticket_for_listed_user(self):
        r = await self.svc.portier({"portier": "charles"})
        key = paths.bridge_key("charles").read_bytes()
        self.assertTrue(r["token"].startswith("portier:"))
        self.assertEqual(r["ticket"], hmac.new(key, session_hash(r["token"]).encode(), hashlib.sha256).hexdigest())

    async def test_refusals(self):
        for user in ("mallory", "bob", ""):          # absent de la liste ; hors groupe ccs ; vide
            with self.assertRaises(rpc.RpcError):
                await self.svc.portier({"portier": user})
        self.cfg = portier.DISABLED
        with self.assertRaises(rpc.RpcError):
            await self.svc.portier({"portier": "charles"})

    async def test_tokens_and_app_token_in_portier_mode(self):
        r = await self.svc.app_token({"portier": "charles", "name": "PC"})
        listed = await self.svc.tokens_list({"portier": "charles"})
        self.assertEqual(len(listed["tokens"]), 1)
        self.assertTrue(r["token"])


if __name__ == "__main__":
    unittest.main()
