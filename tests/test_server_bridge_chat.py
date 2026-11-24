"""Chats dans le pont, contre le faux `claude` : rejeu après coupure, plusieurs appareils."""

import asyncio
import collections
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import chat_protocol, sessions, settings
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

    async def test_sent_message_keeps_its_uuid(self):
        """L'identifiant du message (proposé par l'appareil, sinon tiré par le pont) est rendu et
        diffusé : c'est celui de sa ligne du journal, pour les étiquettes."""
        a, b = await self.client(), await self.client()
        chat_id = (await a.call("chat.open", cwd=str(self.project)))["chat_id"]
        await b.call("chat.attach", chat_id=chat_id, since=0)
        uid = "0b9d2c0e-6f7a-4e55-9a39-2f0e8c1d4b11"
        r = await a.call("chat.send", chat_id=chat_id, text="bonjour", nonce="n1", uuid=uid)
        self.assertEqual(r["uuid"], uid)
        self.assertTrue(await self.wait(lambda: "UserSent" in self.types(b)))
        self.assertEqual(self.find(b, "UserSent")["uuid"], uid)
        other = await a.call("chat.send", chat_id=chat_id, text="encore", uuid="pas-un-uuid")
        self.assertRegex(other["uuid"], r"^[0-9a-f-]{36}$")

    async def test_tags_set_listed_and_broadcast(self):
        a, b = await self.client(), await self.client()
        r = await a.call("chat.tag", session_id="s1", msg_id="msg_1", tags=["important", " Important "],
                         text="Une réponse\nsur deux lignes", role="assistant")
        self.assertEqual(r["entry"]["tags"], ["important"])
        self.assertTrue(await self.wait(lambda: any(n == "chat.tags" for n, _ in b.got)))
        pushed = next(d for n, d in b.got if n == "chat.tags")
        self.assertEqual((pushed["session_id"], pushed["msg_id"]), ("s1", "msg_1"))
        got = await b.call("chat.tags", session_id="s1")
        self.assertEqual(got["messages"]["msg_1"]["excerpt"], "Une réponse sur deux lignes")
        self.assertEqual(got["known"], ["important"])
        r = await a.call("chat.tag", session_id="s1", msg_id="msg_1", tags=[])
        self.assertIsNone(r["entry"])
        self.assertEqual((await a.call("chat.tags", session_id="s1"))["messages"], {})
        for bad in ({"session_id": "../x", "msg_id": "m", "tags": []},
                    {"session_id": "s1", "msg_id": "a/b", "tags": []},
                    {"session_id": "s1", "msg_id": "m", "tags": "x"}):
            with self.assertRaises(rpc.RpcError):
                await a.call("chat.tag", **bad)

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
        want = {"model": "sonnet", "effort": "high", "ultracode": False, "rights": "manual", "provider": None}
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

    async def test_provider_checked_listed_and_fixed(self):
        """Fournisseur : refusé sans clé, proposé par chat.providers, figé par chat.options."""
        from ccs_app import providers
        c = await self.client()
        got = await c.call("chat.providers")
        listed = {p["name"]: p for p in got["providers"]}
        self.assertEqual(got["form"]["rights"][0], ["manual", "Demander"])     # champs de « Nouvelle session »
        self.assertIn("default_rights", got["form"])
        self.assertIsNone(listed["claude"]["problem"])
        self.assertIn("clé absente", listed["openrouter"]["problem"])
        self.assertTrue(listed["openrouter"]["models"])
        with self.assertRaises(rpc.RpcError) as cm:
            await c.call("chat.open", cwd=str(self.project), options={"provider": "openrouter"})
        self.assertEqual(cm.exception.code, "invalide")
        with self.assertRaises(rpc.RpcError):
            await c.call("chat.open", cwd=str(self.project), options={"provider": "inconnu"})
        providers.save_key("openrouter", "sk-or-essai")
        r = await c.call("chat.open", cwd=str(self.project), options={"provider": "openrouter"})
        self.assertEqual(r["options"]["provider"], "openrouter")
        await c.call("chat.options", chat_id=r["chat_id"], options={"provider": None, "model": "x"})
        att = await c.call("chat.attach", chat_id=r["chat_id"], since=0)
        self.assertEqual(att["options"]["provider"], "openrouter")

    async def test_list_gives_journal_title(self):
        """chat.list donne le titre de la conversation : `/rename` ou CCS d'abord, sinon le titre
        automatique ; rien tant que le journal n'en a pas. Le dernier renommage l'emporte."""
        import json
        c = await self.client()
        r = await c.call("chat.open", cwd=str(self.project), session_id="tit")
        journal = sessions.transcript_path(str(self.project), "tit")
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("{}\n")
        title = lambda chats: {x["chat_id"]: x for x in chats["chats"]}[r["chat_id"]]["title"]
        self.assertIsNone(title(await c.call("chat.list")))
        with open(journal, "a") as fh:
            fh.write(json.dumps({"type": "ai-title", "aiTitle": "Titre auto"}) + "\n")
        self.assertEqual(title(await c.call("chat.list")), "Titre auto")
        from ccs_app import conversations
        conversations.rename("tit", "Mon titre", path=str(journal))
        self.assertEqual(title(await c.call("chat.list")), "Mon titre")
        conversations.rename("tit", "Autre", path=str(journal))
        self.assertEqual(title(await c.call("chat.list")), "Autre")

    async def test_background_agent_steps_come_from_its_transcript(self):
        """Sous-agent de fond : la CLI ne passe pas ses étapes ; le pont les lit dans sa
        transcription et les envoie rattachées à son appel, jusqu'à sa fin, puis s'arrête."""
        import json
        c = await self.client()
        r = await c.call("chat.open", cwd=str(self.project), session_id="sub")
        journal = sessions.transcript_path(str(self.project), "sub")
        folder = journal.with_suffix("") / "subagents"
        folder.mkdir(parents=True)
        journal.write_text("{}\n")
        (folder / "agent-aaa.meta.json").write_text(json.dumps({"toolUseId": "t1", "description": "Fond",
                                                               "requestShape": "background"}))
        log = folder / "agent-aaa.jsonl"
        log.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": "consigne"}}) + "\n")

        def say(text, msg_id):
            with open(log, "a") as f:
                f.write(json.dumps({"type": "assistant", "isSidechain": True, "message": {
                    "id": msg_id, "role": "assistant", "content": [{"type": "text", "text": text}]}}) + "\n")

        def texts():
            return [d["event"]["text"] for name, d in c.got if name == "chat.event"
                    and d["event"]["type"] == "AssistantText" and d["event"]["parent_id"] == "t1"]
        chat = self.hub.chats[r["chat_id"]]
        with mock.patch.object(bridge_chat, "WATCH_S", 0.05):
            self.hub._record(chat, chat_protocol.ToolUse("t1", "Agent", {"description": "Fond",
                                                                         "run_in_background": True}))
            say("J'avance.", "m1")
            self.assertTrue(await self.wait(lambda: texts() == ["J'avance."]), texts())
            say("Fini.", "m2")
            self.hub._record(chat, chat_protocol.TaskNotice("t1", "completed", "ok"))
            self.assertTrue(await self.wait(lambda: texts() == ["J'avance.", "Fini."]), texts())
            self.assertTrue(await self.wait(lambda: self.hub._watch.done()))
        att = await c.call("chat.attach", chat_id=r["chat_id"], since=0)
        self.assertEqual([(a["tool_id"], a["state"]) for a in att["agents"]], [("t1", "done")])
        steps = (await c.call("chat.agent_log", chat_id=r["chat_id"], tool_id="t1"))["events"]
        self.assertEqual([e["text"] for e in steps], ["J'avance.", "Fini."])
        self.assertEqual((await c.call("chat.agent_log", chat_id=r["chat_id"], tool_id="inconnu"))["events"], [])

    async def test_attach_lists_agents_launched_before_the_chat(self):
        """Conversation reprise : les sous-agents d'avant sont rendus (pastilles), arrêtés s'ils
        ne s'étaient pas finis (ils sont morts avec l'ancien processus)."""
        import json
        journal = sessions.transcript_path(str(self.project), "vieux")
        folder = journal.with_suffix("") / "subagents"
        folder.mkdir(parents=True)
        journal.write_text("{}\n")
        for agent, tool, finished, minute in (("aaa", "t1", True, 0), ("bbb", "t2", False, 5)):
            (folder / f"agent-{agent}.meta.json").write_text(json.dumps({
                "toolUseId": tool, "description": agent, "requestShape": "background", "finished": finished}))
            (folder / f"agent-{agent}.jsonl").write_text(json.dumps({"timestamp": f"2026-01-01T00:0{minute}:00Z"}) + "\n")
        c = await self.client()
        r = await c.call("chat.open", cwd=str(self.project), session_id="vieux")
        att = await c.call("chat.attach", chat_id=r["chat_id"], since=0)
        self.assertEqual([(a["tool_id"], a["state"]) for a in att["agents"]], [("t1", "done"), ("t2", "stopped")])

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


