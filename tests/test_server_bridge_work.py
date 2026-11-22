"""Travail dans le chat côté pont : commandes `/`, fichiers pour `@`, messages enregistrés,
commande `!`, changements de la session et retour en arrière (HOME temporaire, aucun vrai claude)."""

import asyncio
import hashlib
import json
import os
import types
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import chat_protocol as proto, chat_quote, file_history, saved_messages, sessions
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
        self.call("saved.save", cwd=cwd, scope="global", name="Bonjour", text="Salut")
        self.call("saved.save", cwd=cwd, scope="projet", name="Tests", text="Lance les tests")
        items = self.call("saved.list", cwd=cwd)["items"]
        self.assertEqual({(i["name"], i["scope"]) for i in items}, {("Bonjour", "global"), ("Tests", "projet")})
        self.assertTrue((self.project / ".ccs" / "messages.json").exists())
        self.call("saved.delete", cwd=cwd, scope="projet", name="Tests")
        items = self.call("saved.list", cwd=cwd)["items"]
        self.assertEqual([i["name"] for i in items], ["Bonjour"])

    def test_save_same_name_replaces(self):
        cwd = str(self.project)
        self.call("saved.save", cwd=cwd, scope="global", name="A", text="1")
        self.call("saved.save", cwd=cwd, scope="global", name="A", text="2")
        items = self.call("saved.list", cwd=cwd)["items"]
        self.assertEqual([i["text"] for i in items], ["2"])

    def test_global_hidden_by_project_is_kept(self):
        """Constat 7 : écrire un message commun n'efface pas un commun de même nom qu'un
        message du projet."""
        cwd = str(self.project)
        self.call("saved.save", cwd=cwd, scope="global", name="Revue", text="globale")
        self.call("saved.save", cwd=cwd, scope="projet", name="Revue", text="du projet")
        self.call("saved.save", cwd=cwd, scope="global", name="Merci", text="merci")
        self.call("saved.delete", cwd=cwd, scope="global", name="Merci")
        self.assertEqual([(s.name, s.text) for s in saved_messages.read_scope("global")], [("Revue", "globale")])
        items = self.call("saved.list", cwd=cwd)["items"]
        self.assertEqual([(i["name"], i["scope"]) for i in items], [("Revue", "projet")])

    def test_project_messages_only_in_an_open_chat_folder(self):
        """Constat 11 : `.ccs/` n'est créé que dans le dossier d'un chat ouvert."""
        other = self.home / "ailleurs"
        other.mkdir()
        e = self.fails("saved.save", cwd=str(other), scope="projet", name="a", text="b")
        self.assertEqual(e.code, "refuse")
        self.assertEqual(self.fails("saved.delete", cwd=str(other), scope="projet", name="a").code, "refuse")
        self.assertFalse((other / ".ccs").exists())
        self.call("saved.save", cwd=str(other), scope="global", name="a", text="b")   # commun : permis
        self.assertFalse((other / ".ccs").exists())

    def test_invalid_and_forbidden(self):
        self.assertEqual(self.fails("saved.save", cwd=str(self.project), scope="x", name="a", text="b").code, "invalide")
        self.assertEqual(self.fails("saved.save", cwd=str(self.project), scope="global", name=" ", text="b").code, "invalide")
        self.assertEqual(self.fails("saved.list", cwd="/etc").code, "refuse")


