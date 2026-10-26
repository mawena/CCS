from datetime import datetime, timezone

from ccs_app import core
from ccs_app.store import Store
from tests.helpers import HomeTestCase

R = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def limits(session, weekly):
    return [core.Limit("session", "S", session, R), core.Limit("weekly_all", "W", weekly, None)]


class StoreTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.db = Store()

    def test_default_path_and_permissions(self):
        path = self.store / "history.db"
        self.assertTrue(path.exists())
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")

    def test_samples_roundtrip_and_since_filter(self):
        self.db.add_samples(100.0, "perso", limits(10, 20))
        self.db.add_samples(200.0, "perso", limits(15, 21))
        self.db.add_samples(200.0, "pro", limits(50, 60))
        rows = self.db.samples("perso", "session", since=150.0)
        self.assertEqual(rows, [(200.0, 15.0, R.timestamp())])
        self.assertEqual(self.db.samples("perso", "weekly_all", since=0)[0], (100.0, 20.0, None))

    def test_active_periods_from_switch_events(self):
        self.db.add_event(0, "switch", "perso", {"mode": "manual"})
        self.db.add_event(100, "switch", "pro", {"mode": "auto", "from": "perso"})
        self.assertEqual(self.db.active_periods(0, 200),
                         [(0, 100, "perso"), (100, 200, "pro")])
        # Période commencée avant `since` : tronquée.
        self.assertEqual(self.db.active_periods(50, 200),
                         [(50, 100, "perso"), (100, 200, "pro")])

    def test_last_event_by_type_and_profile(self):
        self.db.add_event(1, "alert", "perso", {"key": "a"})
        self.db.add_event(2, "alert", "pro", {"key": "b"})
        self.db.add_event(3, "switch", "pro", {})
        self.assertEqual(self.db.last_event("alert").detail, {"key": "b"})
        self.assertEqual(self.db.last_event("alert", "perso").ts, 1)
        self.assertIsNone(self.db.last_event("warmup"))
        self.assertEqual([e.ts for e in self.db.events(0, type="alert")], [1, 2])

    def test_prune_removes_old_rows(self):
        self.db.add_samples(10, "perso", limits(1, 1))
        self.db.add_samples(1000, "perso", limits(2, 2))
        self.db.add_event(10, "alert", "perso", {})
        self.db.prune(before=500)
        self.assertEqual(len(self.db.samples("perso", "session", 0)), 1)
        self.assertEqual(self.db.events(0), [])