class AutoCompactBridgeTest(unittest.IsolatedAsyncioTestCase):
    """Compactage automatique : le pont mesure le contexte quand Claude revient au repos et
    envoie `/compact` lui-même. Faux `claude` sans scénario : chaque message a un tour minimal."""

    CONTEXT = {"FAKE_CLAUDE_CONTEXT": "160000"}

    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-bauto-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = make_home(self.tmp)
        env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        for var in ("CLAUDE_CONFIG_DIR", "CCS_HOME"):
            os.environ.pop(var, None)
        self.project = self.home / "projet"
        self.project.mkdir()
        self.sock = Path(self.tmp) / "b.sock"
        self.bridge = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)

    def configure(self, **context_alert):
        settings.save_settings({"context_alert": {"auto_compact": True, "threshold_tokens": 150000, **context_alert}})

    async def hub(self, **env):
        environ = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **self.CONTEXT, **env}
        hub = bridge_chat.ChatHub(self.bridge, claude=FAKE, environ=environ)
        await self.bridge.start(self.sock)
        self.addAsyncCleanup(self.bridge.stop)
        self.addAsyncCleanup(hub.close_all)
        return hub

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
    def events(hub, chat_id, kind=None):
        return [i["event"] for i in hub.chats[chat_id].buf if kind is None or i["event"]["type"] == kind]

    def kinds(self, hub, chat_id):
        return [e["type"] for e in self.events(hub, chat_id)]

    async def settled(self, hub, chat_id, idles):
        """Attend le `idles`-ième retour au repos, puis la mesure du contexte qui le suit."""
        def done():
            # « UserSent » est noté après l'envoi au moteur : sur une machine chargée, il peut
            # arriver après la réponse ; il ne compte pas pour savoir si le chat est au repos.
            kinds = [k for k in self.kinds(hub, chat_id) if k != "UserSent"]
            states = [e["state"] for e in self.events(hub, chat_id, "StateChanged")]
            return states.count("idle") >= idles and kinds[-1] in ("ContextUsage", "Notice")
        self.assertTrue(await self.wait(done), self.kinds(hub, chat_id))
        await asyncio.sleep(0.3)                    # rien d'autre ne part ensuite

    async def test_compacts_without_any_device_attached(self):
        self.configure()
        hub = await self.hub()
        c = await self.client()
        chat_id = (await c.call("chat.open", cwd=str(self.project)))["chat_id"]
        await c.call("chat.send", chat_id=chat_id, text="bonjour")
        await c.close()                             # le téléphone s'en va : le pont continue seul
        await self.settled(hub, chat_id, idles=2)
        kinds = self.kinds(hub, chat_id)
        self.assertEqual(kinds.count("Compacted"), 1)
        notes = self.events(hub, chat_id, "Notice")
        self.assertEqual([(n["text"], n["kind"]) for n in notes],
                         [("Compactage automatique : contexte de 160\u202f000 jetons.", "info")])
        usages = self.events(hub, chat_id, "ContextUsage")
        self.assertEqual([(u["total"], u["auto_compact"]) for u in usages], [(160000, True), (30000, True)])
        self.assertLess(kinds.index("Notice"), kinds.index("Compacted"))     # annoncé avant
        self.assertNotIn("UserSent", kinds[kinds.index("Notice"):])          # pas une bulle de l'utilisateur
        self.assertEqual(hub.chats[chat_id].auto.state, "armed")
        self.assertEqual(hub.chats[chat_id].engine.state, "idle")

    async def test_nothing_when_the_setting_is_off(self):
        hub = await self.hub()
        for cfg in ({"auto_compact": False}, {"enabled": False}):
            self.configure(**cfg)                   # relu à chaque retour au repos
            c = await self.client()
            chat_id = (await c.call("chat.open", cwd=str(self.project)))["chat_id"]
            await c.call("chat.send", chat_id=chat_id, text="bonjour")
            self.assertTrue(await self.wait(lambda: hub.chats[chat_id].engine.state == "idle"
                                            and "TurnResult" in self.kinds(hub, chat_id)))
            await asyncio.sleep(0.3)
            self.assertNotIn("ContextUsage", self.kinds(hub, chat_id), cfg)  # aucune mesure de lui-même
            await c.call("chat.context", chat_id=chat_id)                    # mesure demandée par un appareil
            self.assertTrue(await self.wait(lambda: "ContextUsage" in self.kinds(hub, chat_id)))
            await asyncio.sleep(0.3)
            kinds = self.kinds(hub, chat_id)
            self.assertFalse(self.events(hub, chat_id, "ContextUsage")[0]["auto_compact"], cfg)
            self.assertFalse({"Compacted", "Notice"} & set(kinds), cfg)

    async def test_below_the_threshold_nothing_is_sent(self):
        self.configure(threshold_tokens=170000)
        hub = await self.hub()
        c = await self.client()
        chat_id = (await c.call("chat.open", cwd=str(self.project)))["chat_id"]
        await c.call("chat.send", chat_id=chat_id, text="bonjour")
        await self.settled(hub, chat_id, idles=1)
        kinds = self.kinds(hub, chat_id)
        self.assertEqual(kinds.count("ContextUsage"), 1)
        self.assertFalse({"Compacted", "Notice"} & set(kinds))

    async def test_never_twice_in_a_row_when_context_stays_heavy(self):
        self.configure()
        hub = await self.hub(FAKE_CLAUDE_COMPACT_TO="155000")
        c = await self.client()
        chat_id = (await c.call("chat.open", cwd=str(self.project)))["chat_id"]
        await c.call("chat.send", chat_id=chat_id, text="un")
        await self.settled(hub, chat_id, idles=2)
        await c.call("chat.send", chat_id=chat_id, text="deux")
        await self.settled(hub, chat_id, idles=3)
        kinds = self.kinds(hub, chat_id)
        self.assertEqual(kinds.count("Compacted"), 1)
        notes = self.events(hub, chat_id, "Notice")
        self.assertEqual([n["kind"] for n in notes], ["info", "warning"])
        self.assertIn("Contexte encore lourd après le compactage (155\u202f000 jetons)", notes[1]["text"])
        self.assertEqual(hub.chats[chat_id].auto.state, "stuck")

    async def test_failed_compaction_is_retried_after_the_next_turn_only(self):
        self.configure()
        hub = await self.hub(FAKE_CLAUDE_COMPACT_FAIL="1")
        c = await self.client()
        chat_id = (await c.call("chat.open", cwd=str(self.project)))["chat_id"]
        await c.call("chat.send", chat_id=chat_id, text="un")
        await self.settled(hub, chat_id, idles=2)
        notes = self.events(hub, chat_id, "Notice")
        self.assertEqual([n["kind"] for n in notes], ["info", "warning"])
        self.assertIn("non abouti", notes[1]["text"])
        self.assertEqual(hub.chats[chat_id].auto.state, "failed")            # pas de boucle
        self.assertNotIn("Compacted", self.kinds(hub, chat_id))
        await c.call("chat.send", chat_id=chat_id, text="deux")              # un tour réussi : nouvel essai
        await self.settled(hub, chat_id, idles=4)
        self.assertEqual([n["kind"] for n in self.events(hub, chat_id, "Notice")],
                         ["info", "warning", "info", "warning"])

    async def test_devices_see_the_note_and_the_flag(self):
        self.configure()
        hub = await self.hub()
        a, b = await self.client(), await self.client()
        chat_id = (await a.call("chat.open", cwd=str(self.project)))["chat_id"]
        await b.call("chat.attach", chat_id=chat_id, since=0)
        await a.call("chat.send", chat_id=chat_id, text="bonjour")
        await self.settled(hub, chat_id, idles=2)
        for c in (a, b):
            got = [d["event"] for name, d in c.got if name == "chat.event"]
            self.assertEqual([e["text"] for e in got if e["type"] == "Notice"],
                             ["Compactage automatique : contexte de 160\u202f000 jetons."])
            self.assertTrue(all(e["auto_compact"] for e in got if e["type"] == "ContextUsage"))

