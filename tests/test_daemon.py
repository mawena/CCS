import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from unittest import mock

from ccs_app import core, daemon
from ccs_app.settings import load_settings
from ccs_app.store import Store
from tests.helpers import HomeTestCase, fake_http, write

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)


def usage(session, weekly=10, reset_min=120):
    return {"limits": [
        {"kind": "session", "percent": session,
         "resets_at": (NOW + timedelta(minutes=reset_min)).isoformat()},
        {"kind": "weekly_all", "percent": weekly,
         "resets_at": (NOW + timedelta(days=3)).isoformat()},
    ]}


def per_account(**by_name):
    """Réponse d'usage selon le jeton (AT-<profil>), ou exception."""
    def handler(method, url, body, headers):
        name = headers["Authorization"].split("AT-")[1]
        value = by_name[name]
        if isinstance(value, Exception):
            raise value
        return value
    return {"/api/oauth/usage": handler}


class DaemonTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.store_db = Store()
        self.sent = []
        self.d = daemon.Daemon(self.store_db, notifier=self.sent.append)
        self.settings = load_settings()
        # Les relevés sont horodatés par fetch_usage avec l'heure réelle.
        core_clock = mock.patch.object(core.time, "time", return_value=NOW.timestamp())
        core_clock.start()
        self.addCleanup(core_clock.stop)

    def state(self):
        return json.loads((self.store / "state.json").read_text())

    def test_tick_writes_state_and_samples(self):
        with fake_http(per_account(perso=usage(30), pro=usage(5))):
            delay = self.d.tick(self.settings, NOW)
        self.assertEqual(delay, 300)
        st = self.state()
        self.assertEqual(st["active"], "perso")
        self.assertEqual([a["name"] for a in st["accounts"]], ["perso", "pro"])
        self.assertEqual(st["accounts"][0]["limits"][0]["percent"], 30)
        self.assertIn("forecast", st["accounts"][0])
        self.assertEqual(st["best"]["name"], "perso")
        self.assertAlmostEqual(st["capacity"], 0.7 + 0.9)
        self.assertEqual(len(self.store_db.samples("pro", "session", 0)), 1)
        self.assertNotIn("AT-", (self.store / "state.json").read_text())

    def test_tick_fast_cadence_when_active_above_85(self):
        with fake_http(per_account(perso=usage(88), pro=usage(5))):
            self.assertEqual(self.d.tick(self.settings, NOW), 60)
        # Tick rapide suivant : seul le compte actif est relevé.
        with fake_http(per_account(perso=usage(89), pro=usage(5))) as calls:
            self.d.tick(self.settings, NOW + timedelta(seconds=60))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.state()["accounts"]), 2)

    def test_tick_executes_auto_switch_and_logs_event(self):
        ok = subprocess.CompletedProcess([], 0, "basculé", "")
        with fake_http(per_account(perso=usage(99), pro=usage(5))), \
                mock.patch.object(core, "run_ccs", return_value=ok) as run:
            self.d.tick(self.settings, NOW)
        run.assert_called_once_with(["use", "pro"])
        ev = self.store_db.last_event("switch")
        self.assertEqual((ev.profile, ev.detail["mode"], ev.detail["from"]), ("pro", "auto", "perso"))
        self.assertTrue(any("Bascule automatique" in a.title for a in self.sent))

    def test_tick_with_network_error_keeps_last_state(self):
        with fake_http(per_account(perso=usage(30), pro=usage(5))):
            self.d.tick(self.settings, NOW)
        later = NOW + timedelta(minutes=5)
        err = core.UsageError("réseau : coupé")
        with fake_http(per_account(perso=err, pro=err)):
            self.d.tick(self.settings, later)
        acc = self.state()["accounts"][0]
        self.assertIn("coupé", acc["error"])
        self.assertEqual(acc["limits"][0]["percent"], 30)

    def test_first_tick_records_initial_not_manual(self):
        with fake_http(per_account(perso=usage(30), pro=usage(5))):
            self.d.tick(self.settings, NOW)
        self.assertEqual(self.store_db.last_event("switch").detail["mode"], "initial")

    def test_manual_switch_detected(self):
        self.store_db.add_event(NOW.timestamp() - 3600, "switch", "perso", {"mode": "initial"})
        write(self.home / ".claude.json",
              {"oauthAccount": json.loads((self.store / "pro" / "account.json").read_text())})
        with fake_http(per_account(perso=usage(30), pro=usage(5))):
            self.d.tick(self.settings, NOW)
        ev = self.store_db.last_event("switch")
        self.assertEqual((ev.profile, ev.detail["mode"]), ("pro", "manual"))

    def test_session_alert_sent_once(self):
        with fake_http(per_account(perso=usage(82), pro=usage(5))):
            self.d.tick(self.settings, NOW)
            self.d.tick(self.settings, NOW + timedelta(minutes=5))
        titles = [a.title for a in self.sent]
        self.assertEqual(titles, ["perso : session à 82 %"])

    def test_no_profiles_is_idle(self):
        shutil.rmtree(self.store / "perso")
        shutil.rmtree(self.store / "pro")
        with fake_http({}) as calls:
            self.assertEqual(self.d.tick(self.settings, NOW), 300)
        self.assertEqual(calls, [])
        self.assertEqual(self.state()["accounts"], [])


