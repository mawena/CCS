"""Pont : `root.ask` diffusé, `root.answer` vérifié (faux sudo), `root.resolved`, `root.used`, avis
ntfy sans secret avec « Révoquer », relais d'un second pont. Aucun vrai sudo ni réseau."""

import asyncio
import base64
import logging
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import root_keeper as rk
from ccs_app.server import bridge, bridge_root, rpc

GOOD = "Bon-Mot-De-Passe-42"
SETTINGS = {"phone": {"enabled": True, "server": "https://ntfy.example.org",
                      "topic": "ccs-canal-principal-123", "reply_topic": "ccs-reponses-secretes-456",
                      "show_content": True}}


def verify(secret):
    return bytes(secret.view()) == GOOD.encode()


class FakeListener:
    made = []

    def __init__(self, cfg, topic, on_body):
        self.topic, self.on_body, self.stopped = topic, on_body, False
        FakeListener.made.append(self)

    def start(self):
        pass

    def stop(self):
        self.stopped = True


def decode(header):
    m = re.fullmatch(r"=\?UTF-8\?B\?(.+)\?=", header)
    return base64.b64decode(m.group(1)).decode() if m else header


class RootBridgeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-root-bridge-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.tmp})
        env.start()
        self.addCleanup(env.stop)
        self.sent = []
        FakeListener.made = []

    async def make_bridge(self, name, show_content=True):
        b = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
        s = {"phone": dict(SETTINGS["phone"], show_content=show_content)}
        api = bridge_root.RootApi(
            b, keeper=rk.Keeper(machine="vps", verify=verify), run=lambda work: work(),
            urlopen=self.urlopen, listener_factory=FakeListener, load_settings=lambda: s)
        sock = Path(self.tmp) / f"{name}.sock"
        await b.start(sock)
        await api.start()
        self.addAsyncCleanup(b.stop)
        c = rpc.RpcClient()
        await c.connect_unix(sock)
        self.addAsyncCleanup(c.close)
        await c.call("hello")
        c.got = []
        c.on_event = lambda ev, data: c.got.append((ev, data))
        return b, api, c

    def urlopen(self, req, timeout=None):
        self.sent.append(req)

        class Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return Resp()

    async def wait_for(self, c, name, n=1):
        for _ in range(200):
            if len([e for e, _ in c.got if e == name]) >= n:
                return [d for e, d in c.got if e == name]
            await asyncio.sleep(0.01)
        self.fail(f"événement {name} absent : {c.got}")

    async def test_full_flow(self):
        b, api, c = await self.make_bridge("a")
        self.assertTrue(api.owner)
        with self.assertLogs("ccs", level=logging.DEBUG) as logs:
            fetch = asyncio.ensure_future(asyncio.to_thread(rk.fetch_password, "apt update", 10))
            ask = (await self.wait_for(c, "root.ask"))[0]
            self.assertEqual(set(ask), {"id", "machine", "command", "expires_at", "tries_left"})
            self.assertEqual(ask["command"], "apt update")
            self.assertTrue(b.should_stop() is False)
            # avis sans secret, avec la commande (show_content)
            body = self.sent[0].data.decode()
            self.assertEqual(body, "vps demande le mot de passe root pour : apt update")
            # mauvais mot de passe : root.ask de nouveau avec une erreur
            res = await c.call("root.answer", id=ask["id"], password="faux")
            self.assertFalse(res["ok"])
            again = (await self.wait_for(c, "root.ask", 2))[1]
            self.assertIn("error", again)
            self.assertEqual(len(self.sent), 1)                 # pas de second avis
            with self.assertRaises(rpc.RpcError) as cm:
                await c.call("root.answer", id="autre", password=GOOD)
            self.assertEqual(cm.exception.code, "introuvable")
            self.assertEqual(await c.call("root.answer", id=ask["id"], password=GOOD), {"ok": True})
            self.assertEqual((await self.wait_for(c, "root.resolved"))[0], {"id": ask["id"], "ok": True})
            (await fetch).wipe()
            st = await c.call("root.status")
            self.assertTrue(st["kept"])
            self.assertGreater(st["remaining"], 3500)
            # commande suivante : mot de passe gardé, root.used et avis avec « Révoquer »
            (await asyncio.to_thread(rk.fetch_password, "systemctl status nginx", 10)).wipe()
            used = (await self.wait_for(c, "root.used"))[0]
            self.assertEqual(used["command"], "systemctl status nginx")
            self.assertEqual(set(used), {"machine", "command", "at"})
            req = self.sent[-1]
            self.assertEqual(req.data.decode(), "vps a lancé en root : systemctl status nginx")
            actions = decode(req.headers["Actions"])
            self.assertIn("Révoquer", actions)
            m = re.search(r"body=revoke (\S+) (\S+),", actions)
            listener = FakeListener.made[0]
            # un faux jeton ne révoque rien, le bon une seule fois
            listener.on_body(f"revoke {m.group(1)} mauvais")
            listener.on_body(f"allow {m.group(1)} {m.group(2)}")
            await asyncio.sleep(0.02)
            self.assertTrue(api.keeper.kept())
            listener.on_body(f"revoke {m.group(1)} {m.group(2)}")
            forgotten = (await self.wait_for(c, "root.forgotten"))[0]
            self.assertEqual(forgotten["reason"], "revoke")
            self.assertFalse((await c.call("root.status"))["kept"])
            self.assertTrue(listener.stopped)
        text = "\n".join(logs.output)
        self.assertNotIn(GOOD, text)
        self.assertNotIn(GOOD, repr(c.got))
        for r in self.sent:
            self.assertNotIn(GOOD, r.data.decode())
            self.assertNotIn(GOOD, repr(r.headers))

    async def test_hidden_command_and_forget(self):
        _b, api, c = await self.make_bridge("a", show_content=False)
        fetch = asyncio.ensure_future(asyncio.to_thread(rk.fetch_password, "cat /etc/shadow", 10))
        ask = (await self.wait_for(c, "root.ask"))[0]
        self.assertEqual(self.sent[0].data.decode(), "vps demande le mot de passe root")
        self.assertEqual(await c.call("root.forget"), {"had": False})
        self.assertIsNone(await fetch)
        self.assertEqual((await self.wait_for(c, "root.resolved"))[0], {"id": ask["id"], "ok": False})

    async def test_three_tries_through_bridge(self):
        _b, _api, c = await self.make_bridge("a")
        fetch = asyncio.ensure_future(asyncio.to_thread(rk.fetch_password, "reboot", 10))
        rid = (await self.wait_for(c, "root.ask"))[0]["id"]
        for _ in range(3):
            self.assertFalse((await c.call("root.answer", id=rid, password="faux"))["ok"])
        self.assertIsNone(await fetch)
        self.assertEqual((await self.wait_for(c, "root.resolved"))[0], {"id": rid, "ok": False})

    async def test_second_bridge_relays(self):
        _b1, api1, c1 = await self.make_bridge("a")
        _b2, api2, c2 = await self.make_bridge("b")
        self.assertTrue(api1.owner)
        self.assertFalse(api2.owner)
        await asyncio.sleep(0.05)                           # le relais s'abonne
        fetch = asyncio.ensure_future(asyncio.to_thread(rk.fetch_password, "apt update", 10))
        ask = (await self.wait_for(c2, "root.ask"))[0]       # vu par les clients du second pont
        self.assertEqual((await c2.call("root.status"))["pending"]["id"], ask["id"])
        self.assertEqual(await c2.call("root.answer", id=ask["id"], password=GOOD), {"ok": True})
        (await fetch).wipe()
        await self.wait_for(c1, "root.resolved")
        await self.wait_for(c2, "root.resolved")
        self.assertTrue(api1.keeper.kept())
        self.assertEqual(await c2.call("root.forget"), {"had": True})
        self.assertFalse(api1.keeper.kept())

    async def test_stop_wipes(self):
        b, api, _c = await self.make_bridge("a")
        api.keeper.store(rk.to_secret(GOOD))
        buf = api.keeper._secret._buf
        await b.stop()
        self.assertEqual(len(buf), 0)
        self.assertFalse(os.path.exists(api.server.path))

    def test_build_registers_methods(self):
        b = bridge.build("alice", None, local=True, start_daemon=False, install_claude=False)
        for m in ("root.answer", "root.status", "root.forget"):
            self.assertIn(m, b.handlers())


if __name__ == "__main__":
    unittest.main()
