"""Dépôt git : lecture (log, références, état, diff) et écritures, sur des dépôts temporaires."""

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from ccs_app import git_repo

IDENT = ["-c", "user.name=Test", "-c", "user.email=test@example.org",
         "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]


def g(repo, *args):
    """git de test (identité locale, aucune config de Charles)."""
    return subprocess.run(["git", *IDENT, "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


def commit_file(repo, name, text, msg=None):
    path = Path(repo) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    g(repo, "add", "--", name)
    g(repo, "commit", "-q", "-m", msg or f"ajoute {name}")
    return g(repo, "rev-parse", "HEAD").strip()


class GitTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-git-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = {k: os.environ.get(k) for k in ("HOME", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM")}
        os.environ["HOME"] = self.tmp
        os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
        cfg = Path(self.tmp) / "gitconfig"
        cfg.write_text("[user]\n\tname = Test\n\temail = test@example.org\n"
                       "[commit]\n\tgpgsign = false\n[init]\n\tdefaultBranch = main\n")
        os.environ["GIT_CONFIG_GLOBAL"] = str(cfg)
        self.addCleanup(self._restore_env)
        self.repo = Path(self.tmp) / "depot"
        self.repo.mkdir()
        g(self.repo, "init", "-q")

    def _restore_env(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def remote(self):
        """Distant nu local (file://), branche main poussée."""
        bare = Path(self.tmp) / "distant.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        g(self.repo, "remote", "add", "origin", bare.as_uri())
        return bare


class ReadTest(GitTestCase):
    def test_not_a_repo(self):
        other = Path(self.tmp) / "vide"
        other.mkdir()
        self.assertFalse(git_repo.is_repo(str(other)))
        self.assertTrue(git_repo.is_repo(str(self.repo)))
        with self.assertRaises(git_repo.GitError) as cm:
            git_repo.log(str(other))
        self.assertIn("git", cm.exception.command)

    def test_log_empty_repo(self):
        self.assertEqual(git_repo.log(str(self.repo)), [])
        self.assertEqual(git_repo.status(str(self.repo)), [])

    def test_log_parents_and_pages(self):
        c1 = commit_file(self.repo, "a.txt", "1\n", "premier")
        g(self.repo, "checkout", "-q", "-b", "feature/x")
        c2 = commit_file(self.repo, "b.txt", "2\n", "branche")
        g(self.repo, "checkout", "-q", "main")
        c3 = commit_file(self.repo, "c.txt", "3\n", "sur main")
        g(self.repo, "merge", "-q", "--no-ff", "-m", "fusion", "feature/x")
        merge = g(self.repo, "rev-parse", "HEAD").strip()
        commits = git_repo.log(str(self.repo))
        self.assertEqual(len(commits), 4)
        by_id = {c.id: c for c in commits}
        self.assertEqual(by_id[merge].parents, [c3, c2])
        self.assertEqual(by_id[c1].parents, [])
        self.assertEqual(by_id[merge].subject, "fusion")
        self.assertEqual(by_id[c1].author, "Test")
        self.assertEqual(by_id[c1].email, "test@example.org")
        self.assertGreater(by_id[c1].time, 1_600_000_000)
        page = git_repo.log(str(self.repo), skip=1, limit=1)
        self.assertEqual([c.id for c in page], [commits[1].id])

    def test_refs_kinds(self):
        c1 = commit_file(self.repo, "a.txt", "1\n")
        g(self.repo, "branch", "autre")
        g(self.repo, "tag", "-a", "v1.0", "-m", "version")
        refs = git_repo.refs(str(self.repo))
        kinds = {(r.name, r.kind) for r in refs}
        self.assertIn(("main", "branch"), kinds)
        self.assertIn(("autre", "branch"), kinds)
        self.assertIn(("v1.0", "tag"), kinds)
        self.assertIn(("HEAD", "head"), kinds)
        tag = next(r for r in refs if r.name == "v1.0")
        self.assertEqual(tag.target, c1)   # tag annoté : le commit, pas l'objet tag

    def test_branch_ahead_behind(self):
        commit_file(self.repo, "a.txt", "1\n")
        self.remote()
        g(self.repo, "push", "-q", "-u", "origin", "main")
        commit_file(self.repo, "b.txt", "2\n")
        b = git_repo.branch(str(self.repo))
        self.assertEqual(b.name, "main")
        self.assertEqual(b.upstream, "origin/main")
        self.assertEqual((b.ahead, b.behind), (1, 0))

    def test_branch_detached_and_no_upstream(self):
        c1 = commit_file(self.repo, "a.txt", "1\n")
        b = git_repo.branch(str(self.repo))
        self.assertEqual((b.name, b.upstream, b.ahead, b.behind), ("main", None, 0, 0))
        g(self.repo, "checkout", "-q", c1)
        self.assertIsNone(git_repo.branch(str(self.repo)).name)

    def test_status_odd_names(self):
        commit_file(self.repo, "suivi.txt", "a\n")
        commit_file(self.repo, "a b.txt", "a\n")
        (self.repo / "suivi.txt").write_text("b\n")
        (self.repo / "a b.txt").write_text("b\n")
        g(self.repo, "add", "a b.txt")
        (self.repo / 'é"t.txt').write_text("nouveau\n")
        st = {s.path: s for s in git_repo.status(str(self.repo))}
        self.assertEqual(set(st), {"suivi.txt", "a b.txt", 'é"t.txt'})
        self.assertEqual((st["suivi.txt"].staged, st["suivi.txt"].unstaged), (".", "M"))
        self.assertEqual((st["a b.txt"].staged, st["a b.txt"].unstaged), ("M", "."))
        self.assertEqual((st['é"t.txt'].staged, st['é"t.txt'].unstaged), ("?", "?"))

    def test_status_rename(self):
        commit_file(self.repo, "vieux.txt", "contenu\n" * 5)
        g(self.repo, "mv", "vieux.txt", "neuf.txt")
        st = git_repo.status(str(self.repo))
        self.assertEqual(len(st), 1)
        self.assertEqual((st[0].path, st[0].orig_path, st[0].staged), ("neuf.txt", "vieux.txt", "R"))

    def test_parse_diff_hunks(self):
        lines = [f"ligne {i}\n" for i in range(1, 31)]
        commit_file(self.repo, "f.txt", "".join(lines))
        lines[1] = "deux\n"
        lines[24] = "vingt-cinq\n"
        lines.insert(26, "insérée\n")
        (self.repo / "f.txt").write_text("".join(lines))
        fd = git_repo.diff(str(self.repo), "f.txt", staged=False)
        self.assertEqual(fd.path, "f.txt")
        self.assertFalse(fd.binary)
        self.assertEqual(len(fd.hunks), 2)
        h0 = fd.hunks[0]
        minus = [l for l in h0.lines if l.kind == "-"]
        plus = [l for l in h0.lines if l.kind == "+"]
        self.assertEqual((minus[0].text, minus[0].old_no, minus[0].new_no), ("ligne 2", 2, None))
        self.assertEqual((plus[0].text, plus[0].old_no, plus[0].new_no), ("deux", None, 2))
        ctx = h0.lines[0]
        self.assertEqual((ctx.kind, ctx.old_no, ctx.new_no), (" ", 1, 1))
        added = [l for l in fd.hunks[1].lines if l.kind == "+"]
        self.assertEqual([l.text for l in added], ["vingt-cinq", "insérée"])
        self.assertEqual(added[1].new_no, 27)

    def test_parse_diff_binary(self):
        (self.repo / "img.bin").write_bytes(b"\0\1\2")
        g(self.repo, "add", "img.bin")
        g(self.repo, "commit", "-q", "-m", "bin")
        (self.repo / "img.bin").write_bytes(b"\0\1\3\4")
        fd = git_repo.diff(str(self.repo), "img.bin", staged=False)
        self.assertTrue(fd.binary)
        self.assertEqual(fd.hunks, [])

    def test_diff_untracked_and_staged(self):
        commit_file(self.repo, "a.txt", "a\n")
        (self.repo / "neuf.txt").write_text("x\ny\n")
        fd = git_repo.diff(str(self.repo), "neuf.txt", staged=False)
        self.assertTrue(fd.new_file)
        self.assertEqual([l.text for l in fd.hunks[0].lines], ["x", "y"])
        (self.repo / "a.txt").write_text("b\n")
        g(self.repo, "add", "a.txt")
        self.assertIsNone(git_repo.diff(str(self.repo), "a.txt", staged=False))
        self.assertEqual(len(git_repo.diff(str(self.repo), "a.txt", staged=True).hunks), 1)

    def test_show_commit(self):
        commit_file(self.repo, "a.txt", "a\n")
        (self.repo / "a.txt").write_text("b\n")
        (self.repo / "c.txt").write_text("c\n")
        g(self.repo, "add", "-A")
        g(self.repo, "commit", "-q", "-m", "titre", "-m", "corps du message")
        cid = g(self.repo, "rev-parse", "HEAD").strip()
        c, files = git_repo.show(str(self.repo), cid)
        self.assertEqual((c.id, c.subject, c.body.strip()), (cid, "titre", "corps du message"))
        self.assertEqual(sorted(f.path for f in files), ["a.txt", "c.txt"])
        self.assertTrue(next(f for f in files if f.path == "c.txt").new_file)

    def test_show_root_commit(self):
        cid = commit_file(self.repo, "a.txt", "a\n")
        c, files = git_repo.show(str(self.repo), cid)
        self.assertEqual([f.path for f in files], ["a.txt"])


if __name__ == "__main__":
    unittest.main()
