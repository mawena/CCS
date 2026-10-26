import io
import json
import shutil
import subprocess
import time
from contextlib import redirect_stdout
from unittest import mock

from ccs_app import cli, core
from ccs_app.settings import load_settings
from tests.helpers import HomeTestCase, write


def run(*argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = cli.main(list(argv))
    return code, out.getvalue()


STATE = {
    "updated_at": None, "active": "perso", "capacity": 1.06,
    "best": {"name": "pro", "reason": "au repos, semaine à 22 %"},
    "auto_switch": {"enabled": True, "decision": {"action": "none"}},
    "accounts": [
        {"name": "perso", "active": True, "limits": [
            {"kind": "session", "label": "Session (5 h)", "percent": 72, "resets_at": None},
            {"kind": "weekly_all", "label": "Semaine", "percent": 52, "resets_at": None}],
         "forecast": {"verdict": "limit", "eta": "2026-10-26T12:30:00+00:00"}},
        {"name": "pro", "active": False, "limits": [
            {"kind": "session", "label": "Session (5 h)", "percent": 15, "resets_at": None}]},
    ],
}


class CliTest(HomeTestCase):
    def write_state(self, **over):
        st = dict(STATE, updated_at=time.time(), **over)
        write(self.store / "state.json", st)

    def test_auto_on_off_persists(self):
        self.assertEqual(run("auto", "off")[0], 0)
        self.assertFalse(load_settings()["auto_switch"]["enabled"])
        code, out = run("auto", "on")
        self.assertTrue(load_settings()["auto_switch"]["enabled"])
        self.assertIn("activée", out)

    def test_status_text_contains_best(self):
        self.write_state()
        code, out = run("status")
        self.assertEqual(code, 0)
        self.assertIn("Compte actif : perso", out)
        self.assertIn("Meilleur compte : pro", out)
        self.assertIn("1,1", out)
        self.assertIn("activée", out)

    def test_status_without_state(self):
        code, out = run("status")
        self.assertEqual(code, 0)
        self.assertIn("aucune donnée", out)

    def test_best_switches_when_different(self):
        self.write_state()
        ok = subprocess.CompletedProcess([], 0, "basculé", "")
        with mock.patch.object(core, "run_ccs", return_value=ok) as rc:
            code, out = run("best", "--switch")
        self.assertEqual(code, 0)
        rc.assert_called_once_with(["use", "pro"])

    def test_best_already_active(self):
        self.write_state(best={"name": "perso", "reason": "r"})
        with mock.patch.object(core, "run_ccs") as rc:
            code, out = run("best", "--switch")
        rc.assert_not_called()
        self.assertIn("déjà", out)

    def test_best_without_profiles_exit_1(self):
        shutil.rmtree(self.store / "perso")
        shutil.rmtree(self.store / "pro")
        self.assertEqual(run("best")[0], 1)

    def test_best_none_available_exit_1(self):
        self.write_state(best=None)
        code, out = run("best")
        self.assertEqual(code, 1)
        self.assertIn("Aucun compte", out)


class PrintTest(HomeTestCase):
    def test_print_shows_forecast_and_pace_from_state(self):
        from tests.helpers import fake_http
        st = dict(STATE, updated_at=time.time())
        st["accounts"][0]["pace"] = {"ideal": 57, "margin": 5, "per_day_budget": 16, "days_left": 3}
        write(self.store / "state.json", st)
        usage = {"limits": [{"kind": "session", "percent": 72, "resets_at": None}]}
        with fake_http({"/api/oauth/usage": usage}):
            code, out = run("print")
        self.assertIn("Limite estimée vers", out)
        self.assertIn("budget 16 %/jour", out)


class BestFreshnessTest(HomeTestCase):
    """Revue finale I3 : ne pas basculer sur un état ancien."""

    def test_best_collects_first_when_state_is_stale(self):
        from ccs_app import daemon
        st = dict(STATE, updated_at=time.time() - 3 * 3600)
        write(self.store / "state.json", st)
        fresh = dict(STATE, updated_at=time.time(), best={"name": "perso", "reason": "r"})
        with mock.patch.object(daemon, "collect_once",
                               side_effect=lambda: write(self.store / "state.json", fresh)) as c, \
                mock.patch.object(core, "run_ccs") as rc:
            code, out = run("best", "--switch")
        c.assert_called_once()
        rc.assert_not_called()
        self.assertIn("déjà", out)


class OrchestratorCliTest(HomeTestCase):
    def test_orch_on_off_persists(self):
        code, out = run("orch", "on")
        self.assertTrue(load_settings()["orchestrator"]["enabled"])
        self.assertIn("activé", out)
        run("orch", "off")
        self.assertFalse(load_settings()["orchestrator"]["enabled"])

    def test_status_shows_orchestrator(self):
        run("orch", "on")
        self.assertIn("Orchestrateur : activé", run("status")[1])

    def test_plan_lists_windows_and_recharges(self):
        def iso(h, m=0):
            from datetime import datetime
            return datetime(2026, 10, 26, h, m).astimezone().isoformat()
        st = dict(STATE, updated_at=time.time(), orchestrator={
            "enabled": True, "active_now": True, "period": [iso(8), iso(23)],
            "next_wake": iso(12, 0), "reserve": ["pro"],
            "plan": [{"name": "perso", "start": iso(7), "end": iso(12), "kind": "current"},
                     {"name": "perso", "start": iso(12), "end": iso(17), "kind": "planned"},
                     {"name": "pro", "start": iso(10, 30), "end": iso(15, 30), "kind": "planned"}]})
        write(self.store / "state.json", st)
        code, out = run("plan")
        self.assertEqual(code, 0)
        self.assertIn("07:00–12:00 (en cours)", out)
        self.assertIn("10:30–15:30", out)
        self.assertIn("Recharges", out)
        self.assertIn("12:00 perso", out)
        self.assertIn("réserve", out)

    def test_plan_without_state(self):
        code, out = run("plan")
        self.assertIn("aucune donnée", out)
