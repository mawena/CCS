"""Client du pont : socket local (le pont est lancé s'il ne répond pas) ou WebSocket de ccs-web
avec jeton d'application ; reconnexion automatique."""

import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aiohttp.test_utils import TestServer

from ccs_app.remote import client, servers
from ccs_app.server import bridge, rpc, web
from tests.helpers import make_home
from tests.test_server_web import FakeAuth, FakeBridges


class ClientTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-client-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = make_home(self.tmp)
        env = mock.patch.dict(os.environ, {"HOME": str(home)})
        env.start()
        self.addCleanup(env.stop)
        self.sock = Path(self.tmp) / "b.sock"
        self.bridges = []

    async def start_bridge(self):
        b = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
        await b.start(self.sock)
        self.bridges.append(b)
        return b

    async def asyncTearDown(self):
        for b in self.bridges:
            await b.stop()

    async def test_local_transport_starts_bridge(self):
        spawned = []

        def spawn():
            spawned.append(1)
            asyncio.get_running_loop().create_task(self.start_bridge())
        c = client.BridgeClient(client.LocalTransport(self.sock, spawn=spawn))
        await c.connect()
        self.addAsyncCleanup(c.close)
        self.assertEqual(spawned, [1])
        st = await c.call("accounts.state")
        self.assertEqual(st["user"], "alice")

    async def test_reconnect_and_replay(self):
        await self.start_bridge()
        c = client.BridgeClient(client.LocalTransport(self.sock, spawn=lambda: None), retry_delays=(0.05, 0.1))
        events = []
        c.on_state = lambda s: events.append(s)
        await c.connect()
        self.addAsyncCleanup(c.close)
        await self.bridges[0].stop()                      # le pont tombe
        for _ in range(100):
            if "offline" in events:
                break
            await asyncio.sleep(0.02)
        self.assertIn("offline", events)
        with self.assertRaises(rpc.RpcError):
            await c.call("accounts.state")
        await self.start_bridge()                         # il revient
        for _ in range(200):
            if "reconnected" in events:
                break
            await asyncio.sleep(0.02)
        self.assertIn("reconnected", events)
        self.assertEqual((await c.call("accounts.state"))["user"], "alice")

    async def test_web_transport_bearer(self):
        bridges = FakeBridges()
        app = web.make_app(FakeAuth(), bridges, {"listen": "127.0.0.1:1", "origin": "https://x"})
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)
        srv = servers.Server("essai", str(server.make_url("")).rstrip("/"), "alice", "APP-1")
        c = client.BridgeClient(client.WebTransport(srv))
        got = []
        c.on_event = lambda name, data: got.append((name, data))
        await c.connect()
        self.addAsyncCleanup(c.close)
        self.assertEqual(await c.call("accounts.state", a=1), {"echo": {"a": 1}})
        bridges.connected[0][3].on_event("chat.event", {"x": 1})
        for _ in range(100):
            if got:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(got, [("chat.event", {"x": 1})])

    async def test_web_transport_bad_token(self):
        app = web.make_app(FakeAuth(), FakeBridges(), {"listen": "127.0.0.1:1", "origin": "https://x"})
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)
        srv = servers.Server("essai", str(server.make_url("")).rstrip("/"), "alice", "FAUX")
        c = client.BridgeClient(client.WebTransport(srv), retry_delays=())
        with self.assertRaises(client.AuthError):
            await c.connect()


class SyncClientTest(unittest.TestCase):
    def test_sync_client_calls_from_thread(self):
        tmp = tempfile.mkdtemp(prefix="ccs-sync-")
        self.addCleanup(shutil.rmtree, tmp, True)
        home = make_home(tmp)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            sock = Path(tmp) / "b.sock"
            holder = {}

            def spawn():
                async def go():
                    b = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
                    await b.start(sock)
                    holder["b"] = b
                asyncio.get_running_loop().create_task(go())
            c = client.SyncBridgeClient(client.LocalTransport(sock, spawn=spawn), dispatch=lambda fn, *a: fn(*a))
            c.start()
            try:
                self.assertEqual(c.call_sync("accounts.state", timeout=10)["user"], "alice")
                done = []
                c.call("accounts.state", callback=lambda res, err: done.append((res, err)))
                for _ in range(200):
                    if done:
                        break
                    import time
                    time.sleep(0.01)
                self.assertEqual(done[0][0]["user"], "alice")
                self.assertIsNone(done[0][1])
            finally:
                c.stop()


if __name__ == "__main__":
    unittest.main()
