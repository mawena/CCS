import json

from ccs_app import settings
from tests.helpers import HomeTestCase, write


class SettingsTest(HomeTestCase):
    def test_defaults_without_file(self):
        s = settings.load_settings()
        self.assertTrue(s["auto_switch"]["enabled"])
        self.assertEqual(s["auto_switch"]["threshold"], 98)
        self.assertEqual(s["alerts"]["session_thresholds"], [80, 95])
        self.assertEqual(s["poll"], {"normal_s": 300, "fast_s": 60})

    def test_new_alert_defaults(self):
        a = settings.load_settings()["alerts"]
        self.assertTrue(a["weekly_forecast"])
        self.assertEqual(a["weekly_forecast_days"], 2)
        self.assertTrue(a["waiting_reminder"])
        self.assertEqual(a["waiting_reminder_min"], 10)
        self.assertEqual(settings.load_settings()["updates"], {"enabled": True})

    def test_advisor_defaults(self):
        adv = settings.load_settings()["advisor"]
        self.assertEqual(adv["weeks"], 4)
        self.assertEqual(adv["margin_pct"], 20)
        self.assertEqual(adv["plan_prices"], {})
        self.assertEqual(adv["profile_plans"], {})
        self.assertEqual(adv["max_accounts"], 3)

    def test_plan_prices_override_is_merged(self):
        write(self.store / "settings.json", {"advisor": {"plan_prices": {"pro": 18}}})
        adv = settings.load_settings()["advisor"]
        self.assertEqual(adv["plan_prices"], {"pro": 18})
        self.assertEqual(adv["weeks"], 4)

    def test_old_settings_file_gets_new_defaults(self):
        # Fichier d'une version précédente : les nouvelles clés prennent leur valeur par défaut.
        write(self.store / "settings.json", {"alerts": {"enabled": True, "resets": False}})
        a = settings.load_settings()["alerts"]
        self.assertFalse(a["resets"])
        self.assertTrue(a["weekly_forecast"])

    def test_settings_deep_merge(self):
        write(self.store / "settings.json", {"auto_switch": {"threshold": 95}})
        s = settings.load_settings()
        self.assertEqual(s["auto_switch"]["threshold"], 95)
        self.assertTrue(s["auto_switch"]["enabled"])
        self.assertEqual(s["auto_switch"]["target_max_session"], 80)

    def test_settings_corrupted_file_gives_defaults(self):
        write(self.store / "settings.json", "{oups")
        self.assertEqual(settings.load_settings(), settings.DEFAULTS)

    def test_save_roundtrip_does_not_mutate_defaults(self):
        s = settings.load_settings()
        s["auto_switch"]["enabled"] = False
        settings.save_settings(s)
        self.assertTrue(settings.DEFAULTS["auto_switch"]["enabled"])
        self.assertFalse(json.loads((self.store / "settings.json").read_text())["auto_switch"]["enabled"])
        self.assertFalse(settings.load_settings()["auto_switch"]["enabled"])
