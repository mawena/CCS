"""Sources distantes de l'espace de session : mêmes résultats que les fonctions locales, à travers
les vrais gestionnaires du pont (servis dans le processus, voir `remote_helpers`)."""

import unittest
from pathlib import Path

from ccs_app import file_tree, git_repo, roadmap
from ccs_app.remote.workspace import RemoteWorkspace
from tests.git_helpers import GitTestCase, commit_file, g
from tests.remote_helpers import InProcessClient


class RemoteWorkspaceTest(GitTestCase):
    def setUp(self):
        super().setUp()
        self.client = InProcessClient()
        self.addCleanup(self.client.close)
        self.ws = RemoteWorkspace(self.client, "serveur")
        self.root = str(self.repo)

    # ---- git ---------------------------------------------------------------------------

    def test_status_branch_and_diff_match_local(self):
        commit_file(self.repo, "a.txt", "un\ndeux\n")
        (self.repo / "a.txt").write_text("un\ntrois\n")
        (self.repo / "n.txt").write_text("neuf\n")
        rg = self.ws.git
        self.assertTrue(rg.is_repo(self.root))
        self.assertEqual(rg.status(self.root), git_repo.status(self.root))
        self.assertEqual(rg.branch(self.root), git_repo.branch(self.root))
        remote, local = rg.diff(self.root, "a.txt", False), git_repo.diff(self.root, "a.txt", False)
        self.assertEqual([(l.kind, l.text) for h in remote.hunks for l in h.lines],
                         [(l.kind, l.text) for h in local.hunks for l in h.lines])
        self.assertEqual([h.header for h in remote.hunks], [h.header for h in local.hunks])
        self.assertIsNone(rg.diff(self.root, "a.txt", True))

    def test_not_a_repo(self):
        plain = Path(self.tmp) / "simple"
        plain.mkdir()
        self.assertFalse(self.ws.git.is_repo(str(plain)))
        with self.assertRaises(git_repo.GitError):
            self.ws.git.branch(str(plain))

    def test_stage_lines_commit_and_messages(self):
        base = "".join(f"l{i}\n" for i in range(10))
        commit_file(self.repo, "a.txt", base)
        lines = base.splitlines(keepends=True)
        lines[2], lines[3] = "CHANGE1\n", "CHANGE2\n"
        (self.repo / "a.txt").write_text("".join(lines))
        rg = self.ws.git
        fd = rg.diff(self.root, "a.txt", False)
        keep = {(0, i) for i, l in enumerate(fd.hunks[0].lines) if l.text in ("l2", "CHANGE1")}
        rg.stage_lines(self.root, fd, keep)
        staged = g(self.repo, "diff", "--cached")
        self.assertIn("+CHANGE1", staged)
        self.assertNotIn("CHANGE2", staged)
        self.assertTrue(rg.propose_message(self.root))
        cid = rg.commit(self.root, "partiel")
        self.assertEqual(g(self.repo, "rev-parse", "HEAD").strip(), cid)
        self.assertEqual(rg.last_message(self.root).strip(), "partiel")
        rg.stage_file(self.root, "a.txt")
        self.assertEqual(rg.status(self.root)[0].staged, "M")
        rg.unstage_file(self.root, "a.txt")
        self.assertEqual(rg.status(self.root)[0].staged, ".")

    def test_log_refs_show(self):
        first = commit_file(self.repo, "a.txt", "un\n")
        second = commit_file(self.repo, "b.txt", "deux\n")
        rg = self.ws.git
        log = rg.log(self.root, 0, 10)
        self.assertEqual([c.id for c in log], [second, first])
        self.assertEqual(log, git_repo.log(self.root, 0, 10))
        self.assertEqual(sorted(rg.refs(self.root), key=lambda r: (r.kind, r.name)),
                         sorted(git_repo.refs(self.root), key=lambda r: (r.kind, r.name)))
        c, diffs = rg.show(self.root, second)
        self.assertEqual((c.subject, c.parents), ("ajoute b.txt", [first]))
        self.assertEqual([d.path for d in diffs], ["b.txt"])

    def test_errors_become_git_errors(self):
        commit_file(self.repo, "a.txt", "un\n")
        with self.assertRaises(git_repo.GitError) as cm:
            self.ws.git.push(self.root)
        self.assertTrue(str(cm.exception))
        self.client.offline = True
        self.ws.git.forget()
        with self.assertRaises(git_repo.GitError) as cm:
            self.ws.git.status(self.root)
        self.assertIn("injoignable", str(cm.exception))
        self.assertFalse(self.ws.git.is_repo(self.root))

    def test_status_is_reused_within_one_refresh(self):
        commit_file(self.repo, "a.txt", "un\n")
        rg = self.ws.git
        rg.is_repo(self.root)
        rg.branch(self.root)
        rg.status(self.root)
        self.assertEqual(self.client.calls.count("git.status"), 1)
        rg.stage_file(self.root, "a.txt")         # une écriture oublie l'état gardé
        rg.status(self.root)
        self.assertEqual(self.client.calls.count("git.status"), 2)

    def test_unsupported_operations_are_absent(self):
        rg = self.ws.git
        for name in ("discard_file", "discard_lines", "ignore", "flow"):
            self.assertIsNone(getattr(rg, name))
        self.assertFalse(rg.flow_available())

    # ---- fichiers ----------------------------------------------------------------------

    def test_marks_and_listing_match_local(self):
        from ccs_app.gui.file_panel import _list_dir
        commit_file(self.repo, "a.txt", "un\n")
        commit_file(self.repo, "src/b.txt", "b\n")
        (self.repo / "a.txt").write_text("deux\n")
        (self.repo / "src" / "b.txt").unlink()
        (self.repo / ".gitignore").write_text("*.log\n")
        (self.repo / "x.log").write_text("x\n")
        (self.repo / "node_modules").mkdir()
        rf = self.ws.files
        marks = rf.git_marks(self.root)
        self.assertEqual(marks, file_tree.git_marks(self.root))
        for show in (False, True):
            for d in (self.root, str(self.repo / "src")):
                self.assertEqual(rf.list_dir(self.root, d, show, marks),
                                 _list_dir(self.root, d, show, marks), (d, show))

    def test_marks_of_a_subfolder_are_relative_to_it(self):
        commit_file(self.repo, "src/b.txt", "b\n")
        (self.repo / "src" / "b.txt").write_text("c\n")
        self.assertEqual(self.ws.files.git_marks(str(self.repo / "src")), {"b.txt": "M"})

    def test_read_and_save_with_stamp(self):
        p = self.repo / "a.txt"
        p.write_text("un\n")
        rf = self.ws.files
        kind, text, enc, truncated, stamp = rf.read(str(p))
        self.assertEqual((kind, text, enc, truncated), ("text", "un\n", "utf-8", False))
        stamp = rf.save(str(p), "deux\n", "utf-8", stamp)
        self.assertEqual(p.read_text(), "deux\n")
        p.write_text("ailleurs\n")
        with self.assertRaises(OSError):
            rf.save(str(p), "trois\n", "utf-8", stamp)    # changé depuis l'ouverture
        self.assertEqual(rf.read(str(self.repo / "absent.txt"))[0], "missing")
        self.assertEqual(rf.read("/etc/passwd")[0], "unavailable")

    def test_read_image_gives_bytes(self):
        png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
               b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe"
               b"\x02\xfe\xa75\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82")
        (self.repo / "i.png").write_bytes(png)
        kind, data, *_ = self.ws.files.read(str(self.repo / "i.png"))
        self.assertEqual((kind, data), ("image", png))

    # ---- feuille de route --------------------------------------------------------------

    def test_roadmap_load_and_toggle(self):
        commit_file(self.repo, "a.txt", "un\n")
        rm_path = self.repo / "ROADMAP.md"
        rm_path.write_text("# Projet\n\n## Phase 1\n\n- [ ] faire a\n- [x] faire b\n")
        rr = self.ws.roadmap
        path, rm, project = rr.load(self.root)
        self.assertEqual(path, Path(rm_path))
        self.assertEqual(rm, roadmap.parse(rm_path.read_text(), rm_path))
        task = rm.phases[0].tasks[0]
        self.assertTrue(rr.toggle(path, task.line, task.text))
        self.assertIn("- [x] faire a", rm_path.read_text())
        self.assertFalse(rr.toggle(path, task.line, "autre texte"))

    def test_roadmap_followed_and_missing(self):
        other = Path(self.tmp) / "ailleurs"
        other.mkdir()
        (other / "ROADMAP.md").write_text("## P\n\n- [ ] t\n")
        rr = self.ws.roadmap
        path, rm, _ = rr.load(self.root, followed=other / "ROADMAP.md")
        self.assertEqual(path, other / "ROADMAP.md")
        self.assertEqual(rm.phases[0].tasks[0].text, "t")
        path, rm, project = rr.load(self.root)
        self.assertEqual((path, rm, project), (None, None, True))
        self.assertFalse(rr.load(str(other / "x"))[2])

    def test_night_task_goes_to_server_queue(self):
        from ccs_app import tasks
        rm_path = self.repo / "ROADMAP.md"
        rm_path.write_text("## P\n\n- [ ] t\n")
        self.ws.add_night_task(self.root, "Fais t", {"path": str(rm_path), "text": "t", "phase": "P"})
        queued = tasks.all()
        self.assertEqual(len(queued), 1)
        self.assertEqual((queued[0].cwd, queued[0].when), (str(self.repo), "nuit"))
        with self.assertRaises(ValueError):
            self.ws.add_night_task("/etc", "x", None)


if __name__ == "__main__":
    unittest.main()
