"""Travail dans le chat côté pont : commandes `/`, fichiers pour `@`, messages enregistrés,
commande `!`, changements de la session et retour en arrière (HOME temporaire, aucun vrai claude)."""

import asyncio
import json
import os
import types
import unittest
from pathlib import Path

from ccs_app import chat_protocol as proto, file_history, sessions
from ccs_app.server import bridge, bridge_chat, bridge_work, events, rpc
from tests.helpers import HomeTestCase
from tests.test_file_history import snap_line

SESSION = "sess-w"


class FakeConn:
    closed = False

    def __init__(self):
        self.pushed = []

    async def push(self, name, data):
        self.pushed.append((name, data))


class WorkTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.home / "projet"
        self.project.mkdir()
        self.bridge = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
        self.hub = bridge_chat.ChatHub(self.bridge)
        self.api = bridge_work.WorkApi(self.bridge)
        self.bridge.hubs = {"chat": self.hub, "work": self.api}
        chat = bridge_chat._Chat("c1", str(self.project))
        chat.engine = types.SimpleNamespace(session_id=SESSION, state="idle")
        self.hub.chats["c1"] = chat
        self.chat = chat
        self.conn = FakeConn()

    def call(self, method, **params):
        return asyncio.run(self.bridge._handlers[method](self.conn, params))

    def put(self, ev):
        self.chat.buf.append({"seq": len(self.chat.buf) + 1, "event": events.to_json(ev)})

    def fails(self, method, **params):
        with self.assertRaises(rpc.RpcError) as cm:
            self.call(method, **params)
        return cm.exception


class CommandsTest(WorkTest):
    def test_commands_come_from_last_hello(self):
        self.put(proto.Hello(commands=(("compact", "Résume", ""), ("review", "Relit", "<pr>"))))
        r = self.call("work.commands", chat_id="c1")
        self.assertEqual([c["name"] for c in r["commands"]], ["compact", "review"])
        self.assertEqual(r["commands"][1]["hint"], "<pr>")
        self.assertTrue(r["context"]["enabled"])
        self.assertGreater(r["context"]["threshold_tokens"], 0)

    def test_commands_empty_without_hello(self):
        self.assertEqual(self.call("work.commands", chat_id="c1")["commands"], [])

    def test_unknown_chat(self):
        self.assertEqual(self.fails("work.commands", chat_id="zz").code, "introuvable")


class FilesTest(WorkTest):
    def test_lists_project_files_without_hidden_or_deps(self):
        (self.project / "src").mkdir()
        (self.project / "src" / "a.py").write_text("x")
        (self.project / "node_modules").mkdir()
        (self.project / "node_modules" / "b.js").write_text("x")
        (self.project / ".git").mkdir()
        (self.project / ".git" / "c").write_text("x")
        (self.project / "README.md").write_text("x")
        r = self.call("work.files", chat_id="c1")
        self.assertEqual(sorted(r["files"]), ["README.md", "src/a.py"])


class SavedTest(WorkTest):
    def test_save_list_delete_global_and_project(self):
        cwd = str(self.project)
        self.call("work.saved.save", cwd=cwd, scope="global", name="Bonjour", text="Salut")
        self.call("work.saved.save", cwd=cwd, scope="projet", name="Tests", text="Lance les tests")
        items = self.call("work.saved.list", cwd=cwd)["items"]
        self.assertEqual({(i["name"], i["scope"]) for i in items}, {("Bonjour", "global"), ("Tests", "projet")})
        self.assertTrue((self.project / ".ccs" / "messages.json").exists())
        self.call("work.saved.delete", cwd=cwd, scope="projet", name="Tests")
        items = self.call("work.saved.list", cwd=cwd)["items"]
        self.assertEqual([i["name"] for i in items], ["Bonjour"])

    def test_save_same_name_replaces(self):
        cwd = str(self.project)
        self.call("work.saved.save", cwd=cwd, scope="global", name="A", text="1")
        self.call("work.saved.save", cwd=cwd, scope="global", name="A", text="2")
        items = self.call("work.saved.list", cwd=cwd)["items"]
        self.assertEqual([i["text"] for i in items], ["2"])

    def test_invalid_and_forbidden(self):
        self.assertEqual(self.fails("work.saved.save", cwd=str(self.project), scope="x", name="a", text="b").code, "invalide")
        self.assertEqual(self.fails("work.saved.save", cwd=str(self.project), scope="global", name=" ", text="b").code, "invalide")
        self.assertEqual(self.fails("work.saved.list", cwd="/etc").code, "refuse")


