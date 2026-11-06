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


class SessionsCliTest(HomeTestCase):
    def test_sessions_list(self):
        from ccs_app import sessions
        s = sessions.Session(42, "sid", "gigit-cb", "/w/GiGit", "GiGit", "waiting", "permission",
                             time.time() - 3600, time.time() - 30, "interactive", "cli")
        usage = sessions.ConversationUsage(13_500_000, "opus", 316)
        with mock.patch.object(sessions, "list_sessions", return_value=[s]), \
                mock.patch.object(sessions, "conversation_usage", return_value=usage):
            code, out = run("sessions")
        self.assertEqual(code, 0)
        self.assertIn("GiGit", out)
        self.assertIn("attend ta réponse (permission)", out)
        self.assertIn("13,5 M", out)
        self.assertIn("1 h", out)

    def test_sessions_empty(self):
        from ccs_app import sessions
        with mock.patch.object(sessions, "list_sessions", return_value=[]):
            self.assertIn("Aucune session", run("sessions")[1])


class IntegrationCliTest(HomeTestCase):
    def test_integrate_on_status_off(self):
        code, out = run("integrate", "on")
        self.assertEqual(code, 0)
        self.assertIn("Ligne d'état installée", out)
        self.assertIn("installée", run("integrate", "status")[1])
        run("integrate", "off")
        self.assertIn("non installée", run("integrate", "status")[1])

    def test_statusline_prints_one_line(self):
        write(self.store / "state.json", dict(STATE, updated_at=time.time()))
        with mock.patch("sys.stdin", io.StringIO('{"session_id": "x"}')):
            code, out = run("statusline")
        self.assertEqual(out.count("\n"), 1)
        self.assertIn("perso", out)

    def test_hook_reads_stdin(self):
        from ccs_app import integration
        with mock.patch("sys.stdin", io.StringIO('{"error": "overloaded"}')), \
                mock.patch.object(integration, "stop_failure", return_value="ignoré") as sf:
            self.assertEqual(run("hook", "stop-failure")[0], 0)
        sf.assert_called_once_with({"error": "overloaded"})


class RobustCliTest(HomeTestCase):
    def test_statusline_never_prints_traceback(self):
        bad = dict(STATE, updated_at=time.time())
        bad["accounts"] = [dict(STATE["accounts"][0], limits=[{"kind": "session", "percent": None}])]
        write(self.store / "state.json", bad)
        with mock.patch("sys.stdin", io.StringIO("{}")):
            code, out = run("statusline")
        self.assertEqual(code, 0)
        self.assertIn("CCS", out)
        self.assertNotIn("Traceback", out)

    def test_hook_never_fails(self):
        from ccs_app import integration
        with mock.patch("sys.stdin", io.StringIO('{"error": "rate_limit"}')), \
                mock.patch.object(integration, "stop_failure", side_effect=RuntimeError("boum")):
            self.assertEqual(run("hook", "stop-failure")[0], 0)


class GuiCliTest(HomeTestCase):
    def run_gui(self, *argv):
        import sys
        import types
        fake = types.ModuleType("ccs_app.gui.app")
        fake.run = mock.Mock(return_value=0)
        with mock.patch.dict(sys.modules, {"ccs_app.gui.app": fake}):
            code = cli.main(list(argv))
        return code, fake.run

    def test_plain_launch(self):
        for argv in ((), ("gui",)):
            code, launched = self.run_gui(*argv)
            self.assertEqual(code, 0)
            launched.assert_called_once_with(session=None)

    def test_session_from_a_notification(self):
        code, launched = self.run_gui("gui", "--session", "4242:3f2a9c1e")
        launched.assert_called_once_with(session="4242:3f2a9c1e")


class DoctorCliTest(HomeTestCase):
    def check(self, statut):
        from ccs_app import doctor
        return doctor.Check("Service ccs-daemon", statut, "détail",
                            None if statut == doctor.OK else "systemctl --user start ccs-daemon")

    def test_all_good_exit_0(self):
        from ccs_app import doctor
        with mock.patch.object(doctor, "run_checks", return_value=[self.check(doctor.OK)]):
            code, out = run("doctor")
        self.assertEqual(code, 0)
        self.assertIn("Service ccs-daemon", out)
        self.assertIn("Tout va bien", out)

    def test_problem_exit_1(self):
        from ccs_app import doctor
        with mock.patch.object(doctor, "run_checks",
                               return_value=[self.check(doctor.OK), self.check(doctor.ERREUR)]):
            code, out = run("doctor")
        self.assertEqual(code, 1)
        self.assertIn("systemctl --user start ccs-daemon", out)


class PauseCliTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        from ccs_app import daemon
        refresh = mock.patch.object(daemon, "request_refresh", return_value=True)
        self.refresh = refresh.start()
        self.addCleanup(refresh.stop)

    def test_default_is_status(self):
        code, out = run("pause")
        self.assertEqual(code, 0)
        self.assertIn("Pas de pause", out)
        self.refresh.assert_not_called()

    def test_pause_then_status_then_off(self):
        from ccs_app import pause
        code, out = run("pause", "1h")
        self.assertEqual(code, 0)
        self.assertIn("en pause jusqu'à", out)
        self.assertTrue(pause.pause_path().exists())
        self.refresh.assert_called_once()
        self.assertIn("En pause jusqu'à", run("pause", "status")[1])
        code, out = run("pause", "off")
        self.assertEqual(code, 0)
        self.assertIn("Pause levée", out)
        self.assertFalse(pause.pause_path().exists())
        self.assertEqual(self.refresh.call_count, 2)

    def test_manual_pause_and_resume_word(self):
        code, out = run("pause", "manuel")
        self.assertEqual(code, 0)
        self.assertIn("reprise manuelle", out)
        self.assertIn("Pause levée", run("pause", "reprendre")[1])

    def test_off_without_pause_does_not_wake_the_service(self):
        code, out = run("pause", "off")
        self.assertEqual(code, 0)
        self.assertIn("Pas de pause en cours", out)
        self.refresh.assert_not_called()

    def test_unknown_choice_exit_2_on_stderr(self):
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            code, out = run("pause", "2h")
        self.assertEqual(code, 2)
        self.assertIn("usage : ccs pause", err.getvalue())
        self.assertEqual(out, "")
        self.refresh.assert_not_called()

    def test_status_shows_the_pause(self):
        self.assertNotIn("En pause", run("status")[1])
        run("pause", "manuel")
        out = run("status")[1]
        self.assertIn("En pause jusqu'à reprise manuelle", out)
        self.assertIn("ccs pause off", out)


class PreviewExportCliTest(HomeTestCase):
    SID = "3f2a9c1e-0000-4000-8000-000000000001"

    def setUp(self):
        super().setUp()
        from ccs_app import costs, sessions
        costs.clear_cache()
        self.cwd = self.home / "Work" / "App"
        self.cwd.mkdir(parents=True)
        rows = [
            {"type": "user", "cwd": str(self.cwd), "timestamp": "2026-11-04T10:00:00.000Z",
             "sessionId": self.SID, "entrypoint": "cli", "gitBranch": "main", "origin": {"kind": "human"},
             "message": {"role": "user", "content": "Corrige le calcul des intérêts"}},
            {"type": "assistant", "cwd": str(self.cwd), "timestamp": "2026-11-04T10:01:00.000Z",
             "message": {"id": "m1", "role": "assistant", "model": "claude-opus-5-5",
                         "content": [{"type": "text", "text": "C'est corrigé."}],
                         "usage": {"input_tokens": 1000, "output_tokens": 500}}},
            {"type": "custom-title", "customTitle": "Calcul des intérêts", "sessionId": self.SID},
        ]
        self.path = (self.home / ".claude" / "projects" / sessions.project_slug(str(self.cwd))
                     / f"{self.SID}.jsonl")
        write(self.path, "".join(json.dumps(r) + "\n" for r in rows))

    def test_preview_prints_markdown_with_cost(self):
        code, out = run("preview", self.SID[:8])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("# Calcul des intérêts\n"), out[:80])
        self.assertIn("Corrige le calcul des intérêts", out)
        self.assertIn("C'est corrigé.", out)
        self.assertRegex(out, r"\n- Coût : 1[,.]5 k tokens · ≈ .* \(équivalent API\)\n")

    def test_preview_alias_and_full_id(self):
        self.assertIn("C'est corrigé.", run("apercu", self.SID)[1])

    def test_preview_unknown_or_ambiguous_id(self):
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            self.assertEqual(run("preview", "zzzz")[0], 1)
            self.assertEqual(run("preview", "3f")[0], 1)
        self.assertIn("aucune conversation", err.getvalue())
        self.assertIn("4 caractères", err.getvalue())

    def test_export_default_name_in_current_folder(self):
        import os
        out_dir = self.home / "exports"
        out_dir.mkdir()
        cwd = os.getcwd()
        os.chdir(out_dir)
        try:
            code, out = run("export", self.SID[:6])
        finally:
            os.chdir(cwd)
        dest = out_dir / "calcul-des-interets.md"
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), str(dest))
        text = dest.read_text()
        self.assertIn("# Calcul des intérêts", text)
        self.assertIn("- Coût : ", text)

    def test_export_to_file_or_folder(self):
        dest = self.home / "notes" / "conv.md"
        code, out = run("export", self.SID[:6], str(dest))
        self.assertEqual((code, out.strip()), (0, str(dest)))
        self.assertIn("C'est corrigé.", dest.read_text())
        code, out = run("export", self.SID[:6], str(self.home / "notes"))
        self.assertEqual(out.strip(), str(self.home / "notes" / "calcul-des-interets.md"))

    def test_export_error_exit_1(self):
        blocker = self.home / "fichier"
        blocker.write_text("x")
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            code, _out = run("export", self.SID[:6], str(blocker / "sous" / "conv.md"))
        self.assertEqual(code, 1)
        self.assertIn("Erreur", err.getvalue())

    def test_title_and_resume_print_still_work(self):
        code, out = run("title", self.SID[:6], "Nouveau", "titre")
        self.assertEqual(code, 0)
        self.assertIn("« Nouveau titre »", out)
        code, out = run("resume", self.SID[:6], "--print")
        self.assertEqual(code, 0)
        self.assertIn(f"--resume {self.SID}", out)
