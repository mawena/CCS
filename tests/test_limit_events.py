import json
import os
import time

from ccs_app import limit_events
from ccs_app.limit_events import LimitEvent
from tests.helpers import HomeTestCase, write

SID = "0f3c2a9e-1b2c-4d5e-8f90-123456789abc"


class RecordTest(HomeTestCase):
    def test_record_writes_one_private_file_per_conversation(self):
        self.assertTrue(limit_events.record(SID, 1000.0, source="perso", target="pro", switched=True,
                                            outcome="switched"))
        path = self.store / "limits" / f"{SID}.json"
        data = json.loads(path.read_text())
        self.assertEqual(data, {"session_id": SID, "ts": 1000.0, "from": "perso", "to": "pro",
                                "switched": True, "outcome": "switched"})
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(path.parent).st_mode & 0o777, 0o700)

    def test_later_record_replaces_the_pending_one(self):
        limit_events.record(SID, 1000.0, outcome="pending")
        limit_events.record(SID, 1001.0, source="perso", target=None, switched=False, outcome="exhausted")
        event = limit_events.load_all()[SID]
        self.assertEqual((event.ts, event.source, event.target, event.switched, event.outcome),
                         (1001.0, "perso", None, False, "exhausted"))

    def test_unusable_identifiers_are_refused(self):
        for bad in (None, "", "../x", "a/b", ".cache", "x" * 200, 12):
            self.assertFalse(limit_events.record(bad, 1.0, outcome="pending"))
        self.assertFalse((self.store / "limits").exists())

    def test_never_raises(self):
        write(self.store / "limits", "un fichier à la place du dossier")
        self.assertFalse(limit_events.record(SID, 1.0, outcome="pending"))

    def test_old_markers_are_pruned_when_writing(self):
        now = time.time()
        limit_events.record("ancien", now - limit_events.KEEP_S - 10, outcome="exhausted")
        old = self.store / "limits" / "ancien.json"
        os.utime(old, (now - limit_events.KEEP_S - 10,) * 2)
        limit_events.record(SID, now, outcome="pending")
        self.assertFalse(old.exists())
        self.assertIn(SID, limit_events.load_all())


class LoadTest(HomeTestCase):
    def test_load_skips_broken_or_foreign_files(self):
        limit_events.record(SID, 5.0, source="a", target="b", switched=True, outcome="switched")
        write(self.store / "limits" / "casse.json", "{pas du json")
        write(self.store / "limits" / "autre.json", {"session_id": "pas-le-meme", "ts": 1})
        write(self.store / "limits" / "liste.json", [1, 2])
        write(self.store / "limits" / "sans-ts.json", {"session_id": "sans-ts"})
        write(self.store / "limits" / "notes.txt", "x")
        self.assertEqual(list(limit_events.load_all()), [SID])

    def test_load_without_directory(self):
        self.assertEqual(limit_events.load_all(), {})

    def test_from_dict(self):
        e = LimitEvent.from_dict({"session_id": "s", "ts": 3, "from": "a", "to": "b", "switched": 1,
                                  "outcome": "switched"})
        self.assertEqual(e, LimitEvent("s", 3.0, "a", "b", True, "switched"))
        self.assertIsNone(LimitEvent.from_dict({"session_id": "s", "ts": "hier"}))
        self.assertIsNone(LimitEvent.from_dict({"ts": 3}))
        self.assertEqual(LimitEvent.from_dict({"session_id": "s", "ts": 3}).outcome, "pending")


class ConsumeTest(HomeTestCase):
    def test_consume_removes_only_the_event_that_was_handled(self):
        limit_events.record(SID, 10.0, outcome="switched", switched=True)
        self.assertFalse(limit_events.consume(SID, 9.0))   # un événement plus récent est arrivé
        self.assertIn(SID, limit_events.load_all())
        self.assertTrue(limit_events.consume(SID, 10.0))
        self.assertEqual(limit_events.load_all(), {})
        self.assertFalse(limit_events.consume(SID, 10.0))  # déjà consommé
        self.assertFalse(limit_events.consume("../x", 10.0))
