import json
import os
import time
from unittest import mock

from ccs_app import core
from tests.helpers import HomeTestCase, fake_http, write

USAGE = {
    "limits": [
        {"kind": "session", "percent": 31, "resets_at": "2026-10-26T12:00:00+00:00"},
        {"kind": "weekly_all", "percent": 35, "resets_at": "2026-10-29T01:00:00+00:00"},
    ]
}


class PathsTest(HomeTestCase):
    def test_paths_follow_env(self):
        self.assertEqual(core.paths().store, self.home / ".claude-accounts")
        os.environ["CCS_HOME"] = str(self.home / "ailleurs")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.home / "cfg")
        p = core.paths()
        self.assertEqual(p.store, self.home / "ailleurs")
        self.assertEqual(p.creds, self.home / "cfg" / ".credentials.json")
        self.assertEqual(p.global_json, self.home / "cfg" / ".claude.json")


class ProfilesTest(HomeTestCase):
    active = "pro"

    def test_list_profiles_marks_active_first(self):
        profiles = core.list_profiles()
        self.assertEqual([p.name for p in profiles], ["pro", "perso"])
        self.assertTrue(profiles[0].active)
        self.assertFalse(profiles[1].active)
        self.assertEqual(core.active_profile_name(), "pro")

    def test_corrupted_profile_json_is_skipped(self):
        write(self.store / "perso" / "account.json", "{")
        self.assertEqual([p.name for p in core.list_profiles()], ["pro"])


class LimitsTest(HomeTestCase):
    def test_parse_limits_new_and_legacy(self):
        self.assertEqual([l.kind for l in core.parse_limits(USAGE)], ["session", "weekly_all"])
        self.assertEqual(core.parse_limits(USAGE)[0].percent, 31.0)
        legacy = {"five_hour": {"utilization": 12.0, "resets_at": None},
                  "seven_day": {"utilization": 40.0, "resets_at": "2026-10-29T01:00:00+00:00"},
                  "seven_day_opus": None}
        limits = core.parse_limits(legacy)
        self.assertEqual([l.kind for l in limits], ["session", "weekly_all"])
        self.assertIsNone(limits[0].resets_at)
        self.assertEqual(core.parse_limits(None), [])

    def test_parse_limits_unknown_kind(self):
        limits = core.parse_limits({"limits": [{"kind": "foo_bar", "percent": 5}]})
        self.assertEqual(limits[0].label, "Foo bar")


class TokensTest(HomeTestCase):
    def test_access_token_refreshes_inactive_expired(self):
        path = self.store / "pro" / "oauth.json"
        data = json.loads(path.read_text())
        data["claudeAiOauth"]["expiresAt"] = 0
        write(path, data)
        token = {"access_token": "AT-new", "refresh_token": "RT-new", "expires_in": 3600}
        with fake_http({"/oauth/token": token}) as calls:
            self.assertEqual(core.access_token("pro"), "AT-new")
        saved = json.loads(path.read_text())["claudeAiOauth"]
        self.assertEqual(saved["refreshToken"], "RT-new")
        self.assertGreater(saved["expiresAt"], time.time() * 1000)
        self.assertEqual(calls[0][2]["refresh_token"], "RT-pro")
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")

    def test_access_token_never_refreshes_active_when_claude_running(self):
        creds = self.home / ".claude" / ".credentials.json"
        data = json.loads(creds.read_text())
        data["claudeAiOauth"]["expiresAt"] = 0
        write(creds, data)
        self.claude_running.return_value = True
        with fake_http({}) as calls:
            with self.assertRaises(core.UsageError):
                core.access_token("perso")
        self.assertEqual(calls, [])

    def test_active_token_read_from_live_credentials(self):
        with fake_http({}):
            self.assertEqual(core.access_token("perso"), "AT-perso")


