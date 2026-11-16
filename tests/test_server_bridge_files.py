"""Gestion des fichiers par le pont : télécharger, envoyer, créer, renommer, supprimer."""
import base64
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app.server import bridge, bridge_files, rpc
from tests.helpers import make_home


def b64(data):
    return base64.b64encode(data).decode("ascii")


class FileOpsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-bfiles-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = make_home(self.tmp)
        env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        self.project = self.home / "projet"
        (self.project / "src").mkdir(parents=True)
        (self.project / "a.txt").write_text("un\n")
        sock = Path(self.tmp) / "b.sock"
        self.bridge = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
        bridge_files.FileOps(self.bridge)
        await self.bridge.start(sock)
        self.addAsyncCleanup(self.bridge.stop)
        self.c = rpc.RpcClient()
        await self.c.connect_unix(sock)
        self.addAsyncCleanup(self.c.close)
        await self.c.call("hello")

    async def code(self, method, **params):
        with self.assertRaises(rpc.RpcError) as cm:
            await self.c.call(method, **params)
        return cm.exception.code

    async def test_download_in_chunks(self):
        data = os.urandom(2500)
        (self.project / "gros.bin").write_bytes(data)
        with mock.patch.object(bridge_files, "CHUNK", 1000):
            got, offset = b"", 0
            while True:
                r = await self.c.call("files.download", path=str(self.project / "gros.bin"), offset=offset)
                got += base64.b64decode(r["data"])
                offset = len(got)
                if r["done"]:
                    break
        self.assertEqual((got, r["size"]), (data, 2500))
        self.assertEqual(await self.code("files.download", path="/etc/passwd"), "refuse")
        self.assertEqual(await self.code("files.download", path=str(self.project / "src")), "introuvable")
        self.assertEqual(await self.code("files.download", path=str(self.project / "a.txt"), offset=-1), "invalide")
        with mock.patch.object(bridge_files, "MAX_TRANSFER", 2):
            self.assertEqual(await self.code("files.download", path=str(self.project / "a.txt")), "trop_gros")

    async def test_upload_in_chunks_then_rename(self):
        d = str(self.project)
        r = await self.c.call("files.upload", dir=d, name="n.bin", data=b64(b"abc"), offset=0)
        self.assertEqual(r, {"received": 3, "done": False})
        self.assertFalse((self.project / "n.bin").exists())           # rien sous le vrai nom avant la fin
        self.assertEqual(await self.code("files.upload", dir=d, name="n.bin", data=b64(b"x"), offset=9), "conflit")
        r = await self.c.call("files.upload", dir=d, name="n.bin", data=b64(b"def"), offset=3, last=True)
        self.assertEqual(r, {"received": 6, "done": True})
        self.assertEqual((self.project / "n.bin").read_bytes(), b"abcdef")
        self.assertEqual([p.name for p in self.project.iterdir() if p.name.endswith(bridge_files.PART)], [])

    async def test_upload_refuses_existing_unless_replace(self):
        d = str(self.project)
        self.assertEqual(await self.code("files.upload", dir=d, name="a.txt", data=b64(b"x"), last=True), "existe")
        self.assertEqual((self.project / "a.txt").read_text(), "un\n")
        await self.c.call("files.upload", dir=d, name="a.txt", data=b64(b"deux"), last=True, replace=True)
        self.assertEqual((self.project / "a.txt").read_text(), "deux")
        self.assertEqual(await self.code("files.upload", dir=d, name="src", data="", last=True, replace=True), "existe")
        for bad in ("../x", "a/b", "..", "", "x\0"):
            self.assertEqual(await self.code("files.upload", dir=d, name=bad, data="", last=True), "invalide", bad)
        self.assertEqual(await self.code("files.upload", dir=d, name="z", data="pas du base64 !", last=True), "invalide")
        self.assertEqual(await self.code("files.upload", dir="/etc", name="z", data="", last=True), "refuse")
        with mock.patch.object(bridge_files, "MAX_TRANSFER", 2):
            self.assertEqual(await self.code("files.upload", dir=d, name="z", data=b64(b"abc"), last=True), "trop_gros")

    async def test_mkdir_and_create(self):
        d = str(self.project)
        r = await self.c.call("files.mkdir", dir=d, name="docs")
        self.assertEqual(r["path"], str(self.project / "docs"))
        self.assertTrue((self.project / "docs").is_dir())
        await self.c.call("files.create", dir=str(self.project / "docs"), name="lisez.md")
        self.assertEqual((self.project / "docs" / "lisez.md").read_text(), "")
        self.assertEqual(await self.code("files.mkdir", dir=d, name="docs"), "existe")
        self.assertEqual(await self.code("files.create", dir=d, name="a.txt"), "existe")
        self.assertEqual(await self.code("files.create", dir=d, name="x/y"), "invalide")
        self.assertEqual(await self.code("files.mkdir", dir="/etc", name="x"), "refuse")
        self.assertEqual(await self.code("files.mkdir", dir=str(self.project / "absent"), name="x"), "introuvable")

    async def test_rename(self):
        r = await self.c.call("files.rename", path=str(self.project / "a.txt"), name="b.txt", root=str(self.project))
        self.assertEqual(r["path"], str(self.project / "b.txt"))
        self.assertEqual((self.project / "b.txt").read_text(), "un\n")
        self.assertEqual(await self.code("files.rename", path=str(self.project / "b.txt"), name="src"), "existe")
        self.assertEqual(await self.code("files.rename", path=str(self.project / "b.txt"), name="../c"), "invalide")
        self.assertEqual(await self.code("files.rename", path=str(self.project / "rien"), name="c"), "introuvable")
        self.assertEqual(await self.code("files.rename", path="/etc/passwd", name="c"), "refuse")
        self.assertEqual(await self.code("files.rename", path=str(self.project), name="c", root=str(self.project)), "refuse")
        self.assertTrue(self.project.is_dir())

    async def test_delete_file_folder_and_link(self):
        root = str(self.project)
        (self.project / "src" / "x.py").write_text("x")
        outside = Path(self.tmp) / "dehors.txt"
        outside.write_text("garde")
        os.symlink(outside, self.project / "lien")
        r = await self.c.call("files.info", path=str(self.project / "src"))
        self.assertEqual((r["dir"], r["count"]), (True, 1))
        await self.c.call("files.delete", path=str(self.project / "lien"), root=root)
        self.assertFalse(os.path.lexists(self.project / "lien"))
        self.assertEqual(outside.read_text(), "garde")                # le lien part, pas sa cible
        await self.c.call("files.delete", path=str(self.project / "a.txt"), root=root)
        await self.c.call("files.delete", path=str(self.project / "src"), root=root)
        self.assertEqual(sorted(p.name for p in self.project.iterdir()), [])
        self.assertEqual(await self.code("files.delete", path=str(self.project / "rien"), root=root), "introuvable")

    async def test_delete_protects_roots(self):
        root = str(self.project)
        for path in (root, str(self.home), str(self.project / "src" / ".."), "/etc/passwd", "/"):
            self.assertEqual(await self.code("files.delete", path=path, root=root), "refuse", path)
        self.assertEqual(await self.code("files.delete", path=str(self.home), root=""), "refuse")
        self.assertTrue((self.project / "a.txt").exists())


if __name__ == "__main__":
    unittest.main()
