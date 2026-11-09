"""Bornes de plage horaire en heure locale réelle, changements d'heure compris."""

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

from ccs_app import orchestrator as orch, pause
from ccs_app.core import Limit
from ccs_app.forecast import AccountState
from tests.test_orchestrator import cfg

PARIS = ZoneInfo("Europe/Paris")


def utc(month, day, hh, mm=0):
    return datetime(2026, month, day, hh, mm, tzinfo=timezone.utc)


class DaylightSavingTest(unittest.TestCase):
    """Plage 08:00 -> 02:00 en heure locale réelle (Europe/Paris, injectée)."""
    hours = {"start": "08:00", "end": "02:00", "days": list(range(7))}

    def test_spring_end_in_missing_hour_moves_to_first_valid_time(self):
        # Nuit du 28 au 29/03/2026 : 02:00 -> 03:00 n'existe pas, la fin devient 03:00 CEST.
        start, end = orch.period_bounds(utc(3, 28, 19), self.hours, PARIS)
        self.assertEqual(start, utc(3, 28, 7))    # 08:00 CET
        self.assertEqual(end, utc(3, 29, 1))      # 03:00 CEST
        self.assertEqual(end - start, timedelta(hours=18))

    def test_spring_after_shifted_end_is_outside(self):
        self.assertIsNotNone(orch.period_bounds(utc(3, 29, 0, 30), self.hours, PARIS))
        self.assertIsNone(orch.period_bounds(utc(3, 29, 1, 30), self.hours, PARIS))
        self.assertEqual(orch.next_period_start(utc(3, 29, 1, 30), self.hours, PARIS),
                         utc(3, 29, 6))           # 08:00 CEST

    def test_spring_start_in_missing_hour(self):
        hours = {"start": "02:30", "end": "06:00", "days": list(range(7))}
        self.assertEqual(orch.next_period_start(utc(3, 28, 12), hours, PARIS), utc(3, 29, 1))
        self.assertEqual(orch.period_bounds(utc(3, 29, 1, 10), hours, PARIS),
                         (utc(3, 29, 1), utc(3, 29, 4)))

    def test_autumn_end_in_doubled_hour_takes_first_occurrence(self):
        # Nuit du 24 au 25/10/2026 : 02:00 existe deux fois, on prend la première (CEST).
        start, end = orch.period_bounds(utc(10, 24, 12), self.hours, PARIS)
        self.assertEqual(start, utc(10, 24, 6))   # 08:00 CEST
        self.assertEqual(end, utc(10, 25, 0))     # 02:00 CEST
        self.assertEqual(end - start, timedelta(hours=18))
        self.assertIsNone(orch.period_bounds(utc(10, 25, 0, 30), self.hours, PARIS))
        self.assertEqual(orch.next_period_start(utc(10, 25, 0, 30), self.hours, PARIS),
                         utc(10, 25, 7))          # 08:00 CET

    def test_autumn_start_in_doubled_hour_takes_first_occurrence(self):
        hours = {"start": "02:30", "end": "06:00", "days": list(range(7))}
        self.assertEqual(orch.next_period_start(utc(10, 24, 12), hours, PARIS), utc(10, 25, 0, 30))

    def test_next_edge_and_pause_tomorrow_follow_the_real_clock(self):
        self.assertEqual(orch.next_edge(utc(3, 28, 19), self.hours, PARIS), utc(3, 29, 1))
        # Le soir du 28/03 : « demain » = 08:00 CEST (06:00 UTC), pas 07:00 UTC.
        self.assertEqual(pause.until_for("demain", utc(3, 28, 20), self.hours, PARIS), utc(3, 29, 6))

    def test_default_zone_is_the_system_one(self):
        with mock.patch.object(orch, "local_tz", return_value=PARIS):
            self.assertEqual(orch.period_bounds(utc(3, 28, 19), self.hours),
                             (utc(3, 28, 7), utc(3, 29, 1)))
            # Plan : les fenêtres de 5 h s'arrêtent à la fin réelle de la plage (00:00 UTC).
            now = utc(10, 24, 12)
            a = AccountState("a", True, [Limit("session", "S", 0.0, None)],
                             now.timestamp() - 30, None)
            starts = [w.start for w in orch.plan([a], now, cfg(active_hours=self.hours))
                      if w.kind == "planned"]
            self.assertEqual(starts, [utc(10, 24, 12), utc(10, 24, 17), utc(10, 24, 22)])

    def test_local_tz_reads_tz_variable(self):
        with mock.patch.dict(os.environ, {"TZ": "Europe/Paris"}):
            self.assertEqual(orch.local_tz().key, "Europe/Paris")


if __name__ == "__main__":
    unittest.main()