class FetchUsageTest(HomeTestCase):
    def test_fetch_usage_success_writes_cache(self):
        with fake_http({"/api/oauth/usage": USAGE}) as calls:
            r = core.fetch_usage("pro")
        self.assertIsNone(r.error)
        self.assertEqual(r.usage, USAGE)
        self.assertEqual(calls[0][3]["Authorization"], "Bearer AT-pro")
        self.assertTrue((self.store / "pro" / "usage.json").exists())

    def test_fetch_usage_falls_back_to_cache(self):
        write(self.store / "pro" / "usage.json", {"fetchedAt": 123.0, "data": USAGE})
        with fake_http({"/api/oauth/usage": core.UsageError("réseau : coupé")}):
            r = core.fetch_usage("pro")
        self.assertEqual(r.usage, USAGE)
        self.assertEqual(r.fetched_at, 123.0)
        self.assertIn("coupé", r.error)


class FormatTest(HomeTestCase):
    def test_fmt_reset_relative_and_absolute(self):
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
        self.assertEqual(core.fmt_reset(now + timedelta(hours=3, minutes=5), now),
                         "réinitialisation dans 3 h 05")
        self.assertEqual(core.fmt_reset(now - timedelta(minutes=1), now), "réinitialisé")
        self.assertIn("réinitialisation", core.fmt_reset(now + timedelta(days=3), now))


class NumberTest(HomeTestCase):
    def test_fr_number(self):
        self.assertEqual(core.fr(1.06), "1,1")
        self.assertEqual(core.fr(3.0, 1), "3,0")
        self.assertEqual(core.fr(16.25, 0), "16")


class TokenSafetyTest(HomeTestCase):
    """Revue finale C1 / I2 : ne jamais écrire ou renouveler le mauvais jeton."""

    def expire(self, path):
        data = json.loads(path.read_text())
        data["claudeAiOauth"]["expiresAt"] = 0
        write(path, data)

    def test_refresh_does_not_overwrite_live_creds_changed_meanwhile(self):
        creds = self.home / ".claude" / ".credentials.json"
        self.expire(creds)

        def refresh(oauth):
            # Pendant l'appel réseau, le fichier vivant change (autre compte installé).
            other = json.loads(creds.read_text())
            other["claudeAiOauth"]["refreshToken"] = "RT-autre"
            write(creds, other)
            return dict(oauth, accessToken="AT-new", refreshToken="RT-new", expiresAt=9e15)
        with mock.patch.object(core, "refresh_tokens", side_effect=refresh):
            core.access_token("perso")
        self.assertEqual(json.loads(creds.read_text())["claudeAiOauth"]["refreshToken"], "RT-autre")

    def test_no_refresh_when_live_account_unreadable(self):
        write(self.home / ".claude.json", {"numStartups": 1})  # oauthAccount absent
        # Copie du profil actif périmée : Claude Code a déjà fait tourner le jeton vivant.
        path = self.store / "perso" / "oauth.json"
        data = json.loads(path.read_text())
        data["claudeAiOauth"].update(refreshToken="RT-ancien", expiresAt=0)
        write(path, data)
        with fake_http({}) as calls:
            with self.assertRaises(core.UsageError):
                core.access_token("perso")
        self.assertEqual(calls, [])

    def test_profile_with_live_refresh_token_counts_as_active(self):
        # ~/.claude.json désigne pro, mais le jeton vivant est encore celui de perso.
        write(self.home / ".claude.json",
              {"oauthAccount": json.loads((self.store / "pro" / "account.json").read_text())})
        self.expire(self.store / "perso" / "oauth.json")
        self.claude_running.return_value = True
        with fake_http({}) as calls:
            # Traité comme actif : jeton vivant (valide) renvoyé, rien n'est renouvelé.
            self.assertEqual(core.access_token("perso"), "AT-perso")
        self.assertEqual(calls, [])

    def test_ccs_bin_prefers_system_ccs_when_installed(self):
        with mock.patch.object(core, "__file__", "/usr/lib/ccs/ccs_app/core.py"), \
                mock.patch.dict(os.environ, {"CCS_BIN": ""}):
            self.assertEqual(core.ccs_bin(), "/usr/bin/ccs")
