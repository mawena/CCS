"""Pont : git d'un projet (état, diff, indexation, commit, fetch / pull / push, journal), sur de
vrais petits dépôts temporaires ; un dépôt nu local sert de distant, aucun réseau."""

import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from ccs_app.server import bridge, bridge_git, rpc
from tests.git_helpers import GitTestCase, commit_file, g, many_commits


class GitBridgeTest(GitTestCase, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        sock = Path(self.tmp) / "b.sock"
        self.bridge = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
        bridge_git.GitApi(self.bridge)
        await self.bridge.start(sock)
        self.addAsyncCleanup(self.bridge.stop)
        self.c = rpc.RpcClient()
        await self.c.connect_unix(sock)
        self.addAsyncCleanup(self.c.close)
        await self.c.call("hello")
        self.cwd = str(self.repo)

    async def call(self, method, **params):
        return await self.c.call(method, cwd=self.cwd, **params)

    async def fails(self, code, method, **params):
        with self.assertRaises(rpc.RpcError) as cm:
            await self.call(method, **params)
        self.assertEqual(cm.exception.code, code)
        return cm.exception

    # ---- garde des chemins -----------------------------------------------------------

    async def test_path_outside_allowed_roots_refused(self):
        with self.assertRaises(rpc.RpcError) as cm:
            await self.c.call("git.status", cwd="/etc")
        self.assertEqual(cm.exception.code, "refuse")
        with self.assertRaises(rpc.RpcError):
            await self.c.call("git.status", cwd="relatif")

    async def test_not_a_repo(self):
        plain = Path(self.tmp) / "simple"
        plain.mkdir()
        r = await self.c.call("git.status", cwd=str(plain))
        self.assertFalse(r["repo"])
        with self.assertRaises(rpc.RpcError) as cm:
            await self.c.call("git.log", cwd=str(plain))
        self.assertEqual(cm.exception.code, "invalide")

    async def test_file_paths_cannot_leave_the_repo(self):
        commit_file(self.repo, "a.txt", "un\n")
        for bad in ("../x", "/etc/passwd", "a/../../x", ""):
            await self.fails("invalide", "git.stage", paths=[bad])

    # ---- état ------------------------------------------------------------------------

    async def test_status_branch_files_and_marks(self):
        commit_file(self.repo, "a.txt", "un\n")
        (self.repo / "a.txt").write_text("deux\n")
        (self.repo / "nouveau.txt").write_text("x\n")
        r = await self.call("git.status")
        self.assertTrue(r["repo"])
        self.assertEqual(r["branch"]["name"], "main")
        self.assertEqual((r["branch"]["ahead"], r["branch"]["behind"]), (0, 0))
        files = {f["path"]: f for f in r["files"]}
        self.assertEqual(files["a.txt"]["unstaged"], "M")
        self.assertEqual(files["nouveau.txt"]["staged"], "?")
        self.assertEqual(r["proposed"], "")

    async def test_status_proposed_message_when_staged(self):
        commit_file(self.repo, "a.txt", "un\n")
        (self.repo / "a.txt").write_text("deux\n")
        await self.call("git.stage", paths=["a.txt"])
        r = await self.call("git.status")
        self.assertIn("a.txt", r["proposed"])

    async def test_status_in_empty_repo(self):
        (self.repo / "a.txt").write_text("x\n")
        r = await self.call("git.status")
        self.assertTrue(r["repo"])
        self.assertEqual(r["files"][0]["staged"], "?")

    async def test_cwd_in_subfolder_uses_repo_root(self):
        commit_file(self.repo, "sous/a.txt", "un\n")
        (self.repo / "sous" / "a.txt").write_text("deux\n")
        self.cwd = str(self.repo / "sous")
        r = await self.call("git.status")
        self.assertEqual(r["root"], str(self.repo))
        await self.call("git.stage", paths=["sous/a.txt"])
        self.assertEqual((await self.call("git.status"))["files"][0]["staged"], "M")

    # ---- diff et indexation ----------------------------------------------------------

    async def test_diff_lines_and_staged_side(self):
        commit_file(self.repo, "a.txt", "un\ndeux\n")
        (self.repo / "a.txt").write_text("un\ntrois\n")
        d = (await self.call("git.diff", path="a.txt", staged=False))["diff"]
        kinds = [l["kind"] for h in d["hunks"] for l in h["lines"]]
        self.assertIn("+", kinds)
        self.assertIn("-", kinds)
        self.assertIsNone((await self.call("git.diff", path="a.txt", staged=True))["diff"])
        await self.call("git.stage", paths=["a.txt"])
        self.assertIsNotNone((await self.call("git.diff", path="a.txt", staged=True))["diff"])

    async def test_diff_of_big_file_is_truncated(self):
        commit_file(self.repo, "a.txt", "x\n")
        (self.repo / "a.txt").write_text("".join(f"ligne {i}\n" for i in range(5000)))
        d = (await self.call("git.diff", path="a.txt", staged=False))["diff"]
        self.assertTrue(d["truncated"])
        self.assertLessEqual(sum(len(h["lines"]) for h in d["hunks"]), bridge_git.DIFF_LINES)

    async def test_stage_and_unstage_files(self):
        commit_file(self.repo, "a.txt", "un\n")
        (self.repo / "a.txt").write_text("deux\n")
        (self.repo / "b.txt").write_text("b\n")
        await self.call("git.stage", paths=["a.txt", "b.txt"])
        files = {f["path"]: f["staged"] for f in (await self.call("git.status"))["files"]}
        self.assertEqual(files, {"a.txt": "M", "b.txt": "A"})
        await self.call("git.unstage", paths=["a.txt"])
        files = {f["path"]: f["staged"] for f in (await self.call("git.status"))["files"]}
        self.assertEqual(files["a.txt"], ".")

    async def test_stage_one_hunk(self):
        base = "".join(f"l{i}\n" for i in range(40))
        commit_file(self.repo, "a.txt", base)
        lines = base.splitlines(keepends=True)
        lines[1] = "CHANGE1\n"
        lines[38] = "CHANGE2\n"
        (self.repo / "a.txt").write_text("".join(lines))
        d = (await self.call("git.diff", path="a.txt", staged=False))["diff"]
        self.assertEqual(len(d["hunks"]), 2)
        await self.call("git.hunk", path="a.txt", index=1, action="stage")
        staged = g(self.repo, "diff", "--cached")
        self.assertIn("CHANGE2", staged)
        self.assertNotIn("CHANGE1", staged)
        await self.call("git.hunk", path="a.txt", index=0, action="stage")
        await self.call("git.hunk", path="a.txt", index=0, action="unstage")
        staged = g(self.repo, "diff", "--cached")
        self.assertNotIn("CHANGE1", staged)
        self.assertIn("CHANGE2", staged)
        await self.fails("invalide", "git.hunk", path="a.txt", index=9, action="stage")
        await self.fails("invalide", "git.hunk", path="a.txt", index=0, action="jeter")

    # ---- commit ----------------------------------------------------------------------

    async def test_commit_and_amend(self):
        commit_file(self.repo, "a.txt", "un\n")
        (self.repo / "a.txt").write_text("deux\n")
        await self.call("git.stage", paths=["a.txt"])
        r = await self.call("git.commit", message="feat: deux")
        self.assertEqual(r["id"], g(self.repo, "rev-parse", "HEAD").strip())
        n = int(g(self.repo, "rev-list", "--count", "HEAD"))
        (self.repo / "a.txt").write_text("trois\n")
        await self.call("git.stage", paths=["a.txt"])
        await self.call("git.commit", message="feat: trois", amend=True)
        self.assertEqual(int(g(self.repo, "rev-list", "--count", "HEAD")), n)
        self.assertEqual(g(self.repo, "log", "-1", "--format=%s").strip(), "feat: trois")

    async def test_commit_errors_in_french_shape(self):
        e = await self.fails("git", "git.commit", message="  ")
        self.assertIn("vide", e.message)
        e = await self.fails("git", "git.commit", message="rien indexé")
        self.assertTrue(e.message)

    async def test_amend_message_proposed(self):
        commit_file(self.repo, "a.txt", "un\n", msg="premier")
        r = await self.call("git.status")
        self.assertEqual(r["last_message"], "premier")

    # ---- journal ---------------------------------------------------------------------

    async def test_log_pages_of_fifty(self):
        many_commits(self.repo, 120)
        r = await self.call("git.log")
        self.assertEqual(len(r["commits"]), 50)
        self.assertTrue(r["more"])
        self.assertEqual(r["commits"][0]["subject"], "commit 119")
        r2 = await self.call("git.log", skip=100)
        self.assertEqual(len(r2["commits"]), 20)
        self.assertFalse(r2["more"])
        self.assertEqual(r["commits"][0].keys() >= {"id", "short", "author", "time", "subject"}, True)

    async def test_log_of_empty_repo(self):
        self.assertEqual((await self.call("git.log"))["commits"], [])

    # ---- distant ---------------------------------------------------------------------

    async def test_push_then_status_ahead_and_pull(self):
        self.remote()
        commit_file(self.repo, "a.txt", "un\n")
        await self.call("git.push")
        r = await self.call("git.status")
        self.assertEqual(r["branch"]["upstream"], "origin/main")
        commit_file(self.repo, "b.txt", "deux\n")
        self.assertEqual((await self.call("git.status"))["branch"]["ahead"], 1)
        await self.call("git.push")
        # un second clone pousse, puis on tire
        other = Path(self.tmp) / "autre"
        subprocess.run(["git", "clone", "-q", str(Path(self.tmp) / "distant.git"), str(other)], check=True)
        commit_file(other, "c.txt", "trois\n")
        g(other, "push", "-q")
        await self.call("git.fetch")
        self.assertEqual((await self.call("git.status"))["branch"]["behind"], 1)
        await self.call("git.pull")
        self.assertTrue((self.repo / "c.txt").exists())

    async def test_push_without_remote_is_an_error(self):
        commit_file(self.repo, "a.txt", "un\n")
        e = await self.fails("git", "git.push")
        self.assertIn("distant", e.message)

    async def test_force_push_needs_explicit_force(self):
        self.remote()
        commit_file(self.repo, "a.txt", "un\n")
        await self.call("git.push")
        g(self.repo, "commit", "-q", "--amend", "-m", "réécrit")
        await self.fails("git", "git.push")                       # refusé sans force
        await self.call("git.push", force=True)
        await self.fails("invalide", "git.push", force="oui")
        self.assertEqual((await self.call("git.status"))["branch"]["ahead"], 0)


    # ---- revue phase 14 : confinement et plafonds (C7) ---------------------------------

    async def test_diff_refuses_dash_and_stays_in_repo(self):
        commit_file(self.repo, "a.txt", "un\n")
        await self.fails("invalide", "git.diff", path="-", staged=False)
        outside = Path(self.tmp) / "dehors"
        outside.mkdir()
        (outside / "hostname").write_text("secret-dehors\n")
        os.symlink(outside, self.repo / "lnk")
        try:
            r = await self.call("git.diff", path="lnk/hostname", staged=False)
            self.assertIsNone(r["diff"])
        except rpc.RpcError as e:
            self.assertNotIn("secret-dehors", e.message)

    async def test_diff_of_too_big_file(self):
        self.assertEqual(bridge_git.MAX_FILE_BYTES, 2 * 1024 * 1024)
        (self.repo / "app.js.map").write_bytes(b"x" * (bridge_git.MAX_FILE_BYTES + 1))   # une seule ligne
        d = (await self.call("git.diff", path="app.js.map", staged=False))["diff"]
        self.assertTrue(d["too_big"])
        self.assertEqual(d["hunks"], [])

    async def test_diff_long_lines_are_cut(self):
        self.assertEqual(bridge_git.MAX_LINE_CHARS, 4000)
        commit_file(self.repo, "a.txt", "un\n")
        (self.repo / "a.txt").write_text("y" * 10000 + "\n")
        d = (await self.call("git.diff", path="a.txt", staged=False))["diff"]
        self.assertFalse(d["too_big"])
        longest = max(len(l["text"]) for h in d["hunks"] for l in h["lines"])
        self.assertLessEqual(longest, bridge_git.MAX_LINE_CHARS + 1)

    async def test_diff_total_size_capped(self):
        commit_file(self.repo, "a.txt", "un\n")
        (self.repo / "a.txt").write_text("".join(f"{i:05d}" + "z" * 3000 + "\n" for i in range(600)))
        d = (await self.call("git.diff", path="a.txt", staged=False))["diff"]
        self.assertTrue(d["truncated"])
        total = sum(len(l["text"]) for h in d["hunks"] for l in h["lines"])
        self.assertLessEqual(total, bridge_git.MAX_DIFF_CHARS + bridge_git.MAX_LINE_CHARS + 1)

    async def test_status_capped(self):
        self.assertEqual(bridge_git.MAX_STATUS_FILES, 2000)
        for i in range(5):
            (self.repo / f"f{i}.txt").write_text("x\n")
        with mock.patch.object(bridge_git, "MAX_STATUS_FILES", 3):
            r = await self.call("git.status")
        self.assertTrue(r["truncated"])
        self.assertEqual(len(r["files"]), 3)
        self.assertFalse((await self.call("git.status"))["truncated"])


if __name__ == "__main__":
    unittest.main()
