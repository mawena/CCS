"""Pont par utilisateur : ticket obligatoire, comptes Claude, réglages, arrêt au repos."""

import hashlib
import hmac
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import settings
from ccs_app.server import bridge, rpc
from ccs_app.server.tokens import session_hash
from tests.helpers import make_home

KEY = b"k" * 32


def ticket(token="jeton-de-session"):
    h = session_hash(token)
    return hmac.new(KEY, h.encode(), hashlib.sha256).hexdigest(), h


class Clock:
    def __init__(self):
        self.t = 1_700_000_000.0

    def __call__(self):
        return self.t


class BridgeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-bridge-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = make_home(self.tmp)
        env = mock.patch.dict(os.environ, {"HOME": str(home)})
        env.start()
        self.addCleanup(env.stop)
        for var in ("CLAUDE_CONFIG_DIR", "CCS_HOME"):
            os.environ.pop(var, None)
        self.clock = Clock()
        self.sock = Path(self.tmp) / "b.sock"

    async def start(self, local=False):
        self.bridge = bridge.Bridge("alice", None if local else KEY, local=local, clock=self.clock,
                                    start_daemon=False, install_claude=False)
        await self.bridge.start(self.sock)
        self.addAsyncCleanup(self.bridge.stop)

    async def client(self, hello=True, **hello_params):
        c = rpc.RpcClient()
        await c.connect_unix(self.sock)
        self.addAsyncCleanup(c.close)
        if hello:
            t, h = ticket()
            await c.call("hello", **(hello_params or {"ticket": t, "session_hash": h}))
        return c

    async def test_hello_required(self):
        await self.start()
        c = await self.client(hello=False)
        with self.assertRaises(rpc.RpcError) as cm:
            await c.call("accounts.state")
        self.assertEqual(cm.exception.code, "refuse")

    async def test_bad_ticket_refused(self):
        await self.start()
        c = await self.client(hello=False)
        _t, h = ticket()
        with self.assertRaises(rpc.RpcError) as cm:
            await c.call("hello", ticket="0" * 64, session_hash=h)
        self.assertEqual(cm.exception.code, "refuse")
        with self.assertRaises(rpc.RpcError):
            await c.call("accounts.state")

    async def test_good_ticket(self):
        await self.start()
        c = await self.client()
        self.assertIn("profiles", await c.call("accounts.state"))

    async def test_local_mode_no_ticket(self):
        await self.start(local=True)
        self.assertEqual(oct(self.sock.stat().st_mode & 0o777), "0o600")
        c = await self.client(hello=False)
        await c.call("hello")
        self.assertIn("profiles", await c.call("accounts.state"))

    async def test_accounts_state_shape(self):
        await self.start()
        c = await self.client()
        st = await c.call("accounts.state")
        self.assertEqual(sorted(p["name"] for p in st["profiles"]), ["perso", "pro"])
        self.assertEqual(st["active"], "perso")
        self.assertIn("state", st)
        self.assertIsNone(st["pause"])
        self.assertEqual(st["user"], "alice")

    async def test_switch_unknown_profile_refused(self):
        await self.start()
        c = await self.client()
        with self.assertRaises(rpc.RpcError) as cm:
            await c.call("accounts.switch", name="inconnu")
        self.assertEqual(cm.exception.code, "invalide")

    async def test_settings_set_validates(self):
        await self.start()
        c = await self.client()
        await c.call("settings.set", path="chat.idle_suspend_min", value=10)
        self.assertEqual(settings.load_settings()["chat"]["idle_suspend_min"], 10)
        with self.assertRaises(rpc.RpcError) as cm:
            await c.call("settings.set", path="chat.idle_suspend_min", value="beaucoup")
        self.assertEqual(cm.exception.code, "invalide")
        with self.assertRaises(rpc.RpcError):
            await c.call("settings.set", path="inexistant.cle", value=1)
        got = await c.call("settings.get")
        self.assertEqual(got["settings"]["chat"]["idle_suspend_min"], 10)

    async def test_pause_set(self):
        await self.start()
        c = await self.client()
        r = await c.call("pause.set", choice="1h")
        self.assertTrue(r["paused"])
        st = await c.call("accounts.state")
        self.assertIsNotNone(st["pause"])
        r = await c.call("pause.set", choice="off")
        self.assertFalse(r["paused"])

    async def test_idle_stop(self):
        await self.start()
        self.assertFalse(self.bridge.should_stop())
        self.clock.t += bridge.IDLE_STOP + 1
        self.assertTrue(self.bridge.should_stop())
        c = await self.client()
        self.assertFalse(self.bridge.should_stop())       # un client connecté
        await c.close()
        self.bridge.busy_checks.append(lambda: True)       # un chat en cours
        self.clock.t += bridge.IDLE_STOP + 1
        self.assertFalse(self.bridge.should_stop())


if __name__ == "__main__":
    unittest.main()
