"""file_history : lecture des copies de Claude Code, changements, retour en arrière.
Journal et copies construits à la main dans un dossier temporaire."""

import json
import os
import unittest
from pathlib import Path

from tests.helpers import HomeTestCase

from ccs_app import file_history as fh


def snap_line(message_id, files, update=False):
    """Ligne `file-history-snapshot` ; files : {chemin: (nom de copie ou None, version)}."""
    return json.dumps({
        "type": "file-history-snapshot", "messageId": message_id, "isSnapshotUpdate": update,
        "snapshot": {"messageId": message_id, "timestamp": "2026-11-15T10:00:00Z",
                     "trackedFileBackups": {
                         p: {"backupFileName": name, "version": v,
                             "backupTime": "2026-11-15T10:00:00Z"}
                         for p, (name, v) in files.items()}}})


class FileHistoryCase(HomeTestCase):
    SESSION = "sess-1"

    def setUp(self):
        super().setUp()
        self.proj = Path(self.tmp) / "projet"
        self.proj.mkdir()
        self.config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or self.home / ".claude")
        self.copies = self.config / "file-history" / self.SESSION
        self.copies.mkdir(parents=True)
        self.journal = self.config / "projects" / "-p" / f"{self.SESSION}.jsonl"
        self.journal.parent.mkdir(parents=True)

    def copy(self, name, text):
        (self.copies / name).write_bytes(text.encode())

    def write_journal(self, *lines):
        self.journal.write_text("\n".join(lines) + "\n")

    def f(self, name):
        return str(self.proj / name)


class ReadTest(FileHistoryCase):
    def test_read_unknown_format_is_none(self):
        self.write_journal(json.dumps({"type": "user"}),
                           json.dumps({"type": "file-history-snapshot", "autre": 1}))
        self.assertIsNone(fh.read(self.journal))

    def test_read_without_snapshots_is_empty(self):
        self.write_journal(json.dumps({"type": "user"}))
        self.assertEqual(fh.read(self.journal), [])

    def test_update_replaces_snapshot(self):
        a = self.f("a.txt")
        self.write_journal(snap_line("m1", {a: ("h1@v1", 1)}),
                           snap_line("m2", {a: ("h1@v2", 2)}),
                           snap_line("m1", {a: ("h1@v1", 1), self.f("b.txt"): (None, 1)},
                                     update=True))
        snaps = fh.read(self.journal)
        self.assertEqual([s.message_id for s in snaps], ["m1", "m2"])
        self.assertEqual(sorted(snaps[0].files), sorted([a, self.f("b.txt")]))
        self.assertIsNone(snaps[0].files[self.f("b.txt")].name)


class UserMessagesTest(FileHistoryCase):
    def test_user_messages_skip_tool_results(self):
        self.write_journal(
            json.dumps({"type": "user", "uuid": "u1", "timestamp": "t1",
                        "message": {"role": "user", "content": "Bonjour"}}),
            json.dumps({"type": "assistant", "uuid": "a1", "message": {"content": []}}),
            json.dumps({"type": "user", "uuid": "r1", "message": {
                "role": "user", "content": [{"type": "tool_result", "content": "ok"}]}}),
            json.dumps({"type": "user", "uuid": "u2", "timestamp": "t2", "message": {
                "role": "user", "content": [{"type": "text", "text": "Suite"}]}}),
            json.dumps({"type": "user", "uuid": "m1", "isMeta": True,
                        "message": {"role": "user", "content": "méta"}}))
        got = fh.user_messages(self.journal)
        self.assertEqual([(m.message_id, m.text) for m in got], [("u1", "Bonjour"), ("u2", "Suite")])


