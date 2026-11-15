"""Chats dans le pont, contre le faux `claude` : rejeu après coupure, plusieurs appareils."""

import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
