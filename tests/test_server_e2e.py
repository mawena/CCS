"""Bout en bout : vrais ccs-auth, pont et ccs-web reliés par leurs sockets Unix.
Seuls PAM (mot de passe) et systemd (démarrage du pont) sont simulés."""

import asyncio
import os
import shutil
import tempfile
from unittest import mock

import pyotp
from aiohttp.test_utils import AioHTTPTestCase

from ccs_app.server import auth, bridge, paths, rpc, web
from ccs_app.server.tokens import TokenStore
from tests.helpers import make_home

ORIGIN = "https://ccs.mawena.cloud"


class EndToEndTest(AioHTTPTestCase):
    async def get_application(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-e2e-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = make_home(self.tmp)
        env = mock.patch.dict(os.environ, {"CCS_SERVER_ROOT": self.tmp, "HOME": str(home)})
        env.start()
        self.addCleanup(env.stop)
        loop = asyncio.get_running_loop()
        self.bridges = []

        async def start_bridge(user):
            b = bridge.Bridge(user, paths.bridge_key(user).read_bytes(), start_daemon=False,
                              install_claude=False)
            await b.start(paths.bridge_socket(user))
            self.bridges.append(b)

        svc = auth.AuthService(TokenStore(paths.sessions_file()),
                               pam_check=lambda u, p: (u, p) == ("alice", "bon"),
                               allowed=lambda u: u == "alice",
                               spawn_bridge=lambda u: asyncio.run_coroutine_threadsafe(start_bridge(u), loop).result(5),
                               refuse_delay=0, chown=lambda *_: None)
        self.auth_server = rpc.RpcServer(svc.handlers())
        await self.auth_server.start_unix(paths.auth_socket(), 0o600)
        return web.make_app(web.AuthClient(), web.BridgeConnector(), {"listen": "127.0.0.1:8420", "origin": ORIGIN})

    async def asyncTearDown(self):
        for b in self.bridges:
            await b.stop()
        await self.auth_server.close()
        await super().asyncTearDown()

    async def post(self, path, data):
        r = await self.client.post(path, json=data, headers={"Origin": ORIGIN})
        for c in r.headers.getall("Set-Cookie", []):
            name, _, rest = c.partition("=")
            if name.startswith("ccs_"):
                self.client.session.cookie_jar.update_cookies({name: rest.split(";")[0]})
        return await r.json()

    async def test_login_enroll_then_drive_bridge(self):
        r = await self.post("/api/login", {"user": "alice", "password": "bon"})
        self.assertEqual(r["status"], "enroll")
        r = await self.post("/api/enroll", {"pending": r["pending"], "code": pyotp.TOTP(r["secret"]).now()})
        self.assertEqual(r, {"status": "ok", "user": "alice"})
        ws = await self.client.ws_connect("/api/ws", headers={"Origin": ORIGIN})
        await ws.send_json({"id": 1, "method": "accounts.state", "params": {}})
        msg = await ws.receive_json(timeout=10)
        self.assertEqual(msg["result"]["user"], "alice")
        self.assertEqual(sorted(p["name"] for p in msg["result"]["profiles"]), ["perso", "pro"])
        await ws.close()

    async def test_forged_ticket_rejected_by_bridge(self):
        r = await self.post("/api/login", {"user": "alice", "password": "bon"})
        await self.post("/api/enroll", {"pending": r["pending"], "code": pyotp.TOTP(r["secret"]).now()})
        c = rpc.RpcClient()
        await c.connect_unix(paths.bridge_socket("alice"))
        with self.assertRaises(rpc.RpcError):
            await c.call("hello", ticket="0" * 64, session_hash="a" * 64)
        await c.close()