class ChangesTest(FileHistoryCase):
    def test_changes_before_conversation(self):
        a, b, c = self.f("a.txt"), self.f("b.txt"), self.f("c.txt")
        self.copy("h@v1", "A0\n")
        self.copy("h@v2", "A1\n")
        self.copy("k@v1", "B0\n")
        (self.proj / "a.txt").write_text("A2\n")
        (self.proj / "b.txt").write_text("B0\n")            # revenu comme avant : pas un changement
        (self.proj / "c.txt").write_text("nouveau\n")       # créé pendant la conversation
        self.write_journal(snap_line("m1", {a: ("h@v1", 1), b: ("k@v1", 1), c: (None, 1)}),
                           snap_line("m2", {a: ("h@v2", 2), b: ("k@v1", 1), c: (None, 1)}))
        got = {ch.path: ch for ch in fh.changes(fh.read(self.journal), self.SESSION)}
        self.assertEqual(sorted(got), [a, c])
        self.assertEqual((got[a].before, got[a].now), (b"A0\n", b"A2\n"))
        self.assertEqual((got[c].before, got[c].now), (None, b"nouveau\n"))


class RewindTest(FileHistoryCase):
    def prepare(self):
        a, c, d = self.f("a.txt"), self.f("c.txt"), self.f("d.txt")
        self.copy("h@v1", "A0\n")
        self.copy("h@v2", "A1\n")
        self.copy("d@v1", "D0\n")
        self.write_journal(snap_line("m1", {a: ("h@v1", 1)}),
                           snap_line("m2", {a: ("h@v2", 2), c: (None, 1)}),
                           snap_line("m3", {a: ("h@v2", 2), c: (None, 1), d: ("d@v1", 1)}))
        return a, c, d

    def test_rewind_restores_and_deletes_created(self):
        a, c, d = self.prepare()
        (self.proj / "a.txt").write_text("A1\n")
        (self.proj / "c.txt").write_text("créé par Claude\n")
        (self.proj / "d.txt").write_text("D1\n")
        steps = {s.path: s for s in fh.rewind_plan(fh.read(self.journal), self.SESSION, "m2")}
        self.assertNotIn(a, steps)                        # la copie de m2 est déjà l'état actuel
        self.assertIn(c, steps)
        self.assertIsNone(steps[c].content)               # créé pour m2 (copie nulle) : supprimé
        self.assertEqual(steps[d].content, b"D0\n")       # suivi après m2 : sa plus ancienne copie

    def test_rewind_flags_user_edit(self):
        a, c, d = self.prepare()
        (self.proj / "a.txt").write_text("à la main\n")     # ne correspond à aucune copie
        (self.proj / "d.txt").write_text("D0\n")
        steps = {s.path: s for s in fh.rewind_plan(fh.read(self.journal), self.SESSION, "m1")}
        self.assertEqual(steps[a].content, b"A0\n")
        self.assertTrue(steps[a].user_edited)
        self.assertNotIn(d, steps)                          # déjà identique : rien à écrire

    def test_rewind_refuses_message_without_snapshot(self):
        """Sans instantané pour ce message, l'état d'avant lui est inconnu : erreur, et non un
        retour à l'état d'avant la conversation."""
        a, c, d = self.prepare()
        (self.proj / "a.txt").write_text("A1\n")
        with self.assertRaises(fh.NoSnapshot):
            fh.rewind_plan(fh.read(self.journal), self.SESSION, "m-sans-instantane")
        self.assertIsInstance(fh.NoSnapshot("x"), LookupError)

    def test_apply_atomic(self):
        target = self.proj / "sous" / "x.txt"
        gone = self.proj / "y.txt"
        gone.write_text("à supprimer")
        fh.apply([fh.Step(str(target), b"contenu\n", False), fh.Step(str(gone), None, False),
                  fh.Step(str(self.proj / "absent.txt"), None, False)])
        self.assertEqual(target.read_bytes(), b"contenu\n")
        self.assertFalse(gone.exists())
        self.assertEqual([p.name for p in target.parent.iterdir()], ["x.txt"])   # pas de reste


class CheckTest(FileHistoryCase):
    def test_check_reports_unknown(self):
        self.write_journal(json.dumps({"type": "file-history-snapshot", "autre": 1}))
        ok, text = fh.check()
        self.assertFalse(ok)
        self.assertIn("format inconnu", text)

    def test_check_reports_known(self):
        self.write_journal(snap_line("m1", {self.f("a.txt"): ("h@v1", 1)}))
        self.assertEqual(fh.check(), (True, "format reconnu"))

    def test_check_without_history(self):
        ok, _text = fh.check()
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
