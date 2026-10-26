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
