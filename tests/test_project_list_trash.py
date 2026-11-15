"""project_list (projets ajoutés / retirés) et trash (corbeille des conversations)."""

import os
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from tests.helpers import HomeTestCase

from ccs_app import archive, project_list, session_hub, sessions, trash


def conv(cwd, updated, sid="s1"):
    return NS(cwd=cwd, updated_at=updated, folder_exists=True, session_id=sid, title="t",
              first_prompt="", last_prompt="", origin="terminal", archived=False)


class ProjectListTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        os.environ.pop("XDG_DATA_HOME", None)
        self.proj = str(self.home / "p")
        os.mkdir(self.proj)

    def test_add_then_remove(self):
        project_list.add(self.proj, now=10)
        self.assertEqual(project_list.load(), ({self.proj: 10}, {}))
        project_list.remove(self.proj, now=20)
        self.assertEqual(project_list.load(), ({}, {self.proj: 20}))
        with self.assertRaises(ValueError):
            project_list.add("relatif")

    def test_hidden_until_newer_activity(self):
        removed = {self.proj: 100}
        self.assertEqual(project_list.hidden(removed, [conv(self.proj, 50)], []), {self.proj})
        self.assertEqual(project_list.hidden(removed, [conv(self.proj, 150)], []), set())
        self.assertEqual(project_list.hidden(removed, [], [NS(cwd=self.proj)]), set())

    def test_build_shows_added_and_hides_removed(self):
        other = str(self.home / "q")
        view = session_hub.build([conv(other, 50)], [], listing=({self.proj: 60}, {other: 100}))
        cwds = [e.cwd for e in view.entries]
        self.assertIn(self.proj, cwds)
        self.assertNotIn(other, cwds)
        self.assertEqual(view.conversations, [])


class TrashTest(HomeTestCase):
    SID = "0f0e0d0c-aaaa-bbbb-cccc-000000000001"

    def setUp(self):
        super().setUp()
        os.environ.pop("XDG_DATA_HOME", None)
        self.cwd = str(self.home / "p")
        self.journal = sessions.transcript_path(self.cwd, self.SID)
        self.journal.parent.mkdir(parents=True)
        self.journal.write_text('{"type":"user"}\n')
        (self.journal.with_suffix("") / "subagents").mkdir(parents=True)
        self.fh = Path.home() / ".claude" / "file-history" / self.SID
        self.fh.mkdir(parents=True)
        (self.fh / "h@v1").write_text("avant")

    def test_put_restore_roundtrip(self):
        tid = trash.put(self.journal, self.SID, self.cwd, "Titre", now=1000)
        self.assertFalse(self.journal.exists())
        self.assertFalse(self.fh.exists())
        [item] = trash.items()
        self.assertEqual((item["tid"], item["title"], item["cwd"]), (tid, "Titre", self.cwd))
        trash.restore(tid)
        self.assertTrue(self.journal.is_file())
        self.assertTrue((self.journal.with_suffix("") / "subagents").is_dir())
        self.assertEqual((self.fh / "h@v1").read_text(), "avant")
        self.assertEqual(trash.items(), [])

    def test_archive_copy_goes_with_it(self):
        archive.archive_pass(now=time.time() + 3 * 86400, idle_days=0)
        self.assertTrue(archive.find(self.SID))
        tid = trash.put(self.journal, self.SID, self.cwd, now=1000)
        self.assertIsNone(archive.find(self.SID))
        trash.restore(tid)
        self.assertTrue(archive.find(self.SID))

    def test_restore_refuses_to_overwrite(self):
        tid = trash.put(self.journal, self.SID, now=1000)
        self.journal.write_text("nouveau\n")
        with self.assertRaises(trash.TrashError):
            trash.restore(tid)
        self.assertEqual(self.journal.read_text(), "nouveau\n")

    def test_purge_after_30_days_and_bad_ids(self):
        trash.put(self.journal, self.SID, now=1000)
        self.assertEqual(trash.purge(now=1000 + 29 * 86400), 0)
        self.assertEqual(trash.purge(now=1000 + 31 * 86400), 1)
        for bad in ("", "../x", ".meta", None):
            with self.assertRaises(trash.TrashError):
                trash.restore(bad)

    def test_missing_conversation(self):
        with self.assertRaises(trash.TrashError):
            trash.put(self.journal.with_name("autre.jsonl"), "autre")


if __name__ == "__main__":
    unittest.main()
