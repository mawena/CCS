"""Chats dans le pont, contre le faux `claude` : rejeu après coupure, plusieurs appareils."""

import asyncio
import collections
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import chat_protocol, sessions
from ccs_app.server import bridge, bridge_chat, rpc
from tests.helpers import make_home

ROOT = Path(__file__).resolve().parent
FAKE = str(ROOT / "fake_claude.py")
SCEN_PERM = str(ROOT / "fixtures" / "chat" / "permissions-allow-toujours.jsonl")


class ChatBridgeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-bchat-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = make_home(self.tmp)
        env = mock.patch.dict(os.environ, {"HOME": str(home)})
        env.start()
        self.addCleanup(env.stop)
        for var in ("CLAUDE_CONFIG_DIR", "CCS_HOME"):      # jamais le vrai dossier de Claude Code
            os.environ.pop(var, None)
        self.home = home
        self.project = home / "projet"              # sous le dossier personnel (dossiers permis)
        self.project.mkdir()
        self.sock = Path(self.tmp) / "b.sock"
        self.bridge = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
        environ = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "FAKE_CLAUDE_SCENARIO": SCEN_PERM,
                   "FAKE_CLAUDE_ARGV_LOG": str(Path(self.tmp) / "argv.log")}
        self.hub = bridge_chat.ChatHub(self.bridge, claude=FAKE, environ=environ)
        await self.bridge.start(self.sock)
        self.addAsyncCleanup(self.bridge.stop)
        self.addAsyncCleanup(self.hub.close_all)

    async def client(self):
        c = rpc.RpcClient()
        c.got = []
        c.on_event = lambda name, data: c.got.append((name, data))
        await c.connect_unix(self.sock)
        self.addAsyncCleanup(c.close)
        await c.call("hello")
        return c

    async def wait(self, pred, timeout=20):
        for _ in range(int(timeout * 50)):
            if pred():
                return True
            await asyncio.sleep(0.02)
        return pred()

    @staticmethod
    def types(c):
        return [d["event"]["type"] for name, d in c.got if name == "chat.event"]

    @staticmethod
    def find(c, t):
        return next(d["event"] for name, d in c.got if name == "chat.event" and d["event"]["type"] == t)

    async def test_open_send_receive(self):
        c = await self.client()
        chat_id = (await c.call("chat.open", cwd=str(self.project)))["chat_id"]
        await c.call("chat.send", chat_id=chat_id, text="bonjour")
        self.assertTrue(await self.wait(lambda: "PermissionRequest" in self.types(c)))
        req = self.find(c, "PermissionRequest")
        await c.call("chat.answer", chat_id=chat_id, request_id=req["request_id"], decision="allow")
        self.assertTrue(await self.wait(lambda: "TurnResult" in self.types(c)))
        listing = (await c.call("chat.list"))["chats"]
        self.assertEqual([x["chat_id"] for x in listing], [chat_id])
        self.assertEqual(listing[0]["cwd"], str(self.project))

    async def test_open_expands_home_and_returns_real_cwd(self):
        """Au téléphone, « ~/Repo/P » plutôt que le chemin complet ; le web reprend le vrai chemin."""
        proj = Path(os.environ["HOME"]) / "Repo" / "P"
        proj.mkdir(parents=True)
        c = await self.client()
        r = await c.call("chat.open", cwd="~/Repo/P/")
        self.assertEqual(r["cwd"], str(proj))
        self.assertEqual((await c.call("chat.list"))["chats"][0]["cwd"], str(proj))
        with self.assertRaises(rpc.RpcError):
            await c.call("chat.open", cwd="~/nulle-part")

    async def test_reconnect_replays_missed_events(self):
        c = await self.client()
        chat_id = (await c.call("chat.open", cwd=str(self.project)))["chat_id"]
        await c.call("chat.send", chat_id=chat_id, text="bonjour")
        self.assertTrue(await self.wait(lambda: "PermissionRequest" in self.types(c)))
        await c.close()                                     # le téléphone perd le réseau
        c2 = await self.client()
        r = await c2.call("chat.attach", chat_id=chat_id, since=0)
        kinds = [e["event"]["type"] for e in r["events"]]
        self.assertIn("PermissionRequest", kinds)
        self.assertEqual([e["seq"] for e in r["events"]], sorted(e["seq"] for e in r["events"]))
        again = await c2.call("chat.attach", chat_id=chat_id, since=r["seq"])
        self.assertEqual(again["events"], [])
        req = next(e["event"] for e in r["events"] if e["event"]["type"] == "PermissionRequest")
        await c2.call("chat.answer", chat_id=chat_id, request_id=req["request_id"], decision="allow")
        self.assertTrue(await self.wait(lambda: "TurnResult" in self.types(c2)))

    async def test_two_clients_same_chat(self):
        a, b = await self.client(), await self.client()
        chat_id = (await a.call("chat.open", cwd=str(self.project)))["chat_id"]
        await b.call("chat.attach", chat_id=chat_id, since=0)
        await a.call("chat.send", chat_id=chat_id, text="bonjour")
        self.assertTrue(await self.wait(lambda: "PermissionRequest" in self.types(b)))
        self.assertIn("PermissionRequest", self.types(a))

    async def test_sent_message_shown_on_other_devices(self):
        """Message envoyé depuis le téléphone : les autres appareils (bureau, autre onglet) le
        voient aussi, et il reste dans le tampon pour un onglet rechargé."""
        a, b = await self.client(), await self.client()
        chat_id = (await a.call("chat.open", cwd=str(self.project)))["chat_id"]
        await b.call("chat.attach", chat_id=chat_id, since=0)
        await a.call("chat.send", chat_id=chat_id, text="!notes\nbonjour", shown="bonjour",
                     nonce="n1", images=[])
        self.assertTrue(await self.wait(lambda: "UserSent" in self.types(b)))
        ev = self.find(b, "UserSent")
        self.assertEqual((ev["text"], ev["nonce"], ev["images"]), ("bonjour", "n1", 0))
        replay = await self.client()
        r = await replay.call("chat.attach", chat_id=chat_id, since=0)
        self.assertIn("UserSent", [e["event"]["type"] for e in r["events"]])

    async def test_answer_permission_settles_for_others(self):
        a, b = await self.client(), await self.client()
        chat_id = (await a.call("chat.open", cwd=str(self.project)))["chat_id"]
        await b.call("chat.attach", chat_id=chat_id, since=0)
        await a.call("chat.send", chat_id=chat_id, text="bonjour")
        self.assertTrue(await self.wait(lambda: "PermissionRequest" in self.types(b)))
        req = self.find(b, "PermissionRequest")
        await b.call("chat.answer", chat_id=chat_id, request_id=req["request_id"], decision="allow")
        self.assertTrue(await self.wait(lambda: "PermissionSettled" in self.types(a)))
        self.assertEqual(self.find(a, "PermissionSettled")["request_id"], req["request_id"])

    async def test_reopen_same_conversation_reuses_chat(self):
        c = await self.client()
        one = (await c.call("chat.open", cwd=str(self.project), session_id="abc"))["chat_id"]
        two = (await c.call("chat.open", cwd=str(self.project), session_id="abc"))["chat_id"]
        three = (await c.call("chat.open", cwd=str(self.project)))["chat_id"]
        self.assertEqual(one, two)
        self.assertNotEqual(one, three)

    async def test_unknown_chat_and_bad_cwd(self):
        c = await self.client()
        with self.assertRaises(rpc.RpcError) as cm:
            await c.call("chat.send", chat_id="zzz", text="x")
        self.assertEqual(cm.exception.code, "introuvable")
        with self.assertRaises(rpc.RpcError):
            await c.call("chat.open", cwd="/dossier/inexistant")

    async def test_open_only_in_allowed_folders(self):
        """Constat 11 : un chat ouvert sur / permettrait de lister le système."""
        c = await self.client()
        outside = Path(self.tmp) / "dehors"
        outside.mkdir()
        for bad in ("/", str(outside), str(self.home / ".." / "dehors")):
            with self.assertRaises(rpc.RpcError) as cm:
                await c.call("chat.open", cwd=bad)
            self.assertEqual(cm.exception.code, "refuse", bad)
        os.symlink("/", self.home / "racine")
        with self.assertRaises(rpc.RpcError) as cm:
            await c.call("chat.open", cwd="~/racine")
        self.assertEqual(cm.exception.code, "refuse")
        for bad in ("../../x", "a/b", 3):
            with self.assertRaises(rpc.RpcError) as cm:
                await c.call("chat.open", cwd=str(self.project), session_id=bad)
            self.assertEqual(cm.exception.code, "invalide", bad)
        self.assertEqual((await c.call("chat.list"))["chats"], [])

    async def test_ids_unique_across_bridge_restarts(self):
        """C1 : `c<boot>-<n>`, boot tiré au hasard à la création du hub."""
        c = await self.client()
        one = (await c.call("chat.open", cwd=str(self.project)))["chat_id"]
        self.assertRegex(one, r"^c[0-9a-f]{6}-1$")
        self.assertEqual(one, f"c{self.hub.boot}-1")
        other = bridge_chat.ChatHub(bridge.Bridge("bob", None, local=True, start_daemon=False, install_claude=False))
        self.assertRegex(other.boot, r"^[0-9a-f]{6}$")
        self.assertNotEqual(other.boot, self.hub.boot)

    async def test_options_session_and_journal_path(self):
        """C2 : options du moteur, conversation et journal dans chat.open, chat.attach et chat.list."""
        c = await self.client()
        r = await c.call("chat.open", cwd=str(self.project), options={"model": "sonnet", "effort": "high"})
        want = {"model": "sonnet", "effort": "high", "ultracode": False, "rights": "manual"}
        self.assertEqual((r["options"], r["session_id"], r["path"]), (want, None, None))
        r2 = await c.call("chat.open", cwd=str(self.project), session_id="abc")
        self.assertEqual((r2["session_id"], r2["path"]), ("abc", None))       # journal pas encore écrit
        journal = sessions.transcript_path(str(self.project), "abc")
        self.assertTrue(str(journal).startswith(str(self.home)))
        journal.parent.mkdir(parents=True)
        journal.write_text("{}\n")
        again = await c.call("chat.open", cwd=str(self.project), session_id="abc")   # le même chat
        self.assertEqual((again["chat_id"], again["path"]), (r2["chat_id"], str(journal)))
        self.assertEqual(again["options"]["rights"], "manual")
        listing = {x["chat_id"]: x for x in (await c.call("chat.list"))["chats"]}
        self.assertEqual((listing[r["chat_id"]]["path"], listing[r["chat_id"]]["options"]), (None, want))
        self.assertEqual(listing[r2["chat_id"]]["path"], str(journal))
        att = await c.call("chat.attach", chat_id=r2["chat_id"], since=0)
        self.assertEqual((att["session_id"], att["path"]), ("abc", str(journal)))
        self.assertEqual(set(att["options"]), set(want))

    async def test_history_before_covers_what_the_buffer_lost(self):
        """history_before : heure d'ouverture du chat tant que le tampon a tout gardé, sinon heure du
        plus vieil événement gardé (le journal montre ce qui précède, sans doublon)."""
        import time
        c = await self.client()
        t0 = time.time()
        chat_id = (await c.call("chat.open", cwd=str(self.project)))["chat_id"]
        t1 = time.time()
        listing = (await c.call("chat.list"))["chats"][0]
        self.assertTrue(t0 <= listing["history_before"] <= t1)
        chat = self.hub.chats[chat_id]
        chat.buf = collections.deque(chat.buf, maxlen=2)         # tampon minuscule : il déborde
        for _ in range(3):
            await asyncio.sleep(0.01)
            self.hub._record(chat, chat_protocol.Status("default"))
        r = await c.call("chat.attach", chat_id=chat_id, since=0)
        self.assertEqual(r["history_before"], chat.buf[0]["ts"])
        self.assertGreater(r["history_before"], listing["history_before"])

    async def test_busy_check_and_close(self):
        c = await self.client()
        chat_id = (await c.call("chat.open", cwd=str(self.project)))["chat_id"]
        await c.call("chat.send", chat_id=chat_id, text="bonjour")
        self.assertTrue(await self.wait(lambda: "PermissionRequest" in self.types(c)))
        self.assertTrue(any(check() for check in self.bridge.busy_checks))
        await c.call("chat.close", chat_id=chat_id)
        self.assertEqual((await c.call("chat.list"))["chats"], [])

    async def test_render_markdown_sanitized(self):
        c = await self.client()
        html = (await c.call("chat.render", markdown="**gras** <script>alert(1)</script> [x](javascript:alert(1))"))["html"]
        self.assertIn("<strong>gras</strong>", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn('href="javascript:', html)


if __name__ == "__main__":
    unittest.main()
