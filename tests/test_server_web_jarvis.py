"""ccs-web : `/api/jarvis/oreille`, de bout en bout (faux ccs-auth, vrai pont, faux cerveau TLS)."""

import asyncio
import hashlib
import hmac
import json
import os
import shutil
import socket
import struct
import tempfile
from pathlib import Path
from unittest import mock

from aiohttp import WSMsgType
from aiohttp.test_utils import AioHTTPTestCase

from ccs_app.server import bridge, bridge_jarvis, jarvis_link, rpc, web
from tests.helpers import make_home
from tests.jarvis_brain import FakeBrain
from tests.test_server_bridge import KEY
from tests.test_server_web import ORIGIN, FakeAuth


class Connector:
    """Comme `web.BridgeConnector`, vers le pont de l'essai ; le ticket est celui que ccs-auth
    remettrait (HMAC de l'empreinte de session par la clé du pont)."""

    def __init__(self, path):
        self.path = path
        self.clients = []

    async def connect(self, user, ticket, shash, client_protocol=0):
        c = rpc.RpcClient()
        await c.connect_unix(self.path)
        await c.call("hello", ticket=hmac.new(KEY, shash.encode(), hashlib.sha256).hexdigest(),
                     session_hash=shash, protocol=client_protocol)
        self.clients.append(c)
        return c


class JarvisWebTest(AioHTTPTestCase):
    async def get_application(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccs-jarvis-web-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = make_home(str(self.tmp))
        env = mock.patch.dict(os.environ, {"HOME": str(home)})
        env.start()
        self.addCleanup(env.stop)
        for var in ("CLAUDE_CONFIG_DIR", "CCS_HOME"):
            os.environ.pop(var, None)
        self.brain = FakeBrain(self.tmp)
        await self.brain.start()
        self.near = bridge.Bridge("alice", KEY, start_daemon=False, install_claude=False)
        self.api = bridge_jarvis.JarvisApi(self.near, tunnel=self._tunnel, timeout=5)
        await self.near.start(self.tmp / "near.sock")
        self.auth = FakeAuth()
        return web.make_app(self.auth, Connector(self.tmp / "near.sock"),
                            {"listen": "127.0.0.1:8420", "origin": ORIGIN})

    async def asyncTearDown(self):
        await self.near.stop()
        await self.brain.stop()
        await super().asyncTearDown()

    async def _tunnel(self, machine, port):
        if machine == "eteint":
            raise jarvis_link.LinkError("la machine eteint est hors ligne")
        s = socket.create_connection(("127.0.0.1", self.brain.port))
        s.setblocking(False)
        return s, None

    async def login(self):
        r = await self.client.post("/api/login", json={"user": "alice", "password": "bon", "code": "123456"})
        for c in r.headers.getall("Set-Cookie", []):
            name, _, rest = c.partition("=")
            if name == "ccs_session":
                self.client.session.cookie_jar.update_cookies({name: rest.split(";")[0]})

    async def test_requires_session_and_origin(self):
        r = await self.client.get("/api/jarvis/oreille", headers={"Origin": ORIGIN})
        self.assertEqual(r.status, 401)
        await self.login()
        r = await self.client.get("/api/jarvis/oreille", headers={"Origin": "https://ailleurs.example"})
        self.assertEqual(r.status, 403)

    async def test_app_token_is_accepted(self):
        ws = await self.client.ws_connect(f"/api/jarvis/oreille?fp={self.brain.fingerprint}",
                                          headers={"Authorization": "Bearer APP-1"})
        await ws.send_str(json.dumps({"type": "hello", "token": "jeton-oreille"}))
        msg = await ws.receive(timeout=5)
        self.assertEqual(json.loads(msg.data)["type"], "welcome")
        await ws.close()

    async def test_relays_a_phrase_both_ways(self):
        await self.login()
        ws = await self.client.ws_connect(f"/api/jarvis/oreille?fp={self.brain.fingerprint}",
                                          headers={"Origin": ORIGIN})
        await ws.send_str(json.dumps({"type": "hello", "version": 1, "ear_id": "e1", "token": "jeton-oreille"}))
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data)["type"], "welcome")
        await ws.send_str(json.dumps({"type": "wake", "utterance": 7, "score": 2.0, "level_db": 0, "muted": False}))
        await ws.send_bytes(bytes([1]) + struct.pack("<I", 7) + b"\x10\x00" * 16000)
        await ws.send_str(json.dumps({"type": "listen_end", "utterance": 7, "muted": False, "no_speech": False}))
        got = [json.loads((await ws.receive(timeout=5)).data)["type"] for _ in range(2)]
        self.assertEqual(got, ["elected", "response"])
        self.assertEqual(self.brain.samples, 16000)
        await ws.send_str(json.dumps({"type": "binary_back"}))
        msg = await ws.receive(timeout=5)
        self.assertEqual((msg.type, msg.data), (WSMsgType.BINARY, b"\x02abc"))
        await ws.send_str(json.dumps({"type": "bye"}))
        msg = await ws.receive(timeout=5)
        self.assertEqual(msg.type, WSMsgType.CLOSE)
        self.assertEqual(msg.extra, "au revoir")
        self.assertEqual(self.api.links, {})

    async def test_unreachable_brain_gives_a_clear_error(self):
        await self.login()
        await self.near._handlers["jarvis.configure"](None, {"machine": "eteint"})
        ws = await self.client.ws_connect(f"/api/jarvis/oreille?fp={self.brain.fingerprint}",
                                          headers={"Origin": ORIGIN})
        await ws.send_str(json.dumps({"type": "hello"}))
        msg = await ws.receive(timeout=5)
        err = json.loads(msg.data)
        self.assertEqual(err["type"], "relay_error")
        self.assertIn("Jarvis est injoignable (eteint:7341)", err["message"])
        msg = await ws.receive(timeout=5)
        self.assertEqual(msg.type, WSMsgType.CLOSE)
        self.assertEqual(ws.close_code, web.JARVIS_DOWN)

    async def test_oversized_frame_closes_the_ear(self):
        await self.login()
        ws = await self.client.ws_connect(f"/api/jarvis/oreille?fp={self.brain.fingerprint}",
                                          headers={"Origin": ORIGIN})
        await ws.send_str(json.dumps({"type": "hello", "token": "jeton-oreille"}))
        await ws.receive(timeout=5)
        await ws.send_bytes(b"\x01" * (web.JARVIS_MAX_IN + 1))
        msg = await ws.receive(timeout=5)
        self.assertEqual(msg.type, WSMsgType.CLOSE)
        for _ in range(100):
            if not self.api.links and self.brain.closed:
                break
            await asyncio.sleep(0.02)
        self.assertEqual(self.api.links, {})

    async def test_logout_closes_the_ear(self):
        await self.login()
        ws = await self.client.ws_connect(f"/api/jarvis/oreille?fp={self.brain.fingerprint}",
                                          headers={"Origin": ORIGIN})
        await ws.send_str(json.dumps({"type": "hello", "token": "jeton-oreille"}))
        await ws.receive(timeout=5)
        await self.client.post("/api/logout", headers={"Origin": ORIGIN})
        msg = await ws.receive(timeout=5)
        self.assertEqual(msg.type, WSMsgType.CLOSE)
        self.assertEqual(ws.close_code, web.CLOSED_BY_AUTH)
