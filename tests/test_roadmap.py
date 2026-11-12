"""Feuille de route : lecture de ROADMAP.md et case cochée au clic."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from ccs_app import roadmap

CCS_LIKE = """# Feuille de route — CCS

Texte libre.

- [ ] tâche hors phase

## Phase 1 — Multi-comptes (0.1.0) ✅

- [x] profils
- [x] usage

## Phase 2 — Orchestrateur (0.2.0 → 0.2.1) ✅

- [x] enchaînement

## Phase 12 — Chat (0.10.0)

- [x] protocole
- [ ] chat
  - [ ] sous-tâche
    - [x] sous-sous-tâche

## Phase 4 — Propositions (à choisir)

- [ ] idée

## Notes

Pas de case ici.

## Phase 9 — Reportés (correctif)

- [ ] détail
"""


class ParseTest(unittest.TestCase):
    def test_parse_ccs_like_file(self):
        rm = roadmap.parse(CCS_LIKE)
        self.assertEqual(rm.title, "Feuille de route — CCS")
        self.assertEqual([p.title for p in rm.phases], [
            "Phase 1 — Multi-comptes (0.1.0) ✅", "Phase 2 — Orchestrateur (0.2.0 → 0.2.1) ✅",
            "Phase 12 — Chat (0.10.0)", "Phase 4 — Propositions (à choisir)",
            "Phase 9 — Reportés (correctif)"])
        self.assertEqual([p.version for p in rm.phases],
                         ["0.1.0", "0.2.0 → 0.2.1", "0.10.0", None, None])
        p12 = rm.phases[2]
        self.assertEqual((p12.done_count, p12.total, p12.finished), (2, 4, False))
        self.assertTrue(rm.phases[0].finished)
        self.assertEqual(p12.line, CCS_LIKE.split("\n").index("## Phase 12 — Chat (0.10.0)") + 1)

    def test_nested_tasks_depth(self):
        p12 = roadmap.parse(CCS_LIKE).phases[2]
        self.assertEqual([(t.text, t.depth) for t in p12.tasks], [
            ("protocole", 0), ("chat", 0), ("sous-tâche", 1), ("sous-sous-tâche", 2)])

    def test_task_outside_phase_ignored(self):
        rm = roadmap.parse(CCS_LIKE)
        self.assertNotIn("tâche hors phase", [t.text for p in rm.phases for t in p.tasks])

    def test_crlf_and_fences(self):
        text = "# T\r\n## P (1.0)\r\n- [x] a\r\n```\r\n- [ ] dans un bloc\r\n```\r\n- [ ] b\r\n"
        rm = roadmap.parse(text)
        self.assertEqual([t.text for t in rm.phases[0].tasks], ["a", "b"])
        self.assertEqual(rm.phases[0].tasks[1].line, 7)

    def test_empty_text(self):
        rm = roadmap.parse("")
        self.assertEqual((rm.title, rm.phases), ("", []))


class ToggleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ROADMAP.md"

    def write(self, data: bytes):
        self.path.write_bytes(data)

    def test_toggle_changes_one_char_only(self):
        raw = CCS_LIKE.encode()
        self.write(raw)
        task = roadmap.parse(CCS_LIKE).phases[2].tasks[1]
        self.assertTrue(roadmap.toggle(self.path, task.line, task.text))
        new = self.path.read_bytes()
        self.assertEqual(len(new), len(raw))
        diff = [i for i in range(len(raw)) if raw[i] != new[i]]
        self.assertEqual(len(diff), 1)
        self.assertEqual((raw[diff[0]:diff[0] + 1], new[diff[0]:diff[0] + 1]), (b" ", b"x"))
        # et dans l'autre sens
        self.assertTrue(roadmap.toggle(self.path, task.line, task.text))
        self.assertEqual(self.path.read_bytes(), raw)

    def test_toggle_keeps_crlf(self):
        raw = b"# T\r\n## P (1.0)\r\n- [ ] a\r\n- [x] b\r\n"
        self.write(raw)
        self.assertTrue(roadmap.toggle(self.path, 3, "a"))
        self.assertEqual(self.path.read_bytes(), b"# T\r\n## P (1.0)\r\n- [x] a\r\n- [x] b\r\n")
        self.assertTrue(roadmap.toggle(self.path, 4, "b"))
        self.assertEqual(self.path.read_bytes(), b"# T\r\n## P (1.0)\r\n- [x] a\r\n- [ ] b\r\n")

    def test_toggle_refuses_changed_line(self):
        self.write(b"# T\n## P\n- [ ] a\n")
        self.assertFalse(roadmap.toggle(self.path, 3, "autre texte"))
        self.assertFalse(roadmap.toggle(self.path, 2, "P"))      # pas une case
        self.assertFalse(roadmap.toggle(self.path, 99, "a"))     # ligne absente
        self.assertFalse(roadmap.toggle(self.path.with_name("absent.md"), 3, "a"))
        self.assertEqual(self.path.read_bytes(), b"# T\n## P\n- [ ] a\n")

    def test_toggle_keeps_mode_and_symlink(self):
        self.write(b"## P\n- [ ] a\n")
        os.chmod(self.path, 0o640)
        link = Path(self.tmp.name) / "lien.md"
        link.symlink_to(self.path)
        self.assertTrue(roadmap.toggle(link, 2, "a"))
        self.assertTrue(link.is_symlink())
        self.assertEqual(self.path.read_bytes(), b"## P\n- [x] a\n")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)

    def test_toggle_non_utf8_bytes_preserved(self):
        raw = b"## P\n- [ ] a\n\xff\xfe binaire\n"
        self.write(raw)
        self.assertTrue(roadmap.toggle(self.path, 2, "a"))
        self.assertEqual(self.path.read_bytes(), b"## P\n- [x] a\n\xff\xfe binaire\n")


class NewlyDoneTest(unittest.TestCase):
    def test_duplicate_texts_newly_done(self):
        before = roadmap.parse("## A\n- [x] tests\n- [ ] tests\n## B\n- [ ] tests\n")
        after = roadmap.parse("## A\n- [x] tests\n- [x] tests\n## B\n- [ ] tests\n")
        done = roadmap.newly_done(before, after)
        self.assertEqual([(t.text, t.line) for t in done], [("tests", 3)])
        after2 = roadmap.parse("## A\n- [x] tests\n- [ ] tests\n## B\n- [x] tests\n")
        self.assertEqual([t.line for t in roadmap.newly_done(before, after2)], [5])
        self.assertEqual(roadmap.newly_done(before, before), [])

    def test_unchecked_and_new_tasks_not_reported(self):
        before = roadmap.parse("## A\n- [x] a\n")
        after = roadmap.parse("## A\n- [ ] a\n- [x] nouvelle\n")
        self.assertEqual(roadmap.newly_done(before, after), [])


class FindTest(unittest.TestCase):
    def git(self, cwd, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       cwd=cwd, check=True, capture_output=True)

    def test_find_walks_up_to_git_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            outer = Path(tmp)
            (outer / "ROADMAP.md").write_text("## X\n- [ ] au-dessus du dépôt\n")
            repo = outer / "repo"
            sub = repo / "a" / "b"
            sub.mkdir(parents=True)
            self.git(repo, "init", "-q")
            self.assertIsNone(roadmap.find(sub))            # ne dépasse pas la racine git
            (repo / "ROADMAP.md").write_text("## X\n- [ ] t\n")
            self.assertEqual(roadmap.find(sub), repo / "ROADMAP.md")
            (repo / "a" / "ROADMAP.md").write_text("## X\n- [ ] t\n")
            self.assertEqual(roadmap.find(sub), repo / "a" / "ROADMAP.md")
            self.assertEqual(roadmap.find(str(repo)), repo / "ROADMAP.md")

    def test_find_without_git_only_looks_in_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "ROADMAP.md").write_text("## X\n- [ ] t\n")
            sub = Path(tmp) / "sub"
            sub.mkdir()
            self.assertIsNone(roadmap.find(sub))
            self.assertEqual(roadmap.find(tmp), Path(tmp) / "ROADMAP.md")
            self.assertIsNone(roadmap.find(Path(tmp) / "absent"))


if __name__ == "__main__":
    unittest.main()
