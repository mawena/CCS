"""Volet « Changements de la session » : fichiers changés, annuler un fichier. Sous Xvfb."""

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import HomeTestCase, gui_ready

GTK = gui_ready()
if GTK:
    from gi.repository import GLib
    from ccs_app.gui.session_changes import ChangesPanel


def spin(until, timeout=8.0):
    ctx = GLib.MainContext.default()
    deadline = GLib.get_monotonic_time() + int(timeout * 1e6)
    while not until() and GLib.get_monotonic_time() < deadline:
        ctx.iteration(False)
    return until()


def snap_line(message_id, files):
    return json.dumps({
        "type": "file-history-snapshot", "messageId": message_id, "isSnapshotUpdate": False,
        "snapshot": {"messageId": message_id, "timestamp": "2026-11-15T10:00:00Z",
                     "trackedFileBackups": {
                         p: {"backupFileName": n, "version": 1,
                             "backupTime": "2026-11-15T10:00:00Z"} for p, (n) in files.items()}}})


def user_line(uuid, text):
    return json.dumps({"type": "user", "uuid": uuid, "timestamp": "2026-11-15T10:00:00Z",
                       "message": {"role": "user", "content": text}})


@unittest.skipUnless(GTK, "affichage graphique requis (CCS_GUI_TESTS=1 sous xvfb-run)")
class ChangesPanelTest(HomeTestCase):
    SESSION = "sess-9"

    def setUp(self):
        super().setUp()
        self.proj = Path(self.tmp) / "projet"
        self.proj.mkdir()
        config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or self.home / ".claude")
        copies = config / "file-history" / self.SESSION
        copies.mkdir(parents=True)
        (copies / "h@v1").write_bytes(b"avant\n")
        self.journal = config / "projects" / "-p" / f"{self.SESSION}.jsonl"
        self.journal.parent.mkdir(parents=True)
        self.a = str(self.proj / "a.txt")
        self.b = str(self.proj / "b.txt")
        (self.proj / "a.txt").write_text("après\n")
        (self.proj / "b.txt").write_text("nouveau\n")
        self.journal.write_text("\n".join([
            user_line("u1", "Premier message de la session"),
            snap_line("u1", {self.a: "h@v1", self.b: None}),
        ]) + "\n")

    def panel(self):
        p = ChangesPanel(self.journal, self.SESSION)
        p.refresh()
        self.assertTrue(spin(lambda: p.loaded()))
        return p

    def test_lists_changed_files(self):
        p = self.panel()
        self.assertEqual(sorted(p.file_paths()), sorted([self.a, self.b]))
        self.assertEqual([c.message_id for c in p.checkpoints()], ["u1"])

    def test_undo_file_after_confirm(self):
        p = self.panel()
        asked = []
        with mock.patch.object(p, "_confirm", lambda h, b, label, yes: asked.append(yes)):
            p.undo_file(self.a)
            self.assertEqual((self.proj / "a.txt").read_text(), "après\n")   # rien avant l'accord
            self.assertEqual(len(asked), 1)
            asked[0]()
        self.assertTrue(spin(lambda: (self.proj / "a.txt").read_text() == "avant\n"))
        self.assertTrue(spin(lambda: self.a not in p.file_paths()))

    def test_undo_created_file_deletes_it(self):
        p = self.panel()
        with mock.patch.object(p, "_confirm", lambda h, b, label, yes: yes()):
            p.undo_file(self.b)
        self.assertTrue(spin(lambda: not (self.proj / "b.txt").exists()))

    def test_unknown_format_offers_nothing(self):
        self.journal.write_text(json.dumps({"type": "file-history-snapshot", "autre": 1}) + "\n")
        p = self.panel()
        self.assertTrue(p.unknown_format())
        self.assertEqual(p.file_paths(), [])
        self.assertEqual(p.checkpoints(), [])
        self.assertFalse(p.has_actions())


if __name__ == "__main__":
    unittest.main()
