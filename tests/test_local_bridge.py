"""Chats du bureau par le pont local (phase 33, tâche 4 bis) : connexion partagée et repli,
fermeture d'un onglet (détacher ou fermer), relance du pont quand CCS est mis à jour."""

import asyncio
import os
import shutil
import signal
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ccs_app import chat_engine, chat_protocol as proto
from ccs_app.chat_options import ChatOptions
from ccs_app.remote import client, engine
from ccs_app.server import bridge, bridge_chat, rpc
from tests.helpers import make_home

ROOT = Path(__file__).resolve().parent
FAKE = str(ROOT / "fake_claude.py")
SCEN = str(ROOT / "fixtures" / "chat" / "permissions-allow-toujours.jsonl")


def until(pred, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


class Collector:
    def __init__(self):
        self.events, self.cond = [], threading.Condition()

    def __call__(self, ev):
        with self.cond:
            self.events.append(ev)
            self.cond.notify_all()

    def wait(self, kind, timeout=20):
        with self.cond:
            return self.cond.wait_for(lambda: any(isinstance(e, kind) for e in self.events), timeout)


class LocalBridgeCase(unittest.TestCase):
    """Un vrai pont (faux claude) sur un socket temporaire, lancé par le transport local au
    premier contact, comme `ccs bridge --local` lancé par le bureau."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-lbr-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = make_home(self.tmp)
        env = mock.patch.dict(os.environ, {"HOME": str(home)})
        env.start()
        self.addCleanup(env.stop)
        for var in ("CLAUDE_CONFIG_DIR", "CCS_HOME", "CCS_CHAT_IN_PROCESS"):
            os.environ.pop(var, None)
        self.project = home / "projet"
        self.project.mkdir()
        self.sock = Path(self.tmp) / "b.sock"
        self.environ = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "FAKE_CLAUDE_SCENARIO": SCEN}
        self.spawned = 0
        self.hub = None
        saved = dict(engine._CONNECTIONS)
        engine._CONNECTIONS.clear()
        engine._local_failed_at = None
        self.addCleanup(self.restore, saved)

    def restore(self, saved):
        conn = engine._CONNECTIONS.pop(engine.LOCAL, None)
        if conn is not None:
            if self.hub is not None:
                try:
                    asyncio.run_coroutine_threadsafe(self.hub.close_all(), conn.client.loop).result(10)
                except Exception:
                    pass
            conn.client.stop()
        engine._CONNECTIONS.clear()
        engine._CONNECTIONS.update(saved)
        engine._local_failed_at = None

    def transport(self):
        def spawn():
            self.spawned += 1

            async def go():
                b = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
                self.hub = bridge_chat.ChatHub(b, claude=FAKE, environ=self.environ)
                await b.start(self.sock)
            asyncio.get_running_loop().create_task(go())
        return client.LocalTransport(self.sock, spawn=spawn)

    def second_client(self):
        """Un autre appareil (le web par `machines.attach`) sur le même pont."""
        sync = client.SyncBridgeClient(client.LocalTransport(self.sock, spawn=None), dispatch=lambda fn, *a: fn(*a))
        sync.start()
        self.addCleanup(sync.stop)
        sync._connected.result(10)
        return sync


class LocalConnectionTest(LocalBridgeCase):
    def test_shared_connection_launches_the_bridge_once(self):
        conn = engine.local_connection(lambda fn, *a: fn(*a), transport=self.transport())
        self.assertIsNotNone(conn)
        self.assertTrue(conn.local)
        self.assertIs(engine.local_connection(lambda fn, *a: fn(*a)), conn)
        self.assertEqual(self.spawned, 1)
        self.assertEqual(engine.local_chats(), [])

    def test_fallback_when_the_bridge_does_not_start(self):
        dead = client.LocalTransport(self.sock, spawn=lambda: None, timeout=0.3)
        self.assertIsNone(engine.local_connection(lambda fn, *a: fn(*a), transport=dead, timeout=5))
        # échec retenu : pas de nouvel essai (ni d'attente) avant LOCAL_RETRY_S
        other = mock.Mock()
        self.assertIsNone(engine.local_connection(lambda fn, *a: fn(*a), transport=other))
        other.connect.assert_not_called()
        self.assertEqual(engine.local_chats(), [])

    def test_in_process_by_environment(self):
        with mock.patch.dict(os.environ, {"CCS_CHAT_IN_PROCESS": "1"}):
            self.assertIsNone(engine.local_connection(lambda fn, *a: fn(*a), transport=self.transport()))
        self.assertEqual(self.spawned, 0)


class LocalChatTest(LocalBridgeCase):
    def setUp(self):
        super().setUp()
        self.conn = engine.local_connection(lambda fn, *a: fn(*a), transport=self.transport())
        self.assertIsNotNone(self.conn)

    def start_chat(self):
        col = Collector()
        eng = engine.RemoteChatEngine(self.conn, str(self.project), None, ChatOptions(), on_event=col,
                                      close_on_stop=True)
        self.assertTrue(eng.send("bonjour"))
        self.assertTrue(col.wait(proto.PermissionRequest))
        self.assertTrue(until(lambda: eng.chat_id is not None))
        return eng, col

    def test_chat_runs_in_the_bridge_and_closes_with_its_tab(self):
        eng, _col = self.start_chat()
        listed = engine.local_chats()
        self.assertEqual([c["chat_id"] for c in listed], [eng.chat_id])
        self.assertIn("pid", listed[0])
        eng.stop()
        self.assertTrue(until(lambda: not self.hub.chats))

    def test_chat_followed_elsewhere_survives_its_tab(self):
        eng, _col = self.start_chat()
        other = self.second_client()
        other.call_sync("chat.attach", chat_id=eng.chat_id, since=0)
        eng.stop()
        time.sleep(0.5)
        self.assertIn(eng.chat_id, self.hub.chats)                 # le web le suit encore
        self.assertEqual(len(self.hub.chats[eng.chat_id].conns), 1)  # le bureau s'est détaché

    def test_quitting_the_app_only_detaches(self):
        eng, _col = self.start_chat()
        eng.detach()
        time.sleep(0.3)
        self.assertIn(eng.chat_id, self.hub.chats)

    def test_message_reopens_a_chat_closed_elsewhere(self):
        eng, col = self.start_chat()
        req = next(e for e in col.events if isinstance(e, proto.PermissionRequest))
        eng.answer(req.request_id, "allow")
        self.assertTrue(until(lambda: eng.state == "idle"))
        old = eng.chat_id
        other = self.second_client()
        other.call_sync("chat.close", chat_id=old)
        self.assertTrue(until(lambda: old not in self.hub.chats))
        sid = eng.session_id
        self.assertTrue(eng.send("encore"))
        self.assertTrue(until(lambda: eng.chat_id not in (None, old)))
        self.assertTrue(until(lambda: any(c.engine.session_id == sid for c in self.hub.chats.values())))

    def test_send_if_idle_only_between_turns(self):
        eng = engine.RemoteChatEngine(self.conn, str(self.project), None, ChatOptions(), close_on_stop=True)
        self.assertFalse(eng.send_if_idle("/compact"))            # pas de chat ouvert
        eng.chat_id, eng.state = "c1", "busy"
        self.assertFalse(eng.send_if_idle("/compact"))
        eng._stopped = True


class Conn:
    closed = False


class CloseSharedTest(unittest.IsolatedAsyncioTestCase):
    async def test_keep_if_shared(self):
        b = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
        hub = bridge_chat.ChatHub(b)
        stopped = []
        me, web = Conn(), Conn()
        chat = bridge_chat._Chat("c1", "/tmp")
        chat.engine = SimpleNamespace(stop=lambda: stopped.append(1))
        chat.conns |= {me, web}
        hub.chats["c1"] = chat
        r = await hub.close(me, {"chat_id": "c1", "keep_if_shared": True})
        self.assertEqual(r, {"closed": False, "devices": 1})
        self.assertEqual(chat.conns, {web})
        self.assertFalse(stopped)
        web.closed = True                                   # l'autre appareil est parti
        chat.conns.add(me)
        r = await hub.close(me, {"chat_id": "c1", "keep_if_shared": True})
        self.assertEqual(r, {"closed": True})
        self.assertEqual(stopped, [1])
        self.assertNotIn("c1", hub.chats)

    async def test_stop_closes_every_chat(self):
        b = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
        hub = bridge_chat.ChatHub(b)
        stopped = []
        chat = bridge_chat._Chat("c1", "/tmp")
        chat.engine = SimpleNamespace(stop=lambda: stopped.append(1))
        hub.chats["c1"] = chat
        await b.stop()
        self.assertEqual(stopped, [1])
        self.assertEqual(hub.chats, {})

    async def test_idle_chats_are_suspended(self):
        b = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
        hub = bridge_chat.ChatHub(b)
        self.assertIn(hub.suspend_pass, b.tick_hooks)
        seen = []
        chat = bridge_chat._Chat("c1", "/tmp")
        chat.engine = SimpleNamespace(suspend_if_idle=lambda now, idle: seen.append(idle) or True)
        hub.chats["c1"] = chat
        with mock.patch.object(hub, "_settings", return_value={"chat": {"idle_suspend_min": 30}}):
            await hub.suspend_pass(now=1000)
        self.assertEqual(seen, [1800])
        with mock.patch.object(hub, "_settings", return_value={"chat": {"idle_suspend_min": 0}}):
            await hub.suspend_pass(now=1000)
        self.assertEqual(seen, [1800])                      # 0 : jamais


class RestartOnUpdateTest(unittest.TestCase):
    def make(self, on_disk, local=True):
        return bridge.Bridge("alice", None, local=local, start_daemon=False, install_claude=False,
                             version_on_disk=lambda: on_disk)

    def test_restart_when_installed_version_changed_and_idle(self):
        self.assertTrue(self.make("99.0.0").should_restart())
        self.assertFalse(self.make(bridge.__version__).should_restart())
        self.assertFalse(self.make(None).should_restart())             # fichier illisible
        self.assertTrue(self.make("99.0.0", local=False).should_restart())    # service du serveur aussi
        busy = self.make("99.0.0")
        busy.busy_checks.append(lambda: True)                          # un chat travaille
        self.assertFalse(busy.should_restart())
        term = self.make("99.0.0")
        term.restart_checks.append(lambda: True)                       # un terminal du pont ouvert
        self.assertFalse(term.should_restart())

    def test_open_terminal_holds_the_restart(self):
        b = bridge.build("alice", None, local=True, start_daemon=False, install_claude=False,
                         version_on_disk=lambda: "99.0.0")
        self.assertTrue(b.should_restart())
        b.hubs["term"].terms["t1"] = SimpleNamespace(closed=False)
        self.assertFalse(b.should_restart())
        b.hubs["term"].terms.clear()
        b.hubs["work"].shells["r1"] = object()                          # commande `!` en cours
        self.assertFalse(b.should_restart())

    def test_installed_version_reads_the_file_on_disk(self):
        tmp = tempfile.mkdtemp(prefix="ccs-ver-")
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "__init__.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write('"""CCS."""\n\n__version__ = "1.2.3"\n')
        self.assertEqual(bridge.installed_version(path), "1.2.3")
        self.assertIsNone(bridge.installed_version(os.path.join(tmp, "absent.py")))
        self.assertEqual(bridge.installed_version(), bridge.__version__)

    def test_serve_stops_to_restart(self):
        tmp = tempfile.mkdtemp(prefix="ccs-rst-")
        self.addCleanup(shutil.rmtree, tmp, True)
        b = self.make("99.0.0")

        async def no_wait(aw, timeout):         # la minute du ménage passe tout de suite
            aw.close()
            raise asyncio.TimeoutError
        with mock.patch.object(bridge.asyncio, "wait_for", no_wait), \
                mock.patch.dict(os.environ, {"HOME": tmp}):
            asyncio.run(b.serve(os.path.join(tmp, "b.sock")))
        self.assertTrue(b.restart)

    def test_sigterm_stops_cleanly_with_stop_hooks(self):
        """SIGTERM (systemctl stop) : arrêt propre, les stop_hooks passent (chats enregistrés)."""
        tmp = tempfile.mkdtemp(prefix="ccs-term-")
        self.addCleanup(shutil.rmtree, tmp, True)
        b = self.make(bridge.__version__)
        stopped = []

        async def hook():
            stopped.append(True)
        b.stop_hooks.append(hook)

        async def main():
            task = asyncio.ensure_future(b.serve(os.path.join(tmp, "b.sock")))
            for _ in range(200):
                if b._server is not None and not b.preparing:
                    break
                await asyncio.sleep(0.01)
            if signal.getsignal(signal.SIGTERM) in (signal.SIG_DFL, None):
                task.cancel()
                self.skipTest("gestionnaire de SIGTERM non posé (hors du fil principal)")
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.wait_for(task, 5)
        with mock.patch.dict(os.environ, {"HOME": tmp}):
            asyncio.run(main())
        self.assertEqual(stopped, [True])
        self.assertFalse(b.restart)
        self.assertEqual(signal.getsignal(signal.SIGTERM), signal.SIG_DFL)   # gestionnaire retiré

    def test_cli_execs_the_new_code(self):
        from ccs_app import cli

        async def fake_serve(self_, sock):
            self_.restart = True
        tmp = tempfile.mkdtemp(prefix="ccs-rcli-")
        self.addCleanup(shutil.rmtree, tmp, True)
        sock = os.path.join(tmp, "run", "bridge.sock")
        args = mock.Mock(local=True, socket=sock)
        with mock.patch.object(bridge.Bridge, "serve", fake_serve), \
                mock.patch.dict(os.environ, {"HOME": tmp, "CCS_BIN": "/opt/ccs"}), \
                mock.patch.object(os, "execv") as execv:
            cli.cmd_bridge(args)
        execv.assert_called_once_with("/opt/ccs", ["/opt/ccs", "bridge", "--local", "--socket", sock])

    def test_cli_execs_the_server_bridge_without_local(self):
        """Pont du serveur (service ccs-bridge@) : relancé avec ses arguments, sans --local."""
        from ccs_app import cli
        from ccs_app.server import paths

        async def fake_serve(self_, sock):
            self_.restart = True
        tmp = tempfile.mkdtemp(prefix="ccs-rcli-")
        self.addCleanup(shutil.rmtree, tmp, True)
        key = os.path.join(tmp, "bridge.key")
        with open(key, "wb") as f:
            f.write(b"k" * 32)
        sock = os.path.join(tmp, "bridge.sock")
        args = mock.Mock(local=False, socket=sock)
        with mock.patch.object(bridge.Bridge, "serve", fake_serve), \
                mock.patch.object(paths, "bridge_key", lambda user: Path(key)), \
                mock.patch.dict(os.environ, {"HOME": tmp, "CCS_BIN": "/opt/ccs"}), \
                mock.patch.object(os, "execv") as execv:
            cli.cmd_bridge(args)
        execv.assert_called_once_with("/opt/ccs", ["/opt/ccs", "bridge", "--socket", sock])


class OutdatedBridgeTest(unittest.IsolatedAsyncioTestCase):
    """Pont d'avant la relance automatique (0.37.0 et plus ancien) : le client le remplace."""

    def make(self, chats, version="1.0.0"):
        kills = []
        t = client.LocalTransport("/nulle/part.sock", spawn=lambda: None, version=version,
                                  kill=lambda pid, sig: kills.append((pid, sig)))

        async def no_bridge():
            raise FileNotFoundError
        t._open = no_bridge
        fake = SimpleNamespace(call=mock.AsyncMock(return_value={"chats": chats}))
        return t, fake, kills

    async def test_older_idle_bridge_is_replaced(self):
        t, fake, kills = self.make([{"state": "idle"}, {"state": "suspended"}])
        with mock.patch.object(client, "peer_pid", return_value=4242):
            self.assertTrue(await t.outdated(fake, SimpleNamespace(writer=None), {"version": "0.37.0"}))
        self.assertEqual(kills, [(4242, signal.SIGTERM)])
        self.assertIsNone(t._spawned_at)                    # le prochain contact lance un pont neuf
        with mock.patch.object(client, "peer_pid", return_value=4242):  # une fois par transport
            self.assertFalse(await t.outdated(fake, SimpleNamespace(writer=None), {"version": "0.37.0"}))

    async def test_busy_or_recent_bridge_is_kept(self):
        t, fake, kills = self.make([{"state": "busy"}])
        with mock.patch.object(client, "peer_pid", return_value=4242):
            self.assertFalse(await t.outdated(fake, SimpleNamespace(writer=None), {"version": "0.37.0"}))
            t2, fake2, kills2 = self.make([])
            self.assertFalse(await t2.outdated(fake2, None, {"version": "1.0.0"}))
            self.assertFalse(await t2.outdated(fake2, None, {"version": "2.0.0"}))
            self.assertFalse(await t2.outdated(fake2, None, {}))
        self.assertEqual(kills + kills2, [])

    async def test_bridge_with_an_open_terminal_is_kept(self):
        t, fake, kills = self.make([])

        async def call(method, **_params):
            return {"chats": []} if method == "chat.list" else {"terms": [{"term_id": "t1"}]}
        fake.call = call
        with mock.patch.object(client, "peer_pid", return_value=4242):
            self.assertFalse(await t.outdated(fake, SimpleNamespace(writer=None), {"version": "0.37.0"}))
        self.assertEqual(kills, [])

    def test_version_tuple(self):
        self.assertEqual(client.version_tuple("0.37.0"), (0, 37, 0))
        self.assertLess(client.version_tuple("0.37.0"), client.version_tuple("1.0.0"))
        self.assertIsNone(client.version_tuple("dev"))

    async def test_respawn_after_a_while(self):
        now = [100.0]
        spawned = []
        t = client.LocalTransport("/nulle/part.sock", spawn=lambda: spawned.append(1), timeout=0.2,
                                  clock=lambda: now[0])
        with self.assertRaises(ConnectionError):
            await t.connect()
        with self.assertRaises(ConnectionError):
            await t.connect()                               # lancé à l'instant : pas un second
        self.assertEqual(spawned, [1])
        now[0] += client.RESPAWN_S + 1                      # le pont est mort depuis : relancé
        with self.assertRaises(ConnectionError):
            await t.connect()
        self.assertEqual(spawned, [1, 1])


if __name__ == "__main__":
    unittest.main()
