import copy
import json
import subprocess
import time
from datetime import datetime, timedelta, timezone
from unittest import mock

from ccs_app import autoswitch, core, integration
from ccs_app.core import Limit
from ccs_app.forecast import AccountState
from ccs_app.settings import DEFAULTS
from ccs_app.store import Store
from tests.helpers import HomeTestCase, write

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


class InstallTest(HomeTestCase):
    def settings(self):
        return self.home / ".claude" / "settings.json"

    def read(self):
        return json.loads(self.settings().read_text())

    def test_install_into_missing_file_and_idempotent(self):
        integration.install(bin_path="/usr/bin/claude-accounts")
        integration.install(bin_path="/usr/bin/claude-accounts")
        s = self.read()
        self.assertEqual(s["statusLine"]["command"], "/usr/bin/claude-accounts statusline")
        groups = s["hooks"]["StopFailure"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["matcher"], "rate_limit")
        self.assertEqual(groups[0]["hooks"][0]["command"], "/usr/bin/claude-accounts hook stop-failure")

    def test_existing_settings_kept_and_backed_up(self):
        mine = {"model": "opus", "statusLine": {"type": "command", "command": "mon-script"},
                "hooks": {"StopFailure": [{"matcher": "overloaded", "hooks": [{"type": "command", "command": "x"}]}],
                          "Stop": [{"hooks": [{"type": "command", "command": "y"}]}]}}
        write(self.settings(), mine)
        msgs = integration.install(bin_path="/usr/bin/claude-accounts")
        s = self.read()
        self.assertEqual(s["model"], "opus")
        self.assertEqual(s["statusLine"]["command"], "mon-script")
        self.assertEqual(len(s["hooks"]["StopFailure"]), 2)
        self.assertIn("Stop", s["hooks"])
        self.assertTrue(any("conservée" in m for m in msgs))
        backup = json.loads((self.home / ".claude" / "settings.json.ccs-backup").read_text())
        self.assertEqual(backup, mine)

    def test_invalid_json_is_never_overwritten(self):
        write(self.settings(), "{pas du json")
        with self.assertRaises(integration.IntegrationError):
            integration.install(bin_path="/usr/bin/claude-accounts")
        self.assertEqual(self.settings().read_text(), "{pas du json")

    def test_uninstall_removes_only_ours(self):
        write(self.settings(), {"hooks": {"StopFailure": [
            {"matcher": "overloaded", "hooks": [{"type": "command", "command": "x"}]}]}})
        integration.install(bin_path="/usr/bin/claude-accounts")
        integration.uninstall()
        s = self.read()
        self.assertNotIn("statusLine", s)
        self.assertEqual(s["hooks"]["StopFailure"], [
            {"matcher": "overloaded", "hooks": [{"type": "command", "command": "x"}]}])

    def test_status(self):
        self.assertEqual(integration.status(), {"statusline": None, "hook": False})
        integration.install(bin_path="/usr/bin/claude-accounts")
        self.assertEqual(integration.status(), {"statusline": "ccs", "hook": True})


def iso(minutes):
    return (NOW + timedelta(minutes=minutes)).isoformat()


STATE = {
    "updated_at": NOW.timestamp(), "active": "perso", "capacity": 1.2,
    "best": {"name": "boulot", "reason": "r"},
    "accounts": [
        {"name": "perso", "active": True, "error": None, "fetched_at": NOW.timestamp(),
         "limits": [{"kind": "session", "label": "S", "percent": 85, "resets_at": iso(80)},
                    {"kind": "weekly_all", "label": "W", "percent": 49, "resets_at": iso(3000)}],
         "forecast": {"verdict": "limit", "eta": iso(25)}},
        {"name": "boulot", "active": False, "error": None, "fetched_at": NOW.timestamp(),
         "limits": [{"kind": "session", "label": "S", "percent": 10, "resets_at": iso(200)}]},
    ],
}


class StatuslineTest(HomeTestCase):
    def test_statusline_text(self):
        hm = lambda m: (NOW + timedelta(minutes=m)).astimezone().strftime("%H:%M")  # noqa: E731
        text = integration.statusline_text(STATE, NOW)
        self.assertIn("perso 85 %", text)
        self.assertIn(f"↻{hm(80)}", text)
        self.assertIn(f"⏱{hm(25)}", text)
        self.assertIn("sem. 49 %", text)
        self.assertIn("→ boulot", text)

    def test_statusline_without_state(self):
        self.assertEqual(integration.statusline_text({}, NOW), "CCS : pas encore de données")


class RescueTest(HomeTestCase):
    def acc(self, name, s, age=30, error=None, active=False):
        return AccountState(name, active, [Limit("session", "S", s, NOW + timedelta(minutes=60))],
                            NOW.timestamp() - age, error)

    def test_rescue_switches_to_other_fresh_account(self):
        d = autoswitch.rescue([self.acc("perso", 100, active=True), self.acc("pro", 30)],
                              "perso", copy.deepcopy(DEFAULTS), NOW)
        self.assertEqual((d.action, d.target), ("switch", "pro"))

    def test_rescue_ignores_stale_or_revoked(self):
        accounts = [self.acc("perso", 100, active=True), self.acc("old", 10, age=3600),
                    self.acc("rev", 10, error="connexion expirée ou révoquée : x")]
        self.assertEqual(autoswitch.rescue(accounts, "perso", copy.deepcopy(DEFAULTS), NOW).action,
                         "exhausted")


class StopFailureHookTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        st = copy.deepcopy(STATE)
        st["updated_at"] = time.time()
        for a in st["accounts"]:
            a["fetched_at"] = time.time()
        write(self.store / "state.json", st)
        self.sent = []

    def test_ignores_other_errors(self):
        with mock.patch.object(core, "run_ccs") as run:
            msg = integration.stop_failure({"error": "overloaded"}, notifier=self.sent.append)
        run.assert_not_called()
        self.assertIn("ignor", msg)

    def test_rate_limit_switches_and_notifies(self):
        ok = subprocess.CompletedProcess([], 0, "basculé", "")
        with mock.patch.object(core, "run_ccs", return_value=ok) as run:
            integration.stop_failure({"error": "rate_limit", "cwd": "/w/GiGit"},
                                     notifier=self.sent.append)
        run.assert_called_once_with(["use", "boulot"])
        self.assertEqual(Store().last_event("switch").detail["mode"], "blocage")
        self.assertIn("GiGit", self.sent[0].title)
        self.assertIn("continue", self.sent[0].body)

    def test_stale_state_triggers_collect(self):
        st = json.loads((self.store / "state.json").read_text())
        st["updated_at"] = time.time() - 3600
        write(self.store / "state.json", st)
        from ccs_app import daemon
        with mock.patch.object(daemon, "request_refresh", return_value=False), \
                mock.patch.object(daemon, "collect_once") as collect, \
                mock.patch.object(core, "run_ccs", return_value=subprocess.CompletedProcess([], 0, "", "")):
            integration.stop_failure({"error": "rate_limit", "cwd": "/w"}, notifier=self.sent.append)
        collect.assert_called_once()
