"""Pont : projets, fichiers, feuille de route, analyse et tâches ; chemins limités."""

import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app.server import bridge, bridge_data, rpc
from tests.helpers import make_home

ROADMAP = "# Projet\n\n## Phase 1 — Base (0.1.0)\n\n- [ ] écrire\n- [x] lire\n"


class DataBridgeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-bdata-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = make_home(self.tmp)
        env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        for var in ("CLAUDE_CONFIG_DIR", "CCS_HOME"):
            os.environ.pop(var, None)
        self.project = self.home / "projet"
        (self.project / "src").mkdir(parents=True)
        (self.project / "a.txt").write_text("un\n")
        (self.project / "img.bin").write_bytes(b"\0\1\2")
        (self.project / "ROADMAP.md").write_text(ROADMAP)
        sock = Path(self.tmp) / "b.sock"
        self.bridge = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
        bridge_data.DataApi(self.bridge)
        await self.bridge.start(sock)
        self.addAsyncCleanup(self.bridge.stop)
        self.c = rpc.RpcClient()
        await self.c.connect_unix(sock)
        self.addAsyncCleanup(self.c.close)
        await self.c.call("hello")

    async def refused(self, method, **params):
        with self.assertRaises(rpc.RpcError) as cm:
            await self.c.call(method, **params)
        self.assertEqual(cm.exception.code, "refuse", params)

    async def test_paths_outside_home_refused(self):
        os.symlink("/", self.home / "racine")
        await self.refused("files.read", path="/etc/passwd")
        await self.refused("files.read", path=str(self.home / ".." / ".." / "etc" / "passwd"))
        await self.refused("files.read", path=str(self.home / "racine" / "etc" / "passwd"))
        await self.refused("files.read", path="relatif.txt")
        await self.refused("files.list", root="/etc")
        await self.refused("files.write", path="/tmp/x.txt", text="x", stamp=None)
        await self.refused("roadmap.read", cwd="/etc")

    def test_extra_roots(self):
        self.assertTrue(bridge_data.allowed_path("/var/www/html/site/index.php", home="/home/a"))
        self.assertTrue(bridge_data.allowed_path("/home/a/p", home="/home/a"))
        self.assertFalse(bridge_data.allowed_path("/home/ab/p", home="/home/a"))
        self.assertFalse(bridge_data.allowed_path("/var/wwwx", home="/home/a"))

    async def test_files_list_and_read(self):
        r = await self.c.call("files.list", root=str(self.project))
        names = [(e["name"], e["dir"]) for e in r["entries"]]
        self.assertEqual(names[0], ("src", True))                 # dossiers d'abord
        self.assertIn(("a.txt", False), names)
        r = await self.c.call("files.read", path=str(self.project / "a.txt"))
        self.assertEqual((r["kind"], r["text"]), ("text", "un\n"))
        self.assertEqual(len(r["stamp"]), 2)
        r = await self.c.call("files.read", path=str(self.project / "img.bin"))
        self.assertEqual(r["kind"], "binary")
        self.assertNotIn("text", r)
        r = await self.c.call("files.list", root=str(self.project), rel="src")
        self.assertEqual(r["entries"], [])
        await self.refused("files.list", root=str(self.project), rel="../..")

    async def test_write_conflict(self):
        p = self.project / "a.txt"
        r = await self.c.call("files.read", path=str(p))
        p.write_text("changé ailleurs, plus long\n")
        with self.assertRaises(rpc.RpcError) as cm:
            await self.c.call("files.write", path=str(p), text="moi\n", stamp=r["stamp"])
        self.assertEqual(cm.exception.code, "conflit")
        r = await self.c.call("files.read", path=str(p))
        w = await self.c.call("files.write", path=str(p), text="moi\n", stamp=r["stamp"])
        self.assertEqual(p.read_text(), "moi\n")
        self.assertEqual(len(w["stamp"]), 2)
        await self.c.call("files.write", path=str(self.project / "nouveau.txt"), text="n\n", stamp=None)
        self.assertEqual((self.project / "nouveau.txt").read_text(), "n\n")

    async def test_roadmap_toggle(self):
        r = await self.c.call("roadmap.read", cwd=str(self.project))
        task = r["phases"][0]["tasks"][0]
        self.assertEqual((task["text"], task["done"]), ("écrire", False))
        await self.c.call("roadmap.toggle", path=r["path"], line=task["line"], text=task["text"])
        self.assertIn("- [x] écrire", (self.project / "ROADMAP.md").read_text())
        empty = await self.c.call("roadmap.read", cwd=str(self.project / "src"))
        self.assertIsNone(empty["path"])

    async def test_projects_list_shape(self):
        r = await self.c.call("projects.list")
        self.assertIn("entries", r)
        self.assertIn("conversations", r)
        self.assertIn("sessions", r)
        self.assertEqual(r["entries"][0]["cwd"], None)             # « Tous les projets »

    async def test_tasks_add_and_cancel(self):
        t = await self.c.call("tasks.add", message="fais ceci", cwd=str(self.project), when="nuit")
        ids = [x["id"] for x in (await self.c.call("tasks.list"))["tasks"]]
        self.assertIn(t["task"]["id"], ids)
        await self.c.call("tasks.cancel", id=t["task"]["id"])
        with self.assertRaises(rpc.RpcError) as cm:
            await self.c.call("tasks.add", message="", cwd=str(self.project))
        self.assertEqual(cm.exception.code, "invalide")

    async def test_analysis_report(self):
        r = await self.c.call("analysis.report", days=7)
        self.assertEqual(r["days"], 7)
        self.assertIn("by_project", r)
        self.assertEqual(len(r["by_hour"]), 24)

    # ---- lot « sessions » : dossiers, compte, images, recherche, renommage, coût ----------

    async def test_projects_folders(self):
        (self.home / "Repo" / "a" / ".git").mkdir(parents=True)
        (self.home / "Repo" / "node_modules" / "x" / ".git").mkdir(parents=True)
        (self.home / ".cache" / "z" / ".git").mkdir(parents=True)
        (self.home / "a" / "b" / "c" / "d" / ".git").mkdir(parents=True)        # 4 niveaux : trop profond
        r = await self.c.call("projects.folders")
        paths = [f["path"] for f in r["folders"]]
        self.assertIn(str(self.home / "Repo" / "a"), paths)
        self.assertFalse([p for p in paths if "node_modules" in p or "/.cache" in p])
        self.assertNotIn(str(self.home / "a" / "b" / "c" / "d"), paths)
        self.assertFalse(r["truncated"])

    async def test_projects_folders_capped(self):
        for i in range(5):
            (self.home / "R" / f"p{i}" / ".git").mkdir(parents=True)
        with mock.patch.object(bridge_data, "MAX_FOLDERS", 3):
            r = await self.c.call("projects.folders")
        self.assertEqual(len(r["folders"]), 3)
        self.assertTrue(r["truncated"])

    async def test_projects_account(self):
        r = await self.c.call("projects.account", cwd=str(self.project))
        self.assertEqual(r["active"], "perso")
        self.assertEqual(sorted(p["name"] for p in r["profiles"]), ["perso", "pro"])
        self.assertIsNone(r["preferred"])
        assoc = bridge_data.project_accounts.Association(str(self.project), "pro", True)
        with mock.patch.object(bridge_data.project_accounts, "all", return_value=[assoc]):
            r = await self.c.call("projects.account", cwd=str(self.project))
        self.assertEqual(r["preferred"], "pro")
        self.assertIn("pro", r["hint"])
        await self.refused("projects.account", cwd="/etc")

    async def test_files_image(self):
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
        (self.project / "p.png").write_bytes(png)
        r = await self.c.call("files.image", path=str(self.project / "p.png"))
        self.assertEqual(r["mime"], "image/png")
        import base64
        self.assertEqual(base64.b64decode(r["data"]), png)
        (self.project / "big.png").write_bytes(b"0" * (5 * 1024 * 1024 + 1))
        with self.assertRaises(rpc.RpcError) as cm:
            await self.c.call("files.image", path=str(self.project / "big.png"))
        self.assertEqual(cm.exception.code, "trop_gros")
        with self.assertRaises(rpc.RpcError) as cm:
            await self.c.call("files.image", path=str(self.project / "a.txt"))
        self.assertEqual(cm.exception.code, "invalide")
        await self.refused("files.image", path="/etc/passwd")

    async def test_files_search(self):
        (self.project / "src" / "Lisez.md").write_text("x")
        (self.project / "node_modules" / "lisez").mkdir(parents=True)
        (self.project / ".git").mkdir()
        (self.project / ".git" / "lisez").write_text("x")
        r = await self.c.call("files.search", root=str(self.project), query="LISEZ")
        self.assertEqual([e["path"] for e in r["entries"]], ["src/Lisez.md"])
        r = await self.c.call("files.search", root=str(self.project), query="  ")
        self.assertEqual(r["entries"], [])
        with mock.patch.object(bridge_data, "MAX_SEARCH", 1):
            (self.project / "src" / "lisez2.md").write_text("x")
            r = await self.c.call("files.search", root=str(self.project), query="lisez")
        self.assertEqual(len(r["entries"]), 1)
        self.assertTrue(r["truncated"])
        await self.refused("files.search", root="/etc", query="a")

    async def test_conversation_rename_and_cost(self):
        d = self.home / ".claude" / "projects" / "-p"
        d.mkdir(parents=True)
        journal = d / "abc.jsonl"
        journal.write_text('{"type":"user","message":{"content":"salut"}}\n')
        r = await self.c.call("conversation.rename", session_id="abc", title="  Mon  titre ", path=str(journal))
        self.assertEqual(r["title"], "Mon titre")
        self.assertIn("custom-title", journal.read_text())
        with self.assertRaises(rpc.RpcError) as cm:
            await self.c.call("conversation.rename", session_id="abc", title=" ", path=str(journal))
        self.assertEqual(cm.exception.code, "invalide")
        await self.refused("conversation.rename", session_id="abc", title="x", path="/etc/passwd")
        r = await self.c.call("conversation.cost", path=str(journal))
        self.assertIn("short", r)
        self.assertIn("text", r)
        await self.refused("conversation.cost", path="/etc/passwd")

    async def test_roadmap_task_prompt(self):
        r = await self.c.call("roadmap.read", cwd=str(self.project))
        t = r["phases"][0]["tasks"][0]
        r = await self.c.call("roadmap.task_prompt", path=r["path"], text=t["text"], phase=r["phases"][0]["title"])
        self.assertIn("écrire", r["prompt"])
        with self.assertRaises(rpc.RpcError) as cm:
            await self.c.call("roadmap.task_prompt", path=str(self.project / "ROADMAP.md"), text="inconnue", phase="x")
        self.assertEqual(cm.exception.code, "introuvable")

    async def test_tasks_add_from_roadmap(self):
        info = {"path": str(self.project / "ROADMAP.md"), "text": "écrire", "phase": "Phase 1 — Base (0.1.0)"}
        t = await self.c.call("tasks.add", message="fais", cwd=str(self.project), when="nuit", roadmap=info)
        self.assertEqual(t["task"]["extra"]["roadmap"], info)
        await self.c.call("tasks.cancel", id=t["task"]["id"])


if __name__ == "__main__":
    unittest.main()
