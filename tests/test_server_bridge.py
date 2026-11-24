"""Pont par utilisateur : ticket obligatoire, comptes Claude, réglages, arrêt au repos."""

import asyncio
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
        self.assertEqual(set(st["colors"]), {"perso", "pro"})
        self.assertEqual(st["home"], os.environ["HOME"])
        self.assertTrue(all(c.startswith("#") and len(c) == 7 for c in st["colors"].values()))

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



class EntryPointTest(unittest.TestCase):
    """`ccs bridge` (service ccs-bridge@ du VPS, ou --local) lance le pont complet : le 15/11, il
    n'avait que les comptes et les réglages (chat, fichiers et terminal : « Méthode inconnue »)."""

    METHODS = ("accounts.state", "settings.get", "chat.open", "chat.send", "projects.list", "files.list",
               "roadmap.read", "tasks.list", "analysis.report", "term.open", "term.input")

    def test_cmd_bridge_serves_every_module(self):
        from ccs_app import cli
        served = []

        async def fake_serve(self_, sock):
            served.append(self_)

        tmp = tempfile.mkdtemp(prefix="ccs-bridge-cli-")
        self.addCleanup(shutil.rmtree, tmp, True)
        args = mock.Mock(local=True, socket=os.path.join(tmp, "run", "bridge.sock"))
        with mock.patch.object(bridge.Bridge, "serve", fake_serve), \
                mock.patch.dict(os.environ, {"HOME": tmp}):
            self.assertEqual(cli.cmd_bridge(args), 0)
        names = set(served[0].handlers())
        for m in self.METHODS:
            self.assertIn(m, names)

    def test_build_attaches_every_hub(self):
        b = bridge.build("alice", KEY, start_daemon=False, install_claude=False)
        self.assertEqual(set(b.hubs), {"chat", "data", "term", "work", "admin", "git", "files", "machines",
                                  "root", "network", "jarvis", "pilot", "audio"})

    def test_build_passes_chat_options(self):
        b = bridge.build("alice", KEY, start_daemon=False, install_claude=False,
                         chat={"claude": "/faux/claude"})
        self.assertIn("term.open", b.handlers())
        hub = b._handlers["chat.open"].__self__
        self.assertEqual(hub.claude, "/faux/claude")


class Proc:
    def __init__(self):
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


class PrepareTest(unittest.IsolatedAsyncioTestCase):
    def make(self, pid, installed=True):
        self.started = []
        self.installs = []

        def popen(argv, **kw):
            self.started.append(argv)
            self.proc = Proc()
            return self.proc
        installer = mock.Mock()
        installer.installed.return_value = installed
        installer.install.side_effect = lambda: (self.installs.append(1), (True, "ok"))[1]
        return bridge.Bridge("alice", KEY, popen=popen, daemon_pid=lambda: pid, installer=installer)

    async def test_bridge_starts_daemon_when_absent(self):
        b = self.make(None)
        await b.prepare()
        self.assertEqual(self.started[0][-1], "daemon")
        await b.stop()
        self.assertTrue(self.proc.terminated)

    async def test_bridge_leaves_running_daemon(self):
        b = self.make(4242)
        await b.prepare()
        self.assertEqual(self.started, [])
        await b.stop()

    async def test_installs_claude_when_missing_and_notifies(self):
        b = self.make(4242, installed=False)
        notices = []

        async def broadcast(event, data):
            notices.append((event, data["text"]))
        b.broadcast = broadcast
        await b.prepare()
        for _ in range(100):
            if len(notices) >= 2:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(self.installs, [1])
        self.assertEqual([e for e, _ in notices], ["notice", "notice"])
        self.assertIn("Claude Code", notices[0][1])
        await b.stop()

    async def test_nothing_when_disabled(self):
        b = bridge.Bridge("alice", KEY, start_daemon=False, install_claude=False,
                          popen=lambda *a, **k: self.fail("lancé"), daemon_pid=lambda: None)
        await b.prepare()
        await b.stop()


if __name__ == "__main__":
    unittest.main()
