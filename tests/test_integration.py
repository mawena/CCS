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


class HookBase(HomeTestCase):
    def setUp(self):
        super().setUp()
        st = copy.deepcopy(STATE)
        st["updated_at"] = time.time()
        for a in st["accounts"]:
            a["fetched_at"] = time.time()
        write(self.store / "state.json", st)
        self.sent = []


class StopFailureHookTest(HookBase):
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
                mock.patch.object(daemon, "observe_once") as collect, \
                mock.patch.object(core, "run_ccs", return_value=subprocess.CompletedProcess([], 0, "", "")):
            integration.stop_failure({"error": "rate_limit", "cwd": "/w"}, notifier=self.sent.append)
        collect.assert_called_once()


class ReviewIntegrationTest(InstallTest):
    def test_symlinked_settings_stay_a_symlink(self):
        real = self.home / "dotfiles" / "settings.json"
        write(real, {"model": "opus"})
        self.settings().parent.mkdir(parents=True, exist_ok=True)
        self.settings().symlink_to(real)
        integration.install(bin_path="/usr/bin/claude-accounts")
        self.assertTrue(self.settings().is_symlink())
        self.assertIn("statusLine", json.loads(real.read_text()))

    def test_user_wrapper_mentioning_us_is_not_ours(self):
        mine = {"statusLine": {"type": "command",
                               "command": "bash -c 'claude-accounts statusline; git branch'"}}
        write(self.settings(), mine)
        integration.install(bin_path="/usr/bin/claude-accounts")
        integration.uninstall()
        self.assertEqual(self.read()["statusLine"], mine["statusLine"])

    def test_odd_shapes_raise_integration_error(self):
        write(self.settings(), {"hooks": None})
        with self.assertRaises(integration.IntegrationError):
            integration.install(bin_path="/usr/bin/claude-accounts")
        write(self.settings(), {"statusLine": "foo"})
        self.assertEqual(integration.status()["statusline"], "autre")

    def test_backup_refreshed_on_each_write(self):
        write(self.settings(), {"v": 1})
        integration.install(bin_path="/usr/bin/claude-accounts")
        integration.uninstall()
        backup = json.loads((self.home / ".claude" / "settings.json.ccs-backup").read_text())
        self.assertIn("statusLine", backup)   # état juste avant la dernière écriture


class ReviewHookTest(HookBase):
    def test_second_hook_does_not_switch_again(self):
        ok = subprocess.CompletedProcess([], 0, "basculé", "")
        with mock.patch.object(core, "run_ccs", return_value=ok) as run:
            integration.stop_failure({"error": "rate_limit", "cwd": "/w/A"}, notifier=self.sent.append)
            integration.stop_failure({"error": "rate_limit", "cwd": "/w/B"}, notifier=self.sent.append)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(len(self.sent), 1)

    def test_no_switch_if_active_changed_during_refresh(self):
        def refresh():
            write(self.home / ".claude.json",
                  {"oauthAccount": json.loads((self.store / "pro" / "account.json").read_text())})
            return json.loads((self.store / "state.json").read_text())
        with mock.patch.object(integration, "_fresh_state", side_effect=refresh), \
                mock.patch.object(core, "run_ccs") as run:
            integration.stop_failure({"error": "rate_limit", "cwd": "/w/A"}, notifier=self.sent.append)
        run.assert_not_called()
        self.assertIn("déjà", self.sent[0].body)

    def test_failed_switch_says_so(self):
        ko = subprocess.CompletedProcess([], 1, "", "ccs: erreur")
        with mock.patch.object(core, "run_ccs", return_value=ko):
            integration.stop_failure({"error": "rate_limit", "cwd": "/w/A"}, notifier=self.sent.append)
        self.assertIn("impossible", self.sent[0].body)

    def test_non_dict_payload_and_missing_error(self):
        ok = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(core, "run_ccs", return_value=ok) as run:
            integration.stop_failure(["bizarre"], notifier=self.sent.append)
        run.assert_called_once()   # le matcher rate_limit filtre déjà : champ absent = blocage