class ShellTest(WorkTest):
    def run_shell(self, command):
        async def go():
            r = await self.bridge._handlers["work.shell.run"](self.conn, {"chat_id": "c1", "command": command})
            for _ in range(200):
                if self.conn.pushed:
                    break
                await asyncio.sleep(0.02)
            return r
        return asyncio.run(go())

    def test_runs_in_project_dir(self):
        r = self.run_shell("pwd")
        self.assertTrue(r["run_id"])
        name, data = self.conn.pushed[0]
        self.assertEqual(name, "work.shell")
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["output"].strip(), str(self.project))
        self.assertEqual(data["chat_id"], "c1")

    def test_failure_code_and_poll(self):
        r = self.run_shell("echo non >&2; exit 3")
        self.assertEqual(self.conn.pushed[0][1]["code"], 3)
        p = self.call("work.shell.poll", run_id=r["run_id"])
        self.assertTrue(p["done"])
        self.assertIn("non", p["output"])

    def test_empty_command_refused(self):
        self.assertEqual(self.fails("work.shell.run", chat_id="c1", command="  ").code, "invalide")

    def test_stop(self):
        async def go():
            r = await self.bridge._handlers["work.shell.run"](self.conn, {"chat_id": "c1", "command": "sleep 30"})
            await asyncio.sleep(0.3)
            await self.bridge._handlers["work.shell.stop"](self.conn, {"run_id": r["run_id"]})
            for _ in range(300):
                if self.conn.pushed:
                    break
                await asyncio.sleep(0.02)
        asyncio.run(go())
        self.assertNotEqual(self.conn.pushed[0][1]["code"], 0)


class ChangesTest(WorkTest):
    def setUp(self):
        super().setUp()
        config = self.home / ".claude"
        self.copies = config / "file-history" / SESSION
        self.copies.mkdir(parents=True)
        self.journal = sessions.transcript_path(str(self.project), SESSION)
        self.journal.parent.mkdir(parents=True)
        self.f = str(self.project / "a.txt")

    def journal_with(self, *lines):
        self.journal.write_text("\n".join(lines) + "\n")

    def user(self, uuid, text):
        return json.dumps({"type": "user", "uuid": uuid, "message": {"role": "user", "content": text}})

    def test_changes_with_diff_and_points(self):
        (self.copies / "h1@v1").write_text("un\ndeux\n")
        Path(self.f).write_text("un\ntrois\n")
        self.journal_with(self.user("m1", "Change a"), snap_line("m1", {self.f: ("h1@v1", 1)}))
        r = self.call("work.changes", chat_id="c1")
        self.assertFalse(r["unknown"])
        ch = r["files"][0]
        self.assertEqual(ch["path"], self.f)
        self.assertEqual(ch["kind"], "modified")
        self.assertIn("-deux", ch["diff"])
        self.assertIn("+trois", ch["diff"])
        self.assertEqual(r["points"][0]["message_id"], "m1")

    def test_unknown_format(self):
        self.journal_with(json.dumps({"type": "file-history-snapshot", "autre": 1}))
        self.assertTrue(self.call("work.changes", chat_id="c1")["unknown"])

    def test_undo_file_restores_and_refuses_unknown_path(self):
        (self.copies / "h1@v1").write_text("avant\n")
        Path(self.f).write_text("après\n")
        self.journal_with(self.user("m1", "x"), snap_line("m1", {self.f: ("h1@v1", 1)}))
        self.assertEqual(self.fails("work.undo_file", chat_id="c1", path=str(self.project / "autre")).code, "introuvable")
        self.call("work.undo_file", chat_id="c1", path=self.f)
        self.assertEqual(Path(self.f).read_text(), "avant\n")

    def test_undo_removes_created_file(self):
        Path(self.f).write_text("neuf\n")
        self.journal_with(self.user("m1", "x"), snap_line("m1", {self.f: (None, 1)}))
        self.assertEqual(self.call("work.changes", chat_id="c1")["files"][0]["kind"], "created")
        self.call("work.undo_file", chat_id="c1", path=self.f)
        self.assertFalse(Path(self.f).exists())

    def test_rewind_plan_then_apply(self):
        (self.copies / "h1@v1").write_text("avant\n")
        Path(self.f).write_text("après\n")
        self.journal_with(self.user("m1", "x"), snap_line("m1", {self.f: ("h1@v1", 1)}))
        plan = self.call("work.rewind_plan", chat_id="c1", message_id="m1")
        self.assertEqual([s["path"] for s in plan["steps"]], [self.f])
        self.assertEqual(Path(self.f).read_text(), "après\n")      # le plan n'écrit rien
        r = self.call("work.rewind_apply", chat_id="c1", message_id="m1")
        self.assertEqual(r["count"], 1)
        self.assertEqual(Path(self.f).read_text(), "avant\n")

    def test_rewind_refuses_step_outside_allowed_roots(self):
        (self.copies / "h1@v1").write_text("x\n")
        self.journal_with(self.user("m1", "x"), snap_line("m1", {"/etc/passwd-ccs-test": ("h1@v1", 1)}))
        self.assertEqual(self.fails("work.rewind_apply", chat_id="c1", message_id="m1").code, "refuse")

    def test_no_session_yet(self):
        self.chat.engine.session_id = None
        self.assertEqual(self.call("work.changes", chat_id="c1")["files"], [])


if __name__ == "__main__":
    unittest.main()
