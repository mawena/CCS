"""Moteur de chat distant : mêmes méthodes et mêmes événements que le moteur local, à travers
un vrai pont (faux claude). Relais du shell distant."""

import asyncio
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import chat_engine, chat_protocol as proto
from ccs_app.chat_options import ChatOptions
from ccs_app.remote import client, engine, shell
from ccs_app.server import bridge, bridge_chat, bridge_term
from tests.helpers import make_home

ROOT = Path(__file__).resolve().parent
FAKE = str(ROOT / "fake_claude.py")
SCEN = str(ROOT / "fixtures" / "chat" / "permissions-allow-toujours.jsonl")


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


class RemoteEngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-reng-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = make_home(self.tmp)
        env = mock.patch.dict(os.environ, {"HOME": str(home)})
        env.start()
        self.addCleanup(env.stop)
        self.project = home / "projet"            # chat.open : dossiers permis (HOME…)
        self.project.mkdir()
        sock = Path(self.tmp) / "b.sock"
        environ = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "FAKE_CLAUDE_SCENARIO": SCEN}

        def spawn():
            async def go():
                b = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
                self.hub = bridge_chat.ChatHub(b, claude=FAKE, environ=environ)
                await b.start(sock)
            asyncio.get_running_loop().create_task(go())
        self.sync = client.SyncBridgeClient(client.LocalTransport(sock, spawn=spawn), dispatch=lambda fn, *a: fn(*a))
        self.conn = engine.RemoteConnection(self.sync, "essai")
        self.sync.start()
        self.addCleanup(self.stop)

    def stop(self):
        try:
            asyncio.run_coroutine_threadsafe(self.hub.close_all(), self.sync.loop).result(10)
        except Exception:
            pass
        self.sync.stop()

    def test_remote_engine_same_events_as_local(self):
        col = Collector()
        eng = engine.RemoteChatEngine(self.conn, str(self.project), None, ChatOptions(), on_event=col)
        self.assertEqual(eng.state, "stopped")
        self.assertTrue(eng.send("bonjour"))
        self.assertTrue(col.wait(proto.PermissionRequest))
        req = next(e for e in col.events if isinstance(e, proto.PermissionRequest))
        self.assertTrue(col.wait(chat_engine.StateChanged))
        self.assertEqual(eng.state, "permission")
        self.assertIsNotNone(eng.session_id)
        eng.answer(req.request_id, "allow")
        self.assertTrue(col.wait(proto.TurnResult))
        eng.request_context()
        self.assertTrue(col.wait(chat_engine.ContextUsage))
        eng.stop(grace_s=1)                               # détache seulement : le chat reste sur le pont
        self.assertEqual(len(self.sync.call_sync("chat.list")["chats"]), 1)

    def test_messages_from_other_devices_shown_own_echo_hidden(self):
        """Bureau : un message envoyé du téléphone arrive (UserSent) ; l'écho de nos propres
        envois n'est pas montré une seconde fois."""
        col = Collector()
        eng = engine.RemoteChatEngine(self.conn, str(self.project), None, ChatOptions(), on_event=col)
        eng.send("du bureau")
        self.assertTrue(col.wait(proto.PermissionRequest))
        self.assertEqual([e for e in col.events if isinstance(e, chat_engine.UserSent)], [])
        self.sync.call_sync("chat.send", chat_id=eng.chat_id, text="du téléphone", nonce="tel")
        self.assertTrue(col.wait(chat_engine.UserSent))
        sent = [e.text for e in col.events if isinstance(e, chat_engine.UserSent)]
        self.assertEqual(sent, ["du téléphone"])

    def test_methods_exist_like_local(self):
        local = [m for m in ("send", "answer", "answer_questions", "interrupt", "set_options", "request_context",
                             "suspend_if_idle", "background_finished", "stop")]
        eng = engine.RemoteChatEngine(self.conn, str(self.project), None, ChatOptions(), on_event=lambda e: None)
        for m in local:
            self.assertTrue(callable(getattr(eng, m)), m)
        self.assertFalse(eng.suspend_if_idle(time.time(), 1))
        self.assertIsNone(eng.pid)


class ShellRelayTest(unittest.IsolatedAsyncioTestCase):
    async def test_shell_distant_relays(self):
        tmp = tempfile.mkdtemp(prefix="ccs-relay-")
        self.addCleanup(shutil.rmtree, tmp, True)
        sock = Path(tmp) / "b.sock"
        with mock.patch.dict(os.environ, {"HOME": tmp, "SHELL": "/bin/sh"}):
            b = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
            bridge_term.TermHub(b, shell="/bin/sh")
            await b.start(sock)
            self.addAsyncCleanup(b.stop)
            c = client.BridgeClient(client.LocalTransport(sock, spawn=None), retry_delays=())
            await c.connect()
            self.addAsyncCleanup(c.close)
            reader = asyncio.StreamReader()
            out = bytearray()
            task = asyncio.ensure_future(shell.relay(c, tmp, reader, out.extend, lambda: (80, 24)))
            await asyncio.sleep(0.3)
            reader.feed_data(b"echo bon''jour\n")
            await asyncio.sleep(0.5)
            reader.feed_data(b"exit 4\n")
            code = await asyncio.wait_for(task, 10)
        self.assertIn(b"bonjour", bytes(out))
        self.assertEqual(code, 4)


if __name__ == "__main__":
    unittest.main()
