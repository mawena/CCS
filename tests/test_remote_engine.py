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

    def test_join_running_chat_replays_and_follows(self):
        """Bureau : rejoindre un chat qui tourne déjà sur le serveur (lancé du téléphone) : le fil
        est rejoué, puis suivi en direct ; on peut y répondre."""
        tel = engine.RemoteChatEngine(self.conn, str(self.project), None, ChatOptions(), on_event=lambda e: None)
        tel.send("du téléphone")
        col = Collector()
        deadline = time.time() + 20
        while tel.chat_id is None and time.time() < deadline:
            time.sleep(0.05)
        joined = engine.RemoteChatEngine(self.conn, str(self.project), None, ChatOptions(), on_event=col,
                                         chat_id=tel.chat_id)
        self.assertTrue(col.wait(proto.PermissionRequest))
        self.assertIn("du téléphone", [e.text for e in col.events if isinstance(e, chat_engine.UserSent)])
        self.assertEqual(joined.chat_id, tel.chat_id)
        req = next(e for e in col.events if isinstance(e, proto.PermissionRequest))
        joined.answer(req.request_id, "allow")
        self.assertTrue(col.wait(proto.TurnResult))

    def test_permission_settled_elsewhere_is_forwarded(self):
        """Une autorisation réglée sur un autre appareil (web, téléphone) arrive au bureau, pour
        que sa carte ne reste pas en attente."""
        col = Collector()
        eng = engine.RemoteChatEngine(self.conn, str(self.project), None, ChatOptions(), on_event=col)
        eng.send("bonjour")
        self.assertTrue(col.wait(proto.PermissionRequest))
        req = next(e for e in col.events if isinstance(e, proto.PermissionRequest))
        self.sync.call_sync("chat.answer", chat_id=eng.chat_id, request_id=req.request_id, decision="allow")
        from ccs_app.server import events as bridge_events
        self.assertTrue(col.wait(bridge_events.PermissionSettled))

    def test_bridge_restart_reopens_chat(self):
        """Le pont a redémarré (mise à jour) : le chat n'existe plus là-bas. À la reconnexion,
        l'onglet du bureau se rebranche sur la conversation au lieu de rester figé."""
        col = Collector()
        eng = engine.RemoteChatEngine(self.conn, str(self.project), None, ChatOptions(), on_event=col)
        eng.send("bonjour")
        self.assertTrue(col.wait(proto.PermissionRequest))
        old = eng.chat_id
        self.sync.call_sync("chat.close", chat_id=old)
        eng.resync()                                   # ce que fait la reconnexion
        deadline = time.time() + 20
        while eng.chat_id in (None, old) and time.time() < deadline:
            time.sleep(0.05)
        self.assertNotIn(eng.chat_id, (None, old))
        self.assertIn(eng.chat_id, [c["chat_id"] for c in self.sync.call_sync("chat.list")["chats"]])

    def test_resumed_conversation_follows_chat_running_elsewhere(self):
        """Bureau : « Reprendre » une conversation que le web fait tourner : l'onglet suit le chat
        en direct dès l'ouverture, sans attendre d'y écrire (et sans rejouer l'historique déjà lu)."""
        tel = engine.RemoteChatEngine(self.conn, str(self.project), None, ChatOptions(), on_event=lambda e: None)
        tel.send("du web")
        deadline = time.time() + 20
        while (tel.chat_id is None or tel.session_id is None or tel.state != "permission") and time.time() < deadline:
            time.sleep(0.05)
        col = Collector()
        desk = engine.RemoteChatEngine(self.conn, str(self.project), tel.session_id, ChatOptions(), on_event=col)
        while desk.chat_id is None and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(desk.chat_id, tel.chat_id)
        req = [e for e in col.events if isinstance(e, proto.PermissionRequest)]
        self.assertEqual(req, [])                       # déjà dans l'historique : pas rejoué
        self.sync.call_sync("chat.send", chat_id=tel.chat_id, text="encore du web", nonce="w2")
        self.assertTrue(col.wait(chat_engine.UserSent))

    def test_resumed_conversation_joins_when_opened_elsewhere_later(self):
        """Onglet du bureau ouvert d'abord, le web ouvre la même conversation ensuite : le bureau
        s'y branche quand même."""
        first = engine.RemoteChatEngine(self.conn, str(self.project), None, ChatOptions(), on_event=lambda e: None)
        first.send("pour créer la conversation")
        deadline = time.time() + 20
        while (first.session_id is None or first.state != "permission") and time.time() < deadline:
            time.sleep(0.05)
        sid = first.session_id
        self.sync.call_sync("chat.close", chat_id=first.chat_id)
        first.stop()
        col = Collector()
        with mock.patch.object(engine, "LOOK_S", 0.2):
            desk = engine.RemoteChatEngine(self.conn, str(self.project), sid, ChatOptions(), on_event=col)
            time.sleep(0.5)
            self.assertIsNone(desk.chat_id)                 # rien d'ouvert ailleurs pour l'instant
            web = self.sync.call_sync("chat.open", cwd=str(self.project), session_id=sid)
            while desk.chat_id is None and time.time() < deadline:
                time.sleep(0.05)
        self.assertEqual(desk.chat_id, web["chat_id"])
        desk.stop()

    def test_methods_exist_like_local(self):
        local = [m for m in ("send", "answer", "answer_questions", "interrupt", "set_options", "request_context",
                             "suspend_if_idle", "background_finished", "stop")]
        eng = engine.RemoteChatEngine(self.conn, str(self.project), None, ChatOptions(), on_event=lambda e: None)
        for m in local:
            self.assertTrue(callable(getattr(eng, m)), m)
        self.assertFalse(eng.suspend_if_idle(time.time(), 1))
        self.assertIsNone(eng.pid)


    def test_tags_through_the_bridge(self):
        col = Collector()
        eng = engine.RemoteChatEngine(self.conn, str(self.project), "sess-tags", ChatOptions(), on_event=col)
        got = threading.Event()
        loaded, set_result = [], []
        eng.load_tags(lambda msgs, known: (loaded.append((msgs, known)), got.set()))
        self.assertTrue(got.wait(20))
        self.assertEqual(loaded, [({}, [])])
        got.clear()
        eng.set_tags("m-1", ["important"], "Deux options", "assistant",
                     callback=lambda entry, err: (set_result.append((entry, err)), got.set()))
        self.assertTrue(got.wait(20))
        entry, err = set_result[0]
        self.assertIsNone(err)
        self.assertEqual((entry["tags"], entry["excerpt"]), (["important"], "Deux options"))
        # le pont diffuse le changement : le moteur de cette conversation le reçoit
        self.assertTrue(col.wait(chat_engine.TagsChanged))
        ev = next(e for e in col.events if isinstance(e, chat_engine.TagsChanged))
        self.assertEqual((ev.session_id, ev.msg_id, ev.entry["tags"]), ("sess-tags", "m-1", ["important"]))
        got.clear()
        loaded.clear()
        eng.load_tags(lambda msgs, known: (loaded.append((msgs, known)), got.set()))
        self.assertTrue(got.wait(20))
        self.assertEqual(list(loaded[0][0]), ["m-1"])
        self.assertEqual(loaded[0][1], ["important"])
        eng.stop()
        self.assertNotIn(eng, self.conn.tag_listeners)

    def test_tags_need_a_known_conversation(self):
        eng = engine.RemoteChatEngine(self.conn, str(self.project), None, ChatOptions())
        out = []
        eng.load_tags(lambda *a: out.append(a))
        eng.set_tags("m-1", ["x"], callback=lambda *a: out.append(a))
        self.assertEqual(out, [({}, []), (None, "Conversation pas encore enregistrée.")])

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