class ShellTest(WorkTest):
    def run_shell(self, command):
        async def go():
            r = await self.bridge._handlers["shell.run"](self.conn, {"chat_id": "c1", "command": command})
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
        self.assertEqual(name, "work.shell")      # ancien client : ancien nom (compatibilité 1.x)
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["output"].strip(), str(self.project))
        self.assertEqual(data["chat_id"], "c1")

    def test_new_client_gets_shell_done(self):
        self.conn.peer = {"protocol": 1}
        self.run_shell("true")
        self.assertEqual(self.conn.pushed[0][0], "shell.done")

    def test_failure_code_and_poll(self):
        r = self.run_shell("echo non >&2; exit 3")
        self.assertEqual(self.conn.pushed[0][1]["code"], 3)
        p = self.call("shell.poll", run_id=r["run_id"])
        self.assertTrue(p["done"])
        self.assertIn("non", p["output"])

    def test_background_process_does_not_block(self):
        """Constat 6 : `echo a; sleep 5 &` rend la main quelques secondes après la fin de bash."""
        self.run_shell("echo a; sleep 5 &")
        self.assertTrue(self.conn.pushed, "la commande ne rend pas la main")
        self.assertEqual(self.conn.pushed[0][1]["output"].strip(), "a")
        self.assertEqual(self.conn.pushed[0][1]["code"], 0)

    def test_empty_command_refused(self):
        self.assertEqual(self.fails("shell.run", chat_id="c1", command="  ").code, "invalide")

    def test_stop(self):
        async def go():
            r = await self.bridge._handlers["shell.run"](self.conn, {"chat_id": "c1", "command": "sleep 30"})
            await asyncio.sleep(0.3)
            await self.bridge._handlers["shell.stop"](self.conn, {"run_id": r["run_id"]})
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

    @staticmethod
    def sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def plan(self, mid="m1"):
        r = self.call("rewind.plan", chat_id="c1", message_id=mid)
        return r, [{"path": s["path"], "sha256": s["sha256"]} for s in r["steps"]]

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
        self.assertEqual(ch["sha256"], self.sha(self.f))                  # C4 : contenu actuel
        self.assertFalse(ch["too_big"])
        self.assertEqual(r["points"][0]["message_id"], "m1")

    def test_point_of_a_reply_shows_the_reply_not_its_quote(self):
        (self.copies / "h1@v1").write_text("avant\n")
        Path(self.f).write_text("après\n")
        self.journal_with(self.user("m1", chat_quote.compose("claude", "A ou B ?\n" + "x" * 400, "Prends la B")),
                          snap_line("m1", {self.f: ("h1@v1", 1)}))
        r = self.call("work.changes", chat_id="c1")
        self.assertEqual([p["text"] for p in r["points"]], ["Prends la B"])

    def test_points_are_only_messages_with_a_snapshot(self):
        (self.copies / "h1@v1").write_text("avant\n")
        Path(self.f).write_text("après\n")
        self.journal_with(self.user("m1", "x"), snap_line("m1", {self.f: ("h1@v1", 1)}),
                          self.user("m2", "sans instantané"))
        r = self.call("work.changes", chat_id="c1")
        self.assertEqual([p["message_id"] for p in r["points"]], ["m1"])
        self.assertEqual(self.fails("rewind.plan", chat_id="c1", message_id="m2").code, "introuvable")
        self.assertEqual(Path(self.f).read_text(), "après\n")

    def test_changes_of_deleted_file_and_too_big_file(self):
        gone, big = str(self.project / "parti.txt"), str(self.project / "gros.map")
        (self.copies / "p@v1").write_text("là\n")
        (self.copies / "g@v1").write_text("petit\n")
        Path(big).write_bytes(b"x" * (bridge_work.MAX_FILE_BYTES + 1))
        self.journal_with(self.user("m1", "x"), snap_line("m1", {gone: ("p@v1", 1), big: ("g@v1", 1)}))
        files = {f["path"]: f for f in self.call("work.changes", chat_id="c1")["files"]}
        self.assertIsNone(files[gone]["sha256"])
        self.assertEqual(files[gone]["kind"], "deleted")
        self.assertTrue(files[big]["too_big"])
        self.assertEqual(files[big]["diff"], "")
        self.assertEqual(files[big]["sha256"], self.sha(big))
        self.assertEqual(bridge_work.MAX_FILE_BYTES, 2 * 1024 * 1024)

    def test_changes_long_lines_cut_and_total_capped(self):
        other = str(self.project / "b.txt")
        (self.copies / "h1@v1").write_text("court\n")
        (self.copies / "h2@v1").write_text("court\n")
        Path(self.f).write_text("y" * 10000 + "\n")
        Path(other).write_text("z\n")
        self.journal_with(self.user("m1", "x"), snap_line("m1", {self.f: ("h1@v1", 1), other: ("h2@v1", 1)}))
        files = {f["path"]: f for f in self.call("work.changes", chat_id="c1")["files"]}
        self.assertLessEqual(max(len(l) for l in files[self.f]["diff"].splitlines()),
                             bridge_work.MAX_LINE_CHARS + 1)
        self.assertEqual(bridge_work.MAX_LINE_CHARS, 4000)
        with mock.patch.object(bridge_work, "MAX_DIFF_TOTAL", 10):
            files = self.call("work.changes", chat_id="c1")["files"]
        self.assertEqual([f["too_big"] for f in files], [False, True])  # budget épuisé après le premier

    def test_unknown_format(self):
        self.journal_with(json.dumps({"type": "file-history-snapshot", "autre": 1}))
        self.assertTrue(self.call("work.changes", chat_id="c1")["unknown"])

    def test_undo_file_restores_and_refuses_unknown_path(self):
        (self.copies / "h1@v1").write_text("avant\n")
        Path(self.f).write_text("après\n")
        self.journal_with(self.user("m1", "x"), snap_line("m1", {self.f: ("h1@v1", 1)}))
        self.assertEqual(self.fails("work.undo", chat_id="c1", path=str(self.project / "autre"),
                                    expected=None).code, "introuvable")
        self.call("work.undo", chat_id="c1", path=self.f, expected=self.sha(self.f))
        self.assertEqual(Path(self.f).read_text(), "avant\n")

    def test_undo_file_checks_what_was_shown(self):
        """C4 : le fichier a changé depuis l'affichage (ou l'empreinte manque) : rien n'est écrit."""
        (self.copies / "h1@v1").write_text("avant\n")
        Path(self.f).write_text("après\n")
        self.journal_with(self.user("m1", "x"), snap_line("m1", {self.f: ("h1@v1", 1)}))
        shown = self.call("work.changes", chat_id="c1")["files"][0]["sha256"]
        Path(self.f).write_text("modifié depuis\n")
        e = self.fails("work.undo", chat_id="c1", path=self.f, expected=shown)
        self.assertEqual((e.code, e.message), ("conflit", "Un fichier a changé depuis l'affichage : vérifie de nouveau."))
        self.assertEqual(self.fails("work.undo", chat_id="c1", path=self.f).code, "invalide")
        self.assertEqual(Path(self.f).read_text(), "modifié depuis\n")

    def test_undo_removes_created_file(self):
        Path(self.f).write_text("neuf\n")
        self.journal_with(self.user("m1", "x"), snap_line("m1", {self.f: (None, 1)}))
        ch = self.call("work.changes", chat_id="c1")["files"][0]
        self.assertEqual(ch["kind"], "created")
        self.call("work.undo", chat_id="c1", path=self.f, expected=ch["sha256"])
        self.assertFalse(Path(self.f).exists())

    def test_rewind_plan_then_apply(self):
        (self.copies / "h1@v1").write_text("avant\n")
        Path(self.f).write_text("après\n")
        self.journal_with(self.user("m1", "x"), snap_line("m1", {self.f: ("h1@v1", 1)}))
        plan, expected = self.plan()
        self.assertEqual([s["path"] for s in plan["steps"]], [self.f])
        self.assertEqual(plan["steps"][0]["sha256"], self.sha(self.f))
        self.assertEqual(plan["skipped"], [])
        self.assertEqual(Path(self.f).read_text(), "après\n")      # le plan n'écrit rien
        r = self.call("rewind.apply", chat_id="c1", message_id="m1", expected=expected)
        self.assertEqual(r["count"], 1)
        self.assertEqual(Path(self.f).read_text(), "avant\n")

    def test_rewind_apply_only_what_was_shown(self):
        """C4 : le plan recalculé au clic doit être celui qui a été montré."""
        other = str(self.project / "b.txt")
        (self.copies / "h1@v1").write_text("avant\n")
        (self.copies / "h2@v1").write_text("b avant\n")
        Path(self.f).write_text("après\n")
        Path(other).write_text("b avant\n")
        self.journal_with(self.user("m1", "x"), snap_line("m1", {self.f: ("h1@v1", 1), other: ("h2@v1", 1)}))
        _plan, expected = self.plan()
        self.assertEqual([e["path"] for e in expected], [self.f])
        Path(other).write_text("b changé depuis\n")             # un fichier de plus à remettre
        e = self.fails("rewind.apply", chat_id="c1", message_id="m1", expected=expected)
        self.assertEqual(e.code, "conflit")
        _plan, expected = self.plan()
        Path(self.f).write_text("encore autre chose\n")          # contenu changé depuis l'affichage
        self.assertEqual(self.fails("rewind.apply", chat_id="c1", message_id="m1",
                                    expected=expected).code, "conflit")
        self.assertEqual(self.fails("rewind.apply", chat_id="c1", message_id="m1").code, "invalide")
        self.assertEqual(Path(self.f).read_text(), "encore autre chose\n")
        self.assertEqual(Path(other).read_text(), "b changé depuis\n")

    def test_writes_refused_while_claude_works(self):
        (self.copies / "h1@v1").write_text("avant\n")
        Path(self.f).write_text("après\n")
        self.journal_with(self.user("m1", "x"), snap_line("m1", {self.f: ("h1@v1", 1)}))
        _plan, expected = self.plan()
        for state in ("starting", "busy", "permission"):
            self.chat.engine.state = state
            e = self.fails("rewind.apply", chat_id="c1", message_id="m1", expected=expected)
            self.assertEqual((e.code, e.message), ("occupe", "Claude travaille : attends la fin du tour."))
            self.assertEqual(self.fails("work.undo", chat_id="c1", path=self.f,
                                        expected=self.sha(self.f)).code, "occupe")
        self.assertEqual(Path(self.f).read_text(), "après\n")

    def test_rewind_skips_files_outside_allowed_roots(self):
        """Constat 13 : un fichier hors des dossiers permis est laissé de côté et signalé, le
        reste du retour en arrière se fait."""
        outside = "/etc/passwd-ccs-test"
        (self.copies / "h1@v1").write_text("x\n")
        (self.copies / "h2@v1").write_text("avant\n")
        Path(self.f).write_text("après\n")
        self.journal_with(self.user("m1", "x"), snap_line("m1", {outside: ("h1@v1", 1), self.f: ("h2@v1", 1)}))
        plan, expected = self.plan()
        self.assertEqual([s["path"] for s in plan["steps"]], [self.f])
        self.assertEqual(plan["skipped"], [outside])
        r = self.call("rewind.apply", chat_id="c1", message_id="m1", expected=expected)
        self.assertEqual((r["count"], r["skipped"]), (1, [outside]))
        self.assertEqual(Path(self.f).read_text(), "avant\n")
        self.assertFalse(os.path.exists(outside))

    def test_no_session_yet(self):
        self.chat.engine.session_id = None
        self.assertEqual(self.call("work.changes", chat_id="c1")["files"], [])

if __name__ == "__main__":
    unittest.main()