class LimitMarkerTest(HookBase):
    """Le hook laisse un marqueur par conversation pour la reprise automatique du terminal
    intégré, sans rien changer à ce qu'il décide ni à ce qu'il notifie."""

    SID = "5b1d0c3e-aaaa-4bbb-8ccc-0123456789ab"

    def event(self):
        from ccs_app import limit_events
        return limit_events.load_all().get(self.SID)

    def payload(self, **kw):
        return {"error": "rate_limit", "cwd": "/w/GiGit", "session_id": self.SID, **kw}

    def test_switch_is_recorded(self):
        ok = subprocess.CompletedProcess([], 0, "basculé", "")
        with mock.patch.object(core, "run_ccs", return_value=ok):
            msg = integration.stop_failure(self.payload(), notifier=self.sent.append)
        self.assertEqual(msg, "basculé sur boulot")
        e = self.event()
        self.assertEqual((e.source, e.target, e.switched, e.outcome), ("perso", "boulot", True, "switched"))
        self.assertAlmostEqual(e.ts, time.time(), delta=60)

    def test_failed_switch_is_recorded_as_not_switched(self):
        ko = subprocess.CompletedProcess([], 1, "", "ccs: erreur")
        with mock.patch.object(core, "run_ccs", return_value=ko):
            self.assertEqual(integration.stop_failure(self.payload(), notifier=self.sent.append),
                             "bascule impossible")
        e = self.event()
        self.assertEqual((e.source, e.target, e.switched, e.outcome), ("perso", "boulot", False, "failed"))

    def test_no_other_account_is_recorded(self):
        st = json.loads((self.store / "state.json").read_text())
        st["accounts"] = st["accounts"][:1]   # plus d'autre compte connu
        write(self.store / "state.json", st)
        with mock.patch.object(core, "run_ccs") as run:
            integration.stop_failure(self.payload(), notifier=self.sent.append)
        run.assert_not_called()
        e = self.event()
        self.assertEqual((e.target, e.switched, e.outcome), (None, False, "exhausted"))

    def test_second_blocked_session_is_recorded_as_already_switched(self):
        other = "6c2e1d4f-bbbb-4ccc-8ddd-0123456789ab"
        ok = subprocess.CompletedProcess([], 0, "basculé", "")
        with mock.patch.object(core, "run_ccs", return_value=ok) as run:
            integration.stop_failure(self.payload(session_id=other), notifier=self.sent.append)
            self.assertEqual(integration.stop_failure(self.payload(), notifier=self.sent.append),
                             "déjà basculé")
        self.assertEqual(run.call_count, 1)
        e = self.event()
        self.assertEqual((e.source, e.target, e.switched, e.outcome), ("perso", "boulot", True, "already"))

    def test_active_account_changed_during_refresh_is_recorded_as_already_switched(self):
        def refresh():
            write(self.home / ".claude.json",
                  {"oauthAccount": json.loads((self.store / "pro" / "account.json").read_text())})
            return json.loads((self.store / "state.json").read_text())
        with mock.patch.object(integration, "_fresh_state", side_effect=refresh), \
                mock.patch.object(core, "run_ccs"):
            integration.stop_failure(self.payload(), notifier=self.sent.append)
        e = self.event()
        self.assertEqual((e.source, e.target, e.switched, e.outcome), ("perso", "pro", True, "already"))

    def test_pending_marker_written_before_the_decision(self):
        seen = []

        def refresh():
            seen.append(self.event())
            return json.loads((self.store / "state.json").read_text())
        with mock.patch.object(integration, "_fresh_state", side_effect=refresh), \
                mock.patch.object(core, "run_ccs", return_value=subprocess.CompletedProcess([], 0, "", "")):
            integration.stop_failure(self.payload(), notifier=self.sent.append)
        self.assertEqual((seen[0].outcome, seen[0].switched), ("pending", False))
        self.assertEqual(self.event().outcome, "switched")

    def test_nothing_recorded_without_usable_session_or_for_other_errors(self):
        from ccs_app import limit_events
        ok = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(core, "run_ccs", return_value=ok):
            integration.stop_failure({"error": "overloaded", "session_id": self.SID}, notifier=self.sent.append)
            integration.stop_failure(self.payload(session_id="../../etc"), notifier=self.sent.append)
            integration.stop_failure({"error": "rate_limit", "cwd": "/w"}, notifier=self.sent.append)
        self.assertEqual(limit_events.load_all(), {})

    def test_marker_failure_never_breaks_the_hook(self):
        write(self.store / "limits", "un fichier à la place du dossier")
        ok = subprocess.CompletedProcess([], 0, "basculé", "")
        with mock.patch.object(core, "run_ccs", return_value=ok):
            self.assertEqual(integration.stop_failure(self.payload(), notifier=self.sent.append),
                             "basculé sur boulot")
        self.assertIn("continue", self.sent[0].body)


