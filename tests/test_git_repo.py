"""Dépôt git : lecture (log, références, état, diff) et écritures, sur des dépôts temporaires."""

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import git_repo
from tests.git_helpers import GitTestCase, commit_file, g

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


def thirty(repo, name="f.txt"):
    """Fichier de 30 lignes commité, puis deux blocs modifiés (lignes 2 et 25)."""
    lines = [f"ligne {i}\n" for i in range(1, 31)]
    commit_file(repo, name, "".join(lines))
    lines[1] = "deux\n"
    lines[24] = "vingt-cinq\n"
    (Path(repo) / name).write_text("".join(lines), encoding="utf-8")


def hunk_keys(fd, h):
    return {(h, i) for i, l in enumerate(fd.hunks[h].lines) if l.kind != " "}


class WriteTest(GitTestCase):
    def test_stage_unstage_file(self):
        commit_file(self.repo, "a.txt", "a\n")
        (self.repo / "a.txt").write_text("b\n")
        git_repo.stage_file(str(self.repo), "a.txt")
        self.assertEqual(git_repo.status(str(self.repo))[0].staged, "M")
        git_repo.unstage_file(str(self.repo), "a.txt")
        st = git_repo.status(str(self.repo))[0]
        self.assertEqual((st.staged, st.unstaged), (".", "M"))

    def test_unstage_in_empty_repo(self):
        (self.repo / "a.txt").write_text("a\n")
        git_repo.stage_file(str(self.repo), "a.txt")
        git_repo.unstage_file(str(self.repo), "a.txt")
        self.assertEqual(git_repo.status(str(self.repo))[0].staged, "?")

    def test_stage_lines_partial(self):
        thirty(self.repo)
        fd = git_repo.diff(str(self.repo), "f.txt", staged=False)
        git_repo.stage_lines(str(self.repo), fd, hunk_keys(fd, 0))
        cached = g(self.repo, "diff", "--cached")
        self.assertIn("+deux", cached)
        self.assertNotIn("vingt-cinq", cached)
        self.assertIn("+vingt-cinq", g(self.repo, "diff"))

    def test_stage_single_added_line_keeps_old(self):
        thirty(self.repo)
        fd = git_repo.diff(str(self.repo), "f.txt", staged=False)
        plus = next(i for i, l in enumerate(fd.hunks[0].lines) if l.kind == "+")
        git_repo.stage_lines(str(self.repo), fd, {(0, plus)})
        staged = g(self.repo, "show", ":f.txt").splitlines()
        self.assertEqual(staged[1:3], ["ligne 2", "deux"])

    def test_stage_lines_odd_name(self):
        thirty(self.repo, "a b é.txt")
        fd = git_repo.diff(str(self.repo), "a b é.txt", staged=False)
        git_repo.stage_lines(str(self.repo), fd, hunk_keys(fd, 1))
        cached = git_repo.diff(str(self.repo), "a b é.txt", staged=True)
        self.assertEqual(cached.path, "a b é.txt")
        self.assertEqual([l.text for l in cached.hunks[0].lines if l.kind == "+"], ["vingt-cinq"])

    def test_unstage_lines(self):
        thirty(self.repo)
        git_repo.stage_file(str(self.repo), "f.txt")
        fd = git_repo.diff(str(self.repo), "f.txt", staged=True)
        git_repo.unstage_lines(str(self.repo), fd, hunk_keys(fd, 0))
        cached = g(self.repo, "diff", "--cached")
        self.assertNotIn("deux", cached)
        self.assertIn("+vingt-cinq", cached)

    def test_discard_lines_keeps_other_hunk(self):
        thirty(self.repo)
        fd = git_repo.diff(str(self.repo), "f.txt", staged=False)
        git_repo.discard_lines(str(self.repo), fd, hunk_keys(fd, 1))
        text = (self.repo / "f.txt").read_text().splitlines()
        self.assertEqual((text[1], text[24]), ("deux", "ligne 25"))

    def test_discard_untracked(self):
        commit_file(self.repo, "a.txt", "a\n")
        (self.repo / "neuf.txt").write_text("x\n")
        fs = next(s for s in git_repo.status(str(self.repo)) if s.path == "neuf.txt")
        git_repo.discard_file(str(self.repo), fs)
        self.assertFalse((self.repo / "neuf.txt").exists())

    def test_discard_staged_and_added(self):
        commit_file(self.repo, "a.txt", "a\n")
        (self.repo / "a.txt").write_text("b\n")
        (self.repo / "n.txt").write_text("n\n")
        g(self.repo, "add", "-A")
        for fs in git_repo.status(str(self.repo)):
            git_repo.discard_file(str(self.repo), fs)
        self.assertEqual(git_repo.status(str(self.repo)), [])
        self.assertEqual((self.repo / "a.txt").read_text(), "a\n")
        self.assertFalse((self.repo / "n.txt").exists())

    def test_commit_and_amend(self):
        commit_file(self.repo, "a.txt", "a\n")
        (self.repo / "b.txt").write_text("b\n")
        git_repo.stage_file(str(self.repo), "b.txt")
        cid = git_repo.commit(str(self.repo), "feat: b\n\ncorps")
        self.assertEqual(cid, g(self.repo, "rev-parse", "HEAD").strip())
        self.assertEqual(git_repo.last_message(str(self.repo)), "feat: b\n\ncorps")
        git_repo.commit(str(self.repo), "feat: b corrigé", amend=True)
        self.assertEqual(len(git_repo.log(str(self.repo))), 2)
        self.assertEqual(git_repo.last_message(str(self.repo)), "feat: b corrigé")

    def test_commit_empty_message_fails(self):
        commit_file(self.repo, "a.txt", "a\n")
        (self.repo / "a.txt").write_text("b\n")
        git_repo.stage_file(str(self.repo), "a.txt")
        with self.assertRaises(git_repo.GitError):
            git_repo.commit(str(self.repo), "   ")

    def test_ignore_no_duplicate(self):
        commit_file(self.repo, ".gitignore", "*.log")      # pas de saut de ligne final
        git_repo.ignore(str(self.repo), "build/sortie.bin")
        git_repo.ignore(str(self.repo), "build/sortie.bin")
        self.assertEqual((self.repo / ".gitignore").read_text(), "*.log\n/build/sortie.bin\n")

    def test_push_sets_upstream(self):
        commit_file(self.repo, "a.txt", "a\n")
        bare = self.remote()
        git_repo.push(str(self.repo))
        self.assertIn("main", subprocess.run(["git", "-C", str(bare), "branch"], capture_output=True,
                                             text=True).stdout)
        self.assertEqual(git_repo.branch(str(self.repo)).upstream, "origin/main")

    def test_pull_ff_only(self):
        commit_file(self.repo, "a.txt", "a\n")
        bare = self.remote()
        git_repo.push(str(self.repo))
        other = Path(self.tmp) / "autre"
        subprocess.run(["git", "clone", "-q", bare.as_uri(), str(other)], check=True)
        commit_file(other, "b.txt", "b\n")
        g(other, "push", "-q")
        git_repo.fetch(str(self.repo))
        self.assertEqual(git_repo.branch(str(self.repo)).behind, 1)
        git_repo.pull(str(self.repo))
        self.assertTrue((self.repo / "b.txt").exists())

    def test_force_push_refuses_unseen_remote_commit(self):
        commit_file(self.repo, "a.txt", "a\n")
        bare = self.remote()
        git_repo.push(str(self.repo))
        other = Path(self.tmp) / "autre"
        subprocess.run(["git", "clone", "-q", bare.as_uri(), str(other)], check=True)
        commit_file(other, "b.txt", "b\n")
        g(other, "push", "-q")
        commit_file(self.repo, "c.txt", "c\n")
        with self.assertRaises(git_repo.GitError):
            git_repo.push(str(self.repo), force=True)

    def test_force_push_after_amend(self):
        commit_file(self.repo, "a.txt", "a\n")
        self.remote()
        git_repo.push(str(self.repo))
        git_repo.commit(str(self.repo), "réécrit", amend=True)
        with self.assertRaises(git_repo.GitError):
            git_repo.push(str(self.repo))
        git_repo.push(str(self.repo), force=True)
        self.assertEqual(git_repo.branch(str(self.repo)).ahead, 0)

    def test_fetch_never_prompts(self):
        commit_file(self.repo, "a.txt", "a\n")
        g(self.repo, "remote", "add", "origin", "https://127.0.0.1:9/x.git")
        start = time.monotonic()
        with self.assertRaises(git_repo.GitError):
            git_repo.fetch(str(self.repo))
        self.assertLess(time.monotonic() - start, 10)

    @unittest.skipUnless(git_repo.flow_available(), "git flow absent")
    def test_flow_feature_start_finish(self):
        commit_file(self.repo, "a.txt", "a\n")
        g(self.repo, "flow", "init", "-d")
        git_repo.flow(str(self.repo), "feature", "start", "essai")
        self.assertEqual(git_repo.branch(str(self.repo)).name, "feature/essai")
        commit_file(self.repo, "b.txt", "b\n")
        git_repo.flow(str(self.repo), "feature", "finish", "essai")
        self.assertEqual(git_repo.branch(str(self.repo)).name, "develop")
        self.assertTrue((self.repo / "b.txt").exists())

    @unittest.skipUnless(git_repo.flow_available(), "git flow absent")
    def test_flow_release_finish_tags(self):
        commit_file(self.repo, "a.txt", "a\n")
        g(self.repo, "flow", "init", "-d")
        git_repo.flow(str(self.repo), "release", "start", "1.0.0")
        git_repo.flow(str(self.repo), "release", "finish", "1.0.0")
        self.assertIn("1.0.0", g(self.repo, "tag"))

    def test_flow_bad_kind(self):
        with self.assertRaises(ValueError):
            git_repo.flow(str(self.repo), "support", "start", "x")

    def test_propose_message_docs(self):
        commit_file(self.repo, "README.md", "a\n")
        (self.repo / "README.md").write_text("b\n")
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "x.md").write_text("x\n")
        (self.repo / "code.py").write_text("non indexé\n")
        g(self.repo, "add", "README.md", "docs/x.md")
        msg = git_repo.propose_message(str(self.repo))
        self.assertTrue(msg.startswith("docs: "), msg)
        self.assertIn("- M README.md", msg)
        self.assertIn("- A docs/x.md", msg)
        self.assertNotIn("code.py", msg)

    def test_propose_message_single_and_empty(self):
        commit_file(self.repo, "a.py", "a\n")
        self.assertEqual(git_repo.propose_message(str(self.repo)), "")
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "t.py").write_text("t\n")
        g(self.repo, "add", "tests/t.py")
        self.assertEqual(git_repo.propose_message(str(self.repo)).splitlines()[0],
                         "test: ajoute tests/t.py")


