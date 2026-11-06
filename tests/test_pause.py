import json
import os
import stat
from datetime import datetime, timedelta, timezone

from ccs_app import pause
from ccs_app.settings import DEFAULTS
from tests.helpers import HomeTestCase, write

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)
HOURS = {"start": "08:00", "end": "02:00", "days": [0, 1, 2, 3, 4, 5, 6]}


def local(day, hh, mm=0):
    """Heure locale du 26/10/2026 (lundi) + `day` jours."""
    return (datetime(2026, 10, 26, hh, mm) + timedelta(days=day)).astimezone()


class PauseStateTest(HomeTestCase):
    def test_not_paused_by_default(self):
        self.assertIsNone(pause.pause_state(NOW))

    def test_pause_until_a_date(self):
        until = NOW + timedelta(hours=1)
        st = pause.set_pause(until, now=NOW)
        self.assertEqual((st.since, st.until), (NOW, until))
        read = pause.pause_state(NOW + timedelta(minutes=30))
        self.assertEqual((read.since, read.until), (NOW, until))
        self.assertEqual(json.loads((self.store / "pause.json").read_text())["until"],
                         until.timestamp())

    def test_pause_file_is_private(self):
        pause.set_pause(None, now=NOW)
        mode = stat.S_IMODE(os.stat(self.store / "pause.json").st_mode)
        self.assertEqual(mode, 0o600)

    def test_pause_ends_at_its_deadline(self):
        pause.set_pause(NOW + timedelta(hours=1), now=NOW)
        self.assertIsNone(pause.pause_state(NOW + timedelta(hours=1)))
        self.assertIsNone(pause.pause_state(NOW + timedelta(hours=2)))

    def test_manual_pause_has_no_deadline(self):
        pause.set_pause(None, now=NOW)
        st = pause.pause_state(NOW + timedelta(days=30))
        self.assertIsNotNone(st)
        self.assertIsNone(st.until)

    def test_clear_pause(self):
        pause.set_pause(None, now=NOW)
        pause.clear_pause()
        self.assertIsNone(pause.pause_state(NOW))
        pause.clear_pause()  # déjà levée : pas d'erreur

    def test_unreadable_file_means_no_pause(self):
        for content in ("{oups", {}, {"since": "hier"}, {"since": NOW.timestamp(), "until": "x"}, []):
            write(self.store / "pause.json", content)
            self.assertIsNone(pause.pause_state(NOW), content)

    def test_expire_lifts_a_finished_pause_once(self):
        pause.set_pause(NOW + timedelta(hours=1), now=NOW)
        self.assertIsNone(pause.expire(NOW + timedelta(minutes=59)))
        ended = pause.expire(NOW + timedelta(hours=1, seconds=1))
        self.assertEqual(ended.since, NOW)
        self.assertFalse((self.store / "pause.json").exists())
        self.assertIsNone(pause.expire(NOW + timedelta(hours=2)))

    def test_expire_keeps_manual_pause(self):
        pause.set_pause(None, now=NOW)
        self.assertIsNone(pause.expire(NOW + timedelta(days=3)))
        self.assertIsNotNone(pause.pause_state(NOW + timedelta(days=3)))

    def test_as_dict(self):
        st = pause.set_pause(NOW + timedelta(hours=4), now=NOW)
        d = st.as_dict(NOW)
        self.assertEqual(d["since"], NOW.isoformat())
        self.assertEqual(d["until"], (NOW + timedelta(hours=4)).isoformat())
        self.assertTrue(d["label"].startswith("jusqu'à"))
        self.assertIsNone(pause.set_pause(None, now=NOW).as_dict(NOW)["until"])


class PauseChoicesTest(HomeTestCase):
    def test_durations(self):
        self.assertEqual(pause.until_for("1h", NOW, HOURS), NOW + timedelta(hours=1))
        self.assertEqual(pause.until_for("4h", NOW, HOURS), NOW + timedelta(hours=4))
        self.assertIsNone(pause.until_for("manuel", NOW, HOURS))

    def test_until_tomorrow_is_next_active_period_start(self):
        self.assertEqual(pause.until_for("demain", local(0, 10), HOURS), local(1, 8))
        # 01:00 appartient encore à la période de la veille : reprise à 08:00 le jour même.
        self.assertEqual(pause.until_for("demain", local(1, 1), HOURS), local(1, 8))
        self.assertEqual(pause.until_for("demain", local(0, 8), HOURS), local(1, 8))

    def test_until_tomorrow_skips_inactive_days(self):
        weekdays = dict(HOURS, days=[0, 1, 2, 3, 4])
        # Vendredi 30/10 à 10:00 → lundi 02/11 à 08:00.
        self.assertEqual(pause.until_for("demain", local(4, 10), weekdays), local(7, 8))

    def test_until_tomorrow_without_active_day_falls_back_to_next_morning(self):
        self.assertEqual(pause.until_for("demain", local(0, 10), dict(HOURS, days=[])), local(1, 8))

    def test_default_hours_come_from_settings(self):
        self.assertEqual(pause.until_for("demain", local(0, 10)),
                         pause.until_for("demain", local(0, 10),
                                         DEFAULTS["orchestrator"]["active_hours"]))

    def test_unknown_choice(self):
        with self.assertRaises(ValueError):
            pause.until_for("2j", NOW, HOURS)

    def test_apply_and_resume(self):
        st = pause.apply("4h", NOW)
        self.assertEqual(st.until, NOW + timedelta(hours=4))
        self.assertIsNotNone(pause.pause_state(NOW))
        self.assertIsNone(pause.apply("reprendre", NOW))
        self.assertIsNone(pause.pause_state(NOW))

    def test_labels(self):
        self.assertEqual(pause.label(None, NOW), "")
        manual = pause.PauseState(NOW, None)
        self.assertEqual(pause.label(manual, NOW), "jusqu'à reprise manuelle")
        soon = pause.PauseState(NOW, local(0, 14))
        self.assertEqual(pause.label(soon, local(0, 10)), "jusqu'à 14:00")
        tomorrow = pause.PauseState(NOW, local(1, 8))
        self.assertEqual(pause.label(tomorrow, local(0, 10)), "jusqu'à demain 08:00")
        later = pause.PauseState(NOW, local(3, 8))
        self.assertEqual(pause.label(later, local(0, 10)), "jusqu'au jeu. 29 oct. à 08:00")

    def test_menu_choices(self):
        choices = pause.choices(local(0, 10), HOURS)
        self.assertEqual([c for c, _ in choices], ["1h", "4h", "demain", "manuel"])
        self.assertIn("demain 08:00", dict(choices)["demain"])


class PauseCommandTest(HomeTestCase):
    """Fonction prête à brancher pour « ccs pause »."""

    def test_status_when_not_paused(self):
        code, msg = pause.command("status", NOW)
        self.assertEqual(code, 0)
        self.assertIn("Pas de pause", msg)

    def test_pause_then_status_then_off(self):
        code, msg = pause.command("1h", NOW)
        self.assertEqual(code, 0)
        self.assertIn("en pause", msg)
        self.assertIn("jusqu'à", pause.command("status", NOW)[1])
        code, msg = pause.command("off", NOW)
        self.assertEqual(code, 0)
        self.assertIn("reprennent", msg)
        self.assertIsNone(pause.pause_state(NOW))

    def test_off_without_pause(self):
        self.assertEqual(pause.command("off", NOW)[0], 0)

    def test_bad_choice(self):
        code, msg = pause.command("2j", NOW)
        self.assertEqual(code, 2)
        self.assertIn("1h", msg)