class PauseHookTest(HookBase):
    """Pendant une pause, le hook ne bascule pas (ni la reprise automatique du terminal)."""

    SID = LimitMarkerTest.SID

    def payload(self):
        return {"error": "rate_limit", "cwd": "/w/GiGit", "session_id": self.SID}

    def event(self):
        from ccs_app import limit_events
        return limit_events.load_all().get(self.SID)

    def test_active_pause_blocks_the_switch_and_says_so(self):
        from ccs_app import pause
        now = datetime.now(timezone.utc)
        until = now + timedelta(hours=1)
        pause.set_pause(until, now=now)
        with mock.patch.object(core, "run_ccs") as run, \
                mock.patch.object(integration, "_fresh_state") as fresh:
            msg = integration.stop_failure(self.payload(), notifier=self.sent.append)
        run.assert_not_called()
        fresh.assert_not_called()
        self.assertEqual(msg, "en pause")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("GiGit", self.sent[0].title)
        self.assertEqual(self.sent[0].body, f"CCS est en pause jusqu'à {until.astimezone():%H:%M} : "
                                            "pas de bascule automatique.")
        e = self.event()
        self.assertEqual((e.source, e.target, e.switched, e.outcome), ("perso", None, False, "paused"))

    def test_pause_until_manual_resume(self):
        from ccs_app import pause
        pause.set_pause(None)
        with mock.patch.object(core, "run_ccs") as run:
            self.assertEqual(integration.stop_failure(self.payload(), notifier=self.sent.append), "en pause")
        run.assert_not_called()
        self.assertEqual(self.sent[0].body,
                         "CCS est en pause jusqu'à reprise manuelle : pas de bascule automatique.")

    def test_several_blocked_sessions_during_a_pause_notify_once(self):
        from ccs_app import pause
        pause.set_pause(None)
        with mock.patch.object(core, "run_ccs"):
            integration.stop_failure(self.payload(), notifier=self.sent.append)
            integration.stop_failure(dict(self.payload(), cwd="/w/B"), notifier=self.sent.append)
        self.assertEqual(len(self.sent), 1)

    def test_expired_pause_switches_as_usual(self):
        from ccs_app import pause
        now = datetime.now(timezone.utc)
        pause.set_pause(now - timedelta(minutes=1), now=now - timedelta(hours=1))
        ok = subprocess.CompletedProcess([], 0, "basculé", "")
        with mock.patch.object(core, "run_ccs", return_value=ok) as run:
            self.assertEqual(integration.stop_failure(self.payload(), notifier=self.sent.append),
                             "basculé sur boulot")
        run.assert_called_once_with(["use", "boulot"])
        self.assertEqual(self.event().outcome, "switched")

    def test_unreadable_pause_never_breaks_the_hook(self):
        from ccs_app import pause
        write(self.store / "pause.json", "{pas du json")
        ok = subprocess.CompletedProcess([], 0, "basculé", "")
        with mock.patch.object(core, "run_ccs", return_value=ok):
            self.assertEqual(integration.stop_failure(self.payload(), notifier=self.sent.append),
                             "basculé sur boulot")
        with mock.patch.object(pause, "pause_state", side_effect=OSError("illisible")), \
                mock.patch.object(core, "run_ccs", return_value=ok), \
                mock.patch.object(integration.Store, "events", return_value=[]):
            self.assertEqual(integration.stop_failure(self.payload(), notifier=self.sent.append),
                             "basculé sur boulot")


class StatuslinePauseTest(HomeTestCase):
    def test_pause_symbol(self):
        st = dict(STATE, pause={"since": "…", "until": None, "label": "jusqu'à reprise manuelle"})
        self.assertTrue(integration.statusline_text(st, NOW).startswith("⏸ "))
        self.assertIn("perso 85 %", integration.statusline_text(st, NOW))
        self.assertNotIn("⏸", integration.statusline_text(dict(STATE, pause=None), NOW))
        self.assertNotIn("⏸", integration.statusline_text(STATE, NOW))
        self.assertEqual(integration.statusline_text({"pause": {"until": None}}, NOW),
                         "⏸ CCS : pas encore de données")
