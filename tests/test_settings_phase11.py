"""Réglages de la phase 11 : valeurs par défaut et validation."""

from ccs_app import archive, budget, context_alert, phone, session_memory, settings, tasks
from tests.helpers import HomeTestCase, write


class Phase11SettingsTest(HomeTestCase):
    def load(self, data):
        write(self.store / "settings.json", data)
        return settings.load_settings()

    def test_defaults_match_the_modules(self):
        s = settings.load_settings()
        self.assertEqual(s["tasks"], tasks.DEFAULTS)
        self.assertEqual(s["phone"], phone.DEFAULTS)
        self.assertEqual(s["archive"], archive.DEFAULTS)
        self.assertEqual(s["sessions"], session_memory.DEFAULTS)
        self.assertEqual(s["context_alert"], context_alert.DEFAULTS)
        self.assertEqual(s["budget"], budget.DEFAULTS)
        self.assertEqual(settings.problems(), [])

    def test_valid_values_are_kept(self):
        s = self.load({
            "tasks": {"enabled": False, "night": {"start": "22:30", "end": "06:00"}, "max_attempts": 5},
            "phone": {"enabled": True, "server": "http://ntfy.local:8080", "topic": "ccs-abcdefgh1234",
                      "events": {"task": False}},
            "archive": {"enabled": False, "idle_days": 3, "max_age_days": 90},
            "sessions": {"idle_hours": 0.5},
            "context_alert": {"enabled": False, "threshold_tokens": 100000},
            "budget": {"enabled": False, "alert_pcts": [50, 90, 100]}})
        self.assertFalse(s["tasks"]["enabled"])
        self.assertEqual(s["tasks"]["night"], {"start": "22:30", "end": "06:00"})
        self.assertEqual(s["tasks"]["max_attempts"], 5)
        self.assertEqual(s["phone"]["server"], "http://ntfy.local:8080")
        self.assertEqual(s["phone"]["topic"], "ccs-abcdefgh1234")
        self.assertEqual(s["phone"]["events"], {"waiting": True, "task": False, "switch": True,
                                                "exhausted": True})
        self.assertEqual(s["archive"], {"enabled": False, "idle_days": 3, "max_age_days": 90})
        self.assertEqual(s["sessions"]["idle_hours"], 0.5)
        self.assertEqual(s["context_alert"]["threshold_tokens"], 100000)
        self.assertEqual(s["budget"]["alert_pcts"], [50, 90, 100])
        self.assertEqual(settings.problems(), [])

    def test_invalid_values_fall_back_to_defaults(self):
        s = self.load({
            "tasks": {"enabled": "oui", "night": {"start": "25:00", "end": "7h"}, "max_attempts": 0},
            "phone": {"enabled": 1, "server": "ftp://x", "topic": "court", "events": {"waiting": "non"}},
            "archive": {"enabled": None, "idle_days": -1, "max_age_days": 1.5},
            "sessions": {"idle_hours": 0},
            "context_alert": {"enabled": [], "threshold_tokens": 10},
            "budget": {"enabled": "x", "alert_pcts": [80, "cent"]}})
        d = settings.DEFAULTS
        self.assertEqual(s["tasks"], d["tasks"])
        self.assertEqual(s["phone"], d["phone"])
        self.assertEqual(s["archive"], d["archive"])
        self.assertEqual(s["sessions"], d["sessions"])
        self.assertEqual(s["context_alert"], d["context_alert"])
        self.assertEqual(s["budget"], d["budget"])
        for key in ("tasks.max_attempts", "tasks.night.start", "phone.server", "phone.topic",
                    "phone.events.waiting", "archive.max_age_days", "context_alert.threshold_tokens",
                    "budget.alert_pcts", "sessions.idle_hours"):
            self.assertIn(key, settings.problems())

    def test_a_non_dict_section_falls_back(self):
        s = self.load({"phone": "oui", "budget": 3, "tasks": []})
        self.assertEqual(s["phone"], settings.DEFAULTS["phone"])
        self.assertEqual(s["budget"], settings.DEFAULTS["budget"])
        self.assertEqual(s["tasks"], settings.DEFAULTS["tasks"])