class PidTest(HomeTestCase):
    """Revue finale I1 : un pid recyclé ne doit jamais être pris pour le daemon."""

    def test_running_pid_ignores_unrelated_process(self):
        import sys
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "daemon"])
        self.addCleanup(p.kill)
        write(self.store / "daemon.pid", str(p.pid))
        self.assertIsNone(daemon.running_pid())
        self.assertFalse(daemon.request_refresh())
        self.assertIsNone(p.poll())  # pas tué par un SIGUSR1

    def test_state_fresh(self):
        now = NOW.timestamp()
        self.assertTrue(daemon.state_fresh({"updated_at": now - 60}, now))
        self.assertFalse(daemon.state_fresh({"updated_at": now - 3600}, now))
        self.assertFalse(daemon.state_fresh({}, now))


def idle_usage(weekly=10):
    return {"limits": [
        {"kind": "session", "percent": 0, "resets_at": None},
        {"kind": "weekly_all", "percent": weekly,
         "resets_at": (NOW + timedelta(days=3)).isoformat()},
    ]}


class OrchestratorDaemonTest(DaemonTest):
    def setUp(self):
        super().setUp()
        self.started = []
        self.d.starter = lambda name, now: self.started.append(name)
        o = self.settings["orchestrator"]
        o["enabled"] = True
        # NOW = 09:00 UTC ; plage large pour être active quel que soit le fuseau du poste.
        o["active_hours"] = {"start": "00:00", "end": "23:59", "days": list(range(7))}

    def test_starts_idle_account_after_its_slot(self):
        self.settings["orchestrator"]["stagger"] = False
        with fake_http(per_account(perso=usage(30), pro=idle_usage())):
            self.d.tick(self.settings, NOW)
        self.assertEqual(self.started, ["pro"])
        ev = self.store_db.last_event("warmup", "pro")
        self.assertEqual(ev.detail["mode"], "orchestrateur")

    def test_disabled_never_starts(self):
        self.settings["orchestrator"]["enabled"] = False
        with fake_http(per_account(perso=usage(30), pro=idle_usage())):
            self.d.tick(self.settings, NOW)
        self.assertEqual(self.started, [])

    def test_expiring_switch_executed(self):
        ok = subprocess.CompletedProcess([], 0, "basculé", "")
        with fake_http(per_account(perso=usage(40, reset_min=200), pro=usage(30, reset_min=40))), \
                mock.patch.object(core, "run_ccs", return_value=ok) as run:
            self.d.tick(self.settings, NOW)
        run.assert_called_once_with(["use", "pro"])
        self.assertEqual(self.store_db.last_event("switch").detail["mode"], "anticipee")

    def test_precise_wake_before_reset(self):
        with fake_http(per_account(perso=usage(30, reset_min=3), pro=usage(5, reset_min=250))):
            delay = self.d.tick(self.settings, NOW)
        self.assertAlmostEqual(delay, 210, delta=1)

    def test_state_contains_plan(self):
        with fake_http(per_account(perso=usage(30), pro=idle_usage())):
            self.d.tick(self.settings, NOW)
        o = self.state()["orchestrator"]
        self.assertTrue(o["enabled"])
        self.assertTrue(o["active_now"])
        self.assertTrue(any(w["name"] == "perso" and w["kind"] == "current" for w in o["plan"]))


class ReviewDaemonTest(OrchestratorDaemonTest):
    def test_no_expiring_switch_when_auto_switch_disabled(self):
        self.settings["auto_switch"]["enabled"] = False
        with fake_http(per_account(perso=usage(40, reset_min=200), pro=usage(30, reset_min=40))), \
                mock.patch.object(core, "run_ccs") as run:
            self.d.tick(self.settings, NOW)
        run.assert_not_called()

    def test_failed_switch_does_not_notify(self):
        ko = subprocess.CompletedProcess([], 1, "", "ccs: erreur")
        with fake_http(per_account(perso=usage(40, reset_min=200), pro=usage(30, reset_min=40))), \
                mock.patch.object(core, "run_ccs", return_value=ko):
            self.d.tick(self.settings, NOW)
        self.assertFalse(any("Bascule" in a.title for a in self.sent))

    def test_stale_warmup_dirs_cleaned_at_start(self):
        import tempfile
        leftover = tempfile.mkdtemp(prefix="ccs-warmup-")
        daemon.clean_warmup_leftovers()
        self.assertFalse(os.path.exists(leftover))
