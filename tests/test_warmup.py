import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from ccs_app import warmup
from ccs_app.core import Limit
from ccs_app.forecast import AccountState
from ccs_app.settings import load_settings
from ccs_app.store import Store
from tests.helpers import HomeTestCase

# Lundi 26 octobre 2026, heure locale.
MONDAY_0703 = datetime(2026, 10, 26, 7, 3).astimezone()


def idle(name="perso"):
    return AccountState(name, False, [Limit("session", "S", 0, None)], MONDAY_0703.timestamp(), None)


def open_window(name="perso"):
    lim = Limit("session", "S", 20, MONDAY_0703 + timedelta(hours=2))
    return AccountState(name, False, [lim], MONDAY_0703.timestamp(), None)


class DueTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.db = Store()
        self.settings = load_settings()
        self.settings["warmup"] = {"perso": [{"days": [0, 1, 2, 3, 4], "time": "07:00"}]}

    def test_due_at_slot_when_window_idle(self):
        self.assertEqual(warmup.due(self.settings, [idle()], MONDAY_0703, self.db),
                         [("perso", "07:00")])

    def test_not_due_when_window_open(self):
        self.assertEqual(warmup.due(self.settings, [open_window()], MONDAY_0703, self.db), [])

    def test_not_due_twice_same_day(self):
        self.db.add_event(MONDAY_0703.timestamp(), "warmup", "perso",
                          {"date": "2026-10-26", "time": "07:00", "ok": True})
        self.assertEqual(warmup.due(self.settings, [idle()], MONDAY_0703, self.db), [])

    def test_not_due_on_other_days(self):
        self.settings["warmup"]["perso"][0]["days"] = [5, 6]
        self.assertEqual(warmup.due(self.settings, [idle()], MONDAY_0703, self.db), [])

    def test_not_due_after_10_minutes(self):
        later = MONDAY_0703 + timedelta(minutes=12)
        self.assertEqual(warmup.due(self.settings, [idle()], later, self.db), [])

    def test_not_due_without_data(self):
        broken = AccountState("perso", False, [], None, "réseau")
        self.assertEqual(warmup.due(self.settings, [broken], MONDAY_0703, self.db), [])


class RunTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.db = Store()
        self.live = self.home / ".claude" / ".credentials.json"
        self.live_before = self.live.read_text()

    def fake_claude(self, rotate=False):
        seen = {}

        def run(cmd, env, **kwargs):
            cfg = Path(env["CLAUDE_CONFIG_DIR"])
            seen["cmd"] = cmd
            seen["cfg"] = cfg
            seen["creds"] = json.loads((cfg / ".credentials.json").read_text())
            seen["mode"] = oct(cfg.stat().st_mode & 0o777)
            if rotate:
                c = seen["creds"]
                c["claudeAiOauth"]["refreshToken"] = "RT-rotated"
                (cfg / ".credentials.json").write_text(json.dumps(c))
            return subprocess.CompletedProcess(cmd, 0, "ok", "")
        return seen, run

    def test_run_uses_isolated_config_dir(self):
        seen, fake = self.fake_claude()
        with mock.patch.object(warmup.subprocess, "run", side_effect=fake):
            self.assertTrue(warmup.run("pro", "07:00", self.db, MONDAY_0703))
        self.assertNotEqual(seen["cfg"], self.home / ".claude")
        self.assertEqual(seen["mode"], "0o700")
        self.assertEqual(seen["creds"]["claudeAiOauth"]["accessToken"], "AT-pro")
        self.assertIn("haiku", seen["cmd"])
        self.assertFalse(seen["cfg"].exists())
        self.assertEqual(self.live.read_text(), self.live_before)
        ev = self.db.last_event("warmup", "pro")
        self.assertEqual(ev.detail["time"], "07:00")
        self.assertTrue(ev.detail["ok"])

    def test_run_saves_rotated_token_back_to_profile(self):
        _, fake = self.fake_claude(rotate=True)
        with mock.patch.object(warmup.subprocess, "run", side_effect=fake):
            warmup.run("pro", "07:00", self.db, MONDAY_0703)
        saved = json.loads((self.store / "pro" / "oauth.json").read_text())
        self.assertEqual(saved["claudeAiOauth"]["refreshToken"], "RT-rotated")

    def test_run_failure_is_logged(self):
        def boom(cmd, env, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 120)
        with mock.patch.object(warmup.subprocess, "run", side_effect=boom):
            self.assertFalse(warmup.run("pro", "07:00", self.db, MONDAY_0703))
        self.assertFalse(self.db.last_event("warmup", "pro").detail["ok"])
