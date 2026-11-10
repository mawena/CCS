"""Réglages édités à la main : chaque clé invalide retombe sur sa valeur par défaut."""

import json

from ccs_app import settings
from tests.helpers import HomeTestCase, write


class ValidationTest(HomeTestCase):
    def load(self, data):
        write(self.store / "settings.json", data)
        return settings.load_settings()

    def test_valid_values_are_kept(self):
        s = self.load({"auto_switch": {"threshold": 90.5, "enabled": False},
                       "alerts": {"session_thresholds": [50, 70], "weekly_report_day": 0},
                       "poll": {"normal_s": 120}})
        self.assertEqual(s["auto_switch"]["threshold"], 90.5)
        self.assertFalse(s["auto_switch"]["enabled"])
        self.assertEqual(s["alerts"]["session_thresholds"], [50, 70])
        self.assertEqual(s["alerts"]["weekly_report_day"], 0)
        self.assertEqual(s["poll"], {"normal_s": 120, "fast_s": 60})

    def test_monthly_report_settings(self):
        d = settings.DEFAULTS["alerts"]
        self.assertEqual((d["monthly_report"], d["monthly_report_hour"]), (True, 9))
        s = self.load({"alerts": {"monthly_report": False, "monthly_report_hour": 18}})
        self.assertEqual((s["alerts"]["monthly_report"], s["alerts"]["monthly_report_hour"]), (False, 18))
        for bad in (24, -1, "9", 9.5, True, None):
            with self.subTest(hour=bad):
                s = self.load({"alerts": {"monthly_report_hour": bad, "monthly_report": "oui"}})
                self.assertEqual(s["alerts"]["monthly_report_hour"], 9)
                self.assertIs(s["alerts"]["monthly_report"], True)

    def test_wrong_types_fall_back_to_default(self):
        s = self.load({"auto_switch": {"threshold": "haut", "enabled": "true",
                                       "target_max_session": [1], "target_max_weekly": True},
                       "alerts": {"eta_minutes": None, "session_thresholds": 80,
                                  "resets": "oui", "weekly_report_hour": "9"},
                       "poll": {"normal_s": {}, "fast_s": "60"}})
        self.assertEqual(s["auto_switch"], settings.DEFAULTS["auto_switch"])
        for key in ("eta_minutes", "session_thresholds", "resets", "weekly_report_hour"):
            self.assertEqual(s["alerts"][key], settings.DEFAULTS["alerts"][key], key)
        self.assertEqual(s["poll"], settings.DEFAULTS["poll"])

    def test_out_of_bounds_numbers_fall_back(self):
        s = self.load({"auto_switch": {"threshold": 250, "target_max_session": -5},
                       "alerts": {"session_thresholds": [80, 500], "weekly_report_hour": 24,
                                  "waiting_reminder_min": 0, "model_advice_pct": 101},
                       "poll": {"normal_s": 0, "fast_s": -1},
                       "advisor": {"weeks": 0, "margin_pct": -1, "max_accounts": 0},
                       "orchestrator": {"expiring_within_min": -3, "max_weekly_start": 300}})
        d = settings.DEFAULTS
        self.assertEqual(s["auto_switch"]["threshold"], d["auto_switch"]["threshold"])
        self.assertEqual(s["auto_switch"]["target_max_session"], d["auto_switch"]["target_max_session"])
        for key in ("session_thresholds", "weekly_report_hour", "waiting_reminder_min",
                    "model_advice_pct"):
            self.assertEqual(s["alerts"][key], d["alerts"][key], key)
        self.assertEqual(s["poll"], d["poll"])
        self.assertEqual(s["advisor"], d["advisor"])
        self.assertEqual(s["orchestrator"]["expiring_within_min"], d["orchestrator"]["expiring_within_min"])
        self.assertEqual(s["orchestrator"]["max_weekly_start"], d["orchestrator"]["max_weekly_start"])

    def test_section_that_is_not_an_object_falls_back(self):
        s = self.load({"auto_switch": [1, 2], "alerts": "oui", "poll": 5, "orchestrator": None})
        for section in ("auto_switch", "alerts", "poll", "orchestrator"):
            self.assertEqual(s[section], settings.DEFAULTS[section], section)

    def test_unknown_keys_are_kept(self):
        s = self.load({"auto_switch": {"inconnue": 3}, "ma_section": {"a": 1}})
        self.assertEqual(s["auto_switch"]["inconnue"], 3)
        self.assertEqual(s["ma_section"], {"a": 1})

    def test_active_hours_invalid_parts_fall_back(self):
        d = settings.DEFAULTS["orchestrator"]["active_hours"]
        s = self.load({"orchestrator": {"active_hours": {"start": "25:00", "end": "2h", "days": [0, 9]}}})
        self.assertEqual(s["orchestrator"]["active_hours"], d)
        s = self.load({"orchestrator": {"active_hours": {"start": "07:30", "days": [1, 2, "lundi"]}}})
        self.assertEqual(s["orchestrator"]["active_hours"],
                         {"start": "07:30", "end": d["end"], "days": d["days"]})
        s = self.load({"orchestrator": {"active_hours": "tout le temps"}})
        self.assertEqual(s["orchestrator"]["active_hours"], d)
        s = self.load({"orchestrator": {"active_hours": {"days": [2, 3]}}})
        self.assertEqual(s["orchestrator"]["active_hours"]["days"], [2, 3])

    def test_null_default_keys(self):
        self.assertIsNone(self.load({})["alerts"]["weekly_report_day"])
        self.assertEqual(self.load({"alerts": {"weekly_report_day": 6}})["alerts"]["weekly_report_day"], 6)
        for bad in ("lundi", 7, -1, 1.5, True):
            s = self.load({"alerts": {"weekly_report_day": bad}})
            self.assertIsNone(s["alerts"]["weekly_report_day"], bad)

    def test_free_dictionaries_are_filtered_entry_by_entry(self):
        s = self.load({"advisor": {"plan_prices": {"pro": 18, "max5": "cher", "max20": -4},
                                   "profile_plans": {"perso": "max5", "pro": 3}}})
        self.assertEqual(s["advisor"]["plan_prices"], {"pro": 18})
        self.assertEqual(s["advisor"]["profile_plans"], {"perso": "max5"})
        s = self.load({"advisor": {"plan_prices": [20], "profile_plans": "max5"}})
        self.assertEqual(s["advisor"]["plan_prices"], {})
        self.assertEqual(s["advisor"]["profile_plans"], {})

    def test_warmup_slots(self):
        good = {"time": "08:00", "days": [0, 1]}
        s = self.load({"warmup": {"perso": [good, {"time": "99:00"}, "08:00", {"days": [1]}],
                                  "pro": "08:00", "autre": [{"time": "7:05"}]}})
        self.assertEqual(s["warmup"], {"perso": [good], "autre": [{"time": "7:05"}]})
        self.assertEqual(self.load({"warmup": [1]})["warmup"], {})

    def test_unreadable_json_gives_defaults(self):
        for text in ("{oups", "[1, 2]", "42", ""):
            write(self.store / "settings.json", text)
            self.assertEqual(settings.load_settings(), settings.DEFAULTS)

    def test_loading_never_rewrites_the_file(self):
        p = self.store / "settings.json"
        write(p, {"auto_switch": {"threshold": "haut"}})
        before = p.read_text()
        settings.load_settings()
        self.assertEqual(p.read_text(), before)

    def test_save_keeps_what_it_is_given(self):
        s = settings.load_settings()
        s["auto_switch"]["threshold"] = 91
        s["ma_section"] = {"x": 1}
        settings.save_settings(s)
        saved = json.loads((self.store / "settings.json").read_text())
        self.assertEqual(saved["auto_switch"]["threshold"], 91)
        self.assertEqual(saved["ma_section"], {"x": 1})
        self.assertEqual(saved, s)

    def test_problems_lists_ignored_keys(self):
        write(self.store / "settings.json",
              {"auto_switch": {"threshold": "haut", "enabled": True}, "poll": 3,
               "alerts": {"weekly_report_day": 9}})
        self.assertEqual(settings.problems(),
                         ["alerts.weekly_report_day", "auto_switch.threshold", "poll"])
        write(self.store / "settings.json", {"auto_switch": {"threshold": 90}})
        self.assertEqual(settings.problems(), [])
        write(self.store / "settings.json", "{oups")
        self.assertEqual(settings.problems(), ["settings.json illisible"])

    def test_problems_logged_once_per_set(self):
        write(self.store / "settings.json", {"poll": {"normal_s": "x"}})
        with self.assertLogs("ccs.settings", "WARNING") as cm:
            settings.load_settings()
            settings.load_settings()
        self.assertEqual(len(cm.output), 1)
        self.assertIn("poll.normal_s", cm.output[0])