class SafetyAndLimitsTest(GitTestCase):
    """Revue phase 14 : git.diff ne lit que les fichiers du dépôt, jamais l'entrée standard, et
    ne calcule pas le diff d'un fichier trop gros."""

    def test_run_never_reads_stdin(self):
        with mock.patch("subprocess.run", wraps=subprocess.run) as m:
            git_repo.run(self.repo, "status")
        self.assertIs(m.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def no_leak(self, path, secret):
        try:
            fd = git_repo.diff(str(self.repo), path, staged=False)
        except git_repo.GitError as e:
            self.assertNotIn(secret, e.output)
            return
        self.assertIsNone(fd, path)

    def test_diff_untracked_only_what_git_lists(self):
        commit_file(self.repo, "a.txt", "un\n")
        outside = Path(self.tmp) / "dehors"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret-dehors\n")
        (outside / "null").write_text("secret-null\n")
        os.symlink(outside, self.repo / "lnk")                       # lien vers un dossier hors du dépôt
        (self.repo / ".gitignore").write_text("cache.txt\n")
        (self.repo / "cache.txt").write_text("secret-ignore\n")
        (self.repo / "-").write_text("secret-tiret\n")
        self.no_leak("lnk/secret.txt", "secret-dehors")
        self.no_leak("lnk", "secret-null")
        self.no_leak("cache.txt", "secret-ignore")                  # ignoré : jamais montré
        self.no_leak("-", "secret-tiret")                           # « - » : l'entrée standard
        self.no_leak("*.txt", "secret")                             # motif : pris à la lettre
        (self.repo / "vrai.txt").write_text("x\n")
        self.assertTrue(git_repo.diff(str(self.repo), "vrai.txt", staged=False).new_file)

    def test_diff_too_big_is_not_computed(self):
        commit_file(self.repo, "a.txt", "un\n")
        (self.repo / "a.txt").write_text("x" * 200 + "\n")
        (self.repo / "neuf.txt").write_text("y" * 200 + "\n")
        for path in ("a.txt", "neuf.txt"):
            fd = git_repo.diff(str(self.repo), path, staged=False, max_bytes=100)
            self.assertTrue(fd.too_big, path)
            self.assertEqual(fd.hunks, [])
        g(self.repo, "add", "a.txt")
        (self.repo / "a.txt").write_text("court\n")
        self.assertTrue(git_repo.diff(str(self.repo), "a.txt", staged=True, max_bytes=100).too_big)
        self.assertTrue(git_repo.diff(str(self.repo), "a.txt", staged=False, max_bytes=100).too_big)
        fd = git_repo.diff(str(self.repo), "neuf.txt", staged=False)
        self.assertFalse(fd.too_big)
        self.assertEqual(len(fd.hunks), 1)


def commit_bytes(repo, name, data):
    (Path(repo) / name).write_bytes(data)
    g(repo, "add", "--", name)
    g(repo, "commit", "-q", "-m", f"ajoute {name}")


def index_bytes(repo, name):
    return subprocess.run(["git", "-C", str(repo), "show", f":{name}"], capture_output=True,
                          check=True).stdout


def kind_keys(fd, kind):
    return {(hi, li) for hi, h in enumerate(fd.hunks) for li, l in enumerate(h.lines) if l.kind == kind}


class BytesAndEolTest(GitTestCase):
    """Revue phase 14 : indexer un bloc garde les octets d'un fichier qui n'est pas en UTF-8 et
    la fin d'un fichier sans saut de ligne final."""

    def test_stage_hunk_keeps_latin1_bytes(self):
        base = [b"ligne %d\n" % i for i in range(1, 31)]
        base[3] = b"caf\xe9 cr\xe8me\n"                 # contexte en Latin-1
        commit_bytes(self.repo, "l1.txt", b"".join(base))
        lines = list(base)
        lines[1] = b"d\xe9but chang\xe9\n"               # bloc 0 : ligne en Latin-1
        lines[25] = b"fin chang\xe9e\n"                  # bloc 1
        (self.repo / "l1.txt").write_bytes(b"".join(lines))
        fd = git_repo.diff(str(self.repo), "l1.txt", staged=False)
        self.assertEqual(len(fd.hunks), 2)
        git_repo.stage_lines(str(self.repo), fd, hunk_keys(fd, 0))
        want = list(base)
        want[1] = lines[1]
        self.assertEqual(index_bytes(self.repo, "l1.txt"), b"".join(want))
        fd = git_repo.diff(str(self.repo), "l1.txt", staged=True)
        git_repo.unstage_lines(str(self.repo), fd, hunk_keys(fd, 0))
        self.assertEqual(index_bytes(self.repo, "l1.txt"), b"".join(base))

    def test_hunk_at_end_without_final_newline(self):
        commit_bytes(self.repo, "f.txt", b"a\nb")
        (self.repo / "f.txt").write_bytes(b"a\nc")
        fd = git_repo.diff(str(self.repo), "f.txt", staged=False)
        self.assertEqual([(l.kind, l.no_eol) for l in fd.hunks[0].lines],
                         [(" ", False), ("-", True), ("+", True)])
        git_repo.stage_lines(str(self.repo), fd, hunk_keys(fd, 0))
        self.assertEqual(index_bytes(self.repo, "f.txt"), b"a\nc")
        fd = git_repo.diff(str(self.repo), "f.txt", staged=True)
        git_repo.unstage_lines(str(self.repo), fd, hunk_keys(fd, 0))
        self.assertEqual(index_bytes(self.repo, "f.txt"), b"a\nb")
        fd = git_repo.diff(str(self.repo), "f.txt", staged=False)
        git_repo.discard_lines(str(self.repo), fd, hunk_keys(fd, 0))
        self.assertEqual((self.repo / "f.txt").read_bytes(), b"a\nb")

    def test_single_lines_around_missing_final_newline(self):
        """Choix ligne à ligne (bureau) près d'une fin sans saut de ligne : correctif valable,
        contenu exact."""
        repo = str(self.repo)
        commit_bytes(self.repo, "f.txt", b"a\nb")
        (self.repo / "f.txt").write_bytes(b"a\nc")
        for kind, want in (("+", b"a\nb\nc"), ("-", b"a\n")):
            g(self.repo, "reset", "-q")
            fd = git_repo.diff(repo, "f.txt", staged=False)
            git_repo.stage_lines(repo, fd, kind_keys(fd, kind))
            self.assertEqual(index_bytes(self.repo, "f.txt"), want, f"indexer {kind}")
        for kind, want in (("-", b"a\nb\nc"), ("+", b"a\n")):
            g(self.repo, "add", "f.txt")
            fd = git_repo.diff(repo, "f.txt", staged=True)
            git_repo.unstage_lines(repo, fd, kind_keys(fd, kind))
            self.assertEqual(index_bytes(self.repo, "f.txt"), want, f"désindexer {kind}")
        for kind, want in (("+", b"a\n"), ("-", b"a\nb\nc")):
            g(self.repo, "reset", "-q")
            (self.repo / "f.txt").write_bytes(b"a\nc")
            fd = git_repo.diff(repo, "f.txt", staged=False)
            git_repo.discard_lines(repo, fd, kind_keys(fd, kind))
            self.assertEqual((self.repo / "f.txt").read_bytes(), want, f"annuler {kind}")


class NetworkNoPromptTest(GitTestCase):
    """Revue phase 14 : fetch, pull et push ne demandent jamais de mot de passe et gardent le
    `core.sshCommand` du dépôt."""

    def setUp(self):
        super().setUp()
        commit_file(self.repo, "a.txt", "a\n")
        self.remote()

    def network_calls(self):
        """(env, options) de chaque git fetch / pull / push lancé par les trois fonctions."""
        with mock.patch("subprocess.run", wraps=subprocess.run) as m:
            git_repo.push(str(self.repo))
            git_repo.fetch(str(self.repo))
            git_repo.pull(str(self.repo))
        calls = [c for c in m.call_args_list if c.args and c.args[0][5:6] in (["fetch"], ["pull"], ["push"])]
        self.assertEqual([c.args[0][5] for c in calls], ["push", "fetch", "pull"])
        return calls

    def test_no_prompt_and_batch_ssh(self):
        for c in self.network_calls():
            env = c.kwargs["env"]
            for k, v in (("GIT_TERMINAL_PROMPT", "0"), ("GIT_ASKPASS", ""), ("SSH_ASKPASS", ""),
                         ("SSH_ASKPASS_REQUIRE", "never"), ("GCM_INTERACTIVE", "never"),
                         ("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")):
                self.assertEqual(env.get(k), v, (c.args[0][5], k))
            self.assertTrue(c.kwargs.get("start_new_session"), c.args[0][5])   # aucun terminal

    def test_repo_ssh_command_is_kept(self):
        g(self.repo, "config", "core.sshCommand", "ssh -i /chemin/cle")
        for c in self.network_calls():
            self.assertIsNone(c.kwargs["env"].get("GIT_SSH_COMMAND"), c.args[0][5])
            self.assertEqual(c.kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")

    def test_user_ssh_command_is_kept(self):
        with mock.patch.dict(os.environ, {"GIT_SSH_COMMAND": "ssh -F /chemin/config"}):
            for c in self.network_calls():
                self.assertEqual(c.kwargs["env"]["GIT_SSH_COMMAND"], "ssh -F /chemin/config")

    def test_desktop_pull_and_push_keep_the_session_password_window(self):
        """Le bureau (prompt=True) garde la fenêtre de mot de passe de la session (askpass) ;
        toujours sans terminal."""
        session = {"SSH_ASKPASS": "/usr/bin/ssh-askpass", "GIT_ASKPASS": "/usr/bin/git-askpass"}
        with mock.patch.dict(os.environ, session), \
                mock.patch("subprocess.run", wraps=subprocess.run) as m:
            git_repo.push(str(self.repo), prompt=True)
            git_repo.pull(str(self.repo), prompt=True)
        calls = [c for c in m.call_args_list if c.args and c.args[0][5:6] in (["pull"], ["push"])]
        self.assertEqual(len(calls), 2)
        for c in calls:
            env = c.kwargs["env"]
            self.assertEqual(env["SSH_ASKPASS"], "/usr/bin/ssh-askpass", c.args[0][5])
            self.assertEqual(env["GIT_ASKPASS"], "/usr/bin/git-askpass", c.args[0][5])
            self.assertNotIn("BatchMode", env.get("GIT_SSH_COMMAND", ""), c.args[0][5])
            self.assertTrue(c.kwargs.get("start_new_session"), c.args[0][5])


if __name__ == "__main__":
    unittest.main()
