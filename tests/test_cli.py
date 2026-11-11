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


class BestUnusableAccountsTest(HomeTestCase):
    """`ccs best` ignore les comptes dont le dernier relevé est en erreur."""

    def state(self, perso=None, pro=None, best="pro", **over):
        now = time.time()
        st = json.loads(json.dumps(STATE))
        st.update(updated_at=now, best={"name": best, "reason": "au repos, semaine à 22 %"} if best else None)
        for acc, extra in zip(st["accounts"], (perso or {}, pro or {})):
            acc.update(error=None, fetched_at=now - 30)
            acc.update(extra)
        st.update(over)
        write(self.store / "state.json", st)

    LOST = {"error": "connexion perdue : reconnecte ce compte"}

    def test_best_in_error_is_replaced_and_explained(self):
        self.state(pro=self.LOST)
        with mock.patch.object(core, "run_ccs") as rc:
            code, out = run("best", "--switch")
        rc.assert_not_called()
        self.assertEqual(code, 0)
        self.assertIn("pro ignoré : connexion perdue", out)
        self.assertIn("Meilleur compte : perso", out)
        self.assertIn("déjà", out)

    def test_best_switches_to_usable_account_only(self):
        self.state(perso=self.LOST, best="perso")
        ok = subprocess.CompletedProcess([], 0, "basculé", "")
        with mock.patch.object(core, "run_ccs", return_value=ok) as rc:
            code, out = run("best", "--switch")
        self.assertIn("perso ignoré : connexion perdue", out)
        rc.assert_called_once_with(["use", "pro"])

    def test_no_usable_account_message_and_no_switch(self):
        self.state(perso=self.LOST, pro={"error": "HTTP 401"})
        with mock.patch.object(core, "run_ccs") as rc, mock.patch.object(cli, "_notify") as n:
            code, out = run("best", "--switch", "--notifier")
        rc.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("Aucun compte utilisable", out)
        self.assertIn("perso ignoré : connexion perdue", out)
        self.assertIn("pro ignoré : connexion refusée (HTTP 401)", out)
        n.assert_called_once()
        self.assertIn("connexion perdue", n.call_args[0][1])

    def test_stale_or_missing_sample_is_ignored(self):
        self.state(pro={"fetched_at": time.time() - 3600})
        code, out = run("best")
        self.assertIn("pro ignoré : relevé trop ancien", out)
        self.assertIn("Meilleur compte : perso", out)
        self.state(pro={"fetched_at": None})
        self.assertIn("pro ignoré : aucun relevé", run("best")[1])

    def test_transient_error_with_fresh_sample_is_kept(self):
        self.state(pro={"error": "HTTP 429"})
        code, out = run("best")
        self.assertIn("Meilleur compte : pro", out)
        self.assertNotIn("ignoré", out)

    def test_nothing_ignored_prints_no_extra_line(self):
        self.state()
        self.assertNotIn("ignoré", run("best")[1])


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
            launched.assert_called_once_with(session=None, page=None, new_session=False)

    def test_session_from_a_notification(self):
        code, launched = self.run_gui("gui", "--session", "4242:3f2a9c1e")
        launched.assert_called_once_with(session="4242:3f2a9c1e", page=None, new_session=False)

    def test_page(self):
        for text, name in (("sessions", "sessions"), ("historique", "history"), ("Réglages", "prefs"),
                           ("analysis", "analysis")):
            code, launched = self.run_gui("gui", "--page", text)
            self.assertEqual(code, 0)
            launched.assert_called_once_with(session=None, page=name, new_session=False)

    def test_unknown_page_is_refused(self):
        err = io.StringIO()
        with mock.patch("sys.stderr", err), self.assertRaises(SystemExit) as raised:
            self.run_gui("gui", "--page", "inconnu")
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("onglet inconnu", err.getvalue())
        self.assertIn("sessions, comptes, planning", err.getvalue())

    def test_task_from_a_notification(self):
        code, launched = self.run_gui("gui", "--page", "planning", "--task", "12")
        self.assertEqual(code, 0)
        launched.assert_called_once_with(session=None, page="planning", new_session=False, task="12")

    def test_unreadable_task_is_refused(self):
        err = io.StringIO()
        with mock.patch("sys.stderr", err), self.assertRaises(SystemExit) as raised:
            self.run_gui("gui", "--task", "-x")
        self.assertEqual(raised.exception.code, 2)

    def test_new_session(self):
        code, launched = self.run_gui("gui", "--new-session")
        launched.assert_called_once_with(session=None, page=None, new_session=True)
        code, launched = self.run_gui("gui", "--page", "comptes", "--new-session")
        launched.assert_called_once_with(session=None, page="accounts", new_session=True)


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


class _Tty(io.StringIO):
    """Sortie d'erreur vue comme un terminal."""

    def isatty(self):
        return True


class FormuleCliTest(HomeTestCase):
    ADVICE = mock.Mock(summary="2 comptes Pro suffisent.", reasons=["Semaine la plus chargée : 1,4 Pro."])

    def test_prints_the_advice_and_alias(self):
        from ccs_app import advisor
        for name in ("formule", "conseil"):
            with self.subTest(name=name), mock.patch.object(advisor, "compute", return_value=self.ADVICE):
                code, out = run(name)
            self.assertEqual(code, 0)
            self.assertEqual(out, advisor.format_text(self.ADVICE) + "\n")

    def test_waiting_message_only_on_a_terminal(self):
        from ccs_app import advisor
        for err, shown in ((_Tty(), True), (io.StringIO(), False)):
            with mock.patch("sys.stderr", err), mock.patch.object(advisor, "compute", return_value=self.ADVICE):
                self.assertEqual(run("formule")[0], 0)
            self.assertEqual("Calcul" in err.getvalue(), shown, err.getvalue())

    def test_failure_exit_1_on_stderr(self):
        from ccs_app import advisor
        err = io.StringIO()
        with mock.patch("sys.stderr", err), \
                mock.patch.object(advisor, "compute", side_effect=OSError("historique illisible")):
            code, out = run("formule")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("historique illisible", err.getvalue())


class SemaineCliTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        from ccs_app import weekly_report
        self.wr = weekly_report
        self.built = []
        report = mock.Mock()
        p = mock.patch.object(weekly_report, "build_report",
                              side_effect=lambda s, e: (self.built.append((s, e)), report)[1])
        p.start()
        self.addCleanup(p.stop)
        f = mock.patch.object(weekly_report, "format_text", return_value="Bilan du 26 oct. au 2 nov.")
        f.start()
        self.addCleanup(f.stop)

    def weeks(self):
        from datetime import datetime, timezone
        return self.wr.week_choices([], datetime.now(timezone.utc), load_settings(), count=4)

    def test_last_finished_week_by_default(self):
        code, out = run("semaine")
        self.assertEqual((code, out), (0, "Bilan du 26 oct. au 2 nov.\n"))
        self.assertEqual(self.built, [self.weeks()[1]])

    def test_weeks_before(self):
        self.assertEqual(run("semaine", "--precedente", "2")[0], 0)
        self.assertEqual(run("semaine", "--precedente", "0")[0], 0)
        self.assertEqual(self.built, [self.weeks()[3], self.weeks()[1]])

    def test_invalid_count_exit_2(self):
        for bad in ("-1", "deux", "100000"):
            err = io.StringIO()
            with self.subTest(n=bad), mock.patch("sys.stderr", err), self.assertRaises(SystemExit) as e:
                run("semaine", "--precedente", bad)
            self.assertEqual(e.exception.code, 2)
            self.assertIn("--precedente", err.getvalue())
        self.assertEqual(self.built, [])

    def test_failure_exit_1(self):
        err = io.StringIO()
        with mock.patch("sys.stderr", err), \
                mock.patch.object(self.wr, "build_report", side_effect=OSError("journal illisible")):
            self.assertEqual(run("semaine")[0], 1)
        self.assertIn("journal illisible", err.getvalue())


class JournalCliTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        from ccs_app.store import Store
        now = time.time()
        store = Store()
        store.add_event(now - 20 * 86400, "switch", "perso", {"mode": "initial"})
        store.add_event(now - 10 * 86400, "switch", "pro", {"mode": "manual", "via": "ccs", "from": "perso"})
        store.add_event(now - 3600, "switch", "perso", {"mode": "manual", "via": "icone", "from": "pro"})
        store.close()

    def test_default_is_seven_days(self):
        code, out = run("journal")
        self.assertEqual(code, 0)
        self.assertIn("pro → perso", out)
        self.assertIn("depuis l'icône", out)
        self.assertNotIn("perso → pro", out)

    def test_days_and_everything(self):
        self.assertIn("perso → pro", run("journal", "--jours", "30")[1])
        out = run("journal", "--tout")[1]
        self.assertIn("perso → pro", out)
        self.assertIn("Début du suivi", out)

    def test_invalid_usage_exit_2(self):
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            code, out = run("journal", "--jours", "0")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("usage : ccs journal [--jours N | --tout]", err.getvalue())
        for argv in (("--jours", "3", "--tout"), ("--jours", "x")):
            with self.subTest(argv=argv), mock.patch("sys.stderr", io.StringIO()), \
                    self.assertRaises(SystemExit) as e:
                run("journal", *argv)
            self.assertEqual(e.exception.code, 2)


class ProjetCliTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        import os
        self.app = self.home / "Work" / "App"
        self.app.mkdir(parents=True)
        cwd = os.getcwd()
        os.chdir(self.app)
        self.addCleanup(os.chdir, cwd)

    def test_list_associate_show_remove(self):
        from ccs_app import project_accounts
        self.assertEqual(run("projet"), (0, "Aucun projet associé à un compte.\n"))
        code, out = run("projet", "pro")   # dossier courant
        self.assertEqual(code, 0)
        self.assertIn("→ pro", out)
        self.assertEqual(project_accounts.get(str(self.app)).profile, "pro")
        self.assertIn("→ pro", run("projet", str(self.app))[1])
        self.assertEqual(run("projet", str(self.app), "aucun")[0], 0)
        self.assertIsNone(project_accounts.get(str(self.app)))

    def test_errors_on_stderr(self):
        for argv, code in ((("inconnu-zz",), 2), ((str(self.app), "zz"), 1), (("a", "b", "c"), 2),
                           ((str(self.home / "absent"), "pro"), 1)):
            err = io.StringIO()
            with self.subTest(argv=argv), mock.patch("sys.stderr", err):
                self.assertEqual(run("projet", *argv), (code, ""))
            self.assertTrue(err.getvalue().strip())


class RaccourcisCliTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        import os
        from ccs_app import shortcuts as sc
        self.sc = sc
        self.backend = sc.MemoryBackend.gnome()
        for p in (mock.patch.object(sc, "default_backend", return_value=self.backend),
                  mock.patch.object(sc, "command_for", side_effect=lambda a: "/usr/bin/" + sc.action(a).display),
                  mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"})):
            p.start()
            self.addCleanup(p.stop)

    def test_status_on_set_off_and_alias(self):
        code, out = run("raccourcis")
        self.assertEqual(code, 0)
        self.assertIn("Raccourcis clavier globaux", out)
        self.assertEqual(run("raccourcis", "on", "suivant")[0], 0)
        self.assertEqual(self.backend.get(self.sc.MEDIA_KEYS, self.sc.CUSTOM_KEY),
                         [self.sc.action("suivant").path])
        code, out = run("shortcuts", "set", "suivant", "Super+Alt+K")
        self.assertEqual(code, 0)
        self.assertIn("Super+Alt+K", out)
        self.assertIn("Raccourcis retirés", run("raccourcis", "off")[1])
        self.assertEqual(self.backend.get(self.sc.MEDIA_KEYS, self.sc.CUSTOM_KEY), [])

    def test_usage_and_refusal_on_stderr(self):
        for argv, code in ((("on", "zzz"), 2), (("set", "suivant"), 2), (("set", "suivant", "K"), 1)):
            err = io.StringIO()
            with self.subTest(argv=argv), mock.patch("sys.stderr", err):
                self.assertEqual(run("raccourcis", *argv), (code, ""))
            self.assertTrue(err.getvalue().strip())

    def test_other_desktop_shows_the_commands(self):
        import os
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}):
            code, out = run("raccourcis", "status")
        self.assertEqual(code, 1)
        self.assertIn("seulement sous GNOME", out)
        self.assertIn("/usr/bin/ccs next", out)


class StatuslineHintCliTest(HomeTestCase):
    def write_state(self, percent):
        st = dict(STATE, updated_at=time.time())
        st["accounts"] = [dict(STATE["accounts"][0], limits=[
            {"kind": "session", "label": "Session (5 h)", "percent": percent, "resets_at": None}])]
        write(self.store / "state.json", st)

    def statusline(self, stdin):
        with mock.patch("sys.stdin", stdin):
            return run("statusline")

    def test_cheaper_model_hint_from_the_session_model(self):
        self.write_state(85)
        payload = json.dumps({"session_id": "x", "model": {"id": "claude-opus-5-5", "display_name": "Opus"}})
        code, out = self.statusline(io.StringIO(payload))
        self.assertEqual(code, 0)
        self.assertIn("→ sonnet ?", out)
        self.write_state(40)
        self.assertNotIn("→", self.statusline(io.StringIO(payload))[1])

    def test_empty_or_terminal_input_never_blocks(self):
        self.write_state(85)
        tty = mock.Mock()
        tty.isatty.return_value = True
        tty.read.side_effect = AssertionError("lecture bloquante d'un terminal")
        for stdin in (io.StringIO(""), io.StringIO("pas du json"), io.StringIO("[1]"), tty):
            with self.subTest(stdin=stdin):
                code, out = self.statusline(stdin)
            self.assertEqual(code, 0)
            self.assertIn("perso", out)
            self.assertEqual(out.count("\n"), 1)

    def test_broken_hint_keeps_the_line(self):
        self.write_state(85)
        from ccs_app import model_advice
        with mock.patch.object(model_advice, "statusline_hint", side_effect=KeyError("alerts")):
            code, out = self.statusline(io.StringIO('{"model": "claude-opus-5-5"}'))
        self.assertIn("perso", out)
        self.assertNotIn("illisible", out)


class NotifierCliTest(HomeTestCase):
    """Commandes des raccourcis clavier (--notifier) : résultat en notification bureau."""

    def setUp(self):
        super().setUp()
        from ccs_app import daemon, notify
        self.sent = []
        for p in (mock.patch.object(notify, "send", side_effect=lambda a, **k: self.sent.append(a) or 7),
                  mock.patch.object(daemon, "request_refresh", return_value=True)):
            p.start()
            self.addCleanup(p.stop)

    def titles(self):
        return [(a.title, a.body) for a in self.sent]

    def test_notify_command(self):
        self.assertEqual(run("notify", "--", "Bascule sur pro", "b@y.com")[0], 0)
        self.assertEqual(self.titles(), [("Bascule sur pro", "b@y.com")])

    def test_best_switch_notifies_and_notes_the_shortcut(self):
        from ccs_app import switch_log
        write(self.store / "state.json", dict(STATE, updated_at=time.time()))
        ok = subprocess.CompletedProcess([], 0, "✔ basculé sur 'pro'", "")
        notes = []

        def use(args):
            notes.append(core.load_json(switch_log.origin_path()))
            return ok
        with mock.patch.object(core, "run_ccs", side_effect=use):
            self.assertEqual(run("best", "--switch", "--notifier")[0], 0)
        self.assertEqual(notes[0]["via"], "raccourci")
        self.assertEqual(notes[0]["profile"], "pro")
        self.assertEqual(self.titles(), [("Bascule sur pro", "Meilleur compte : au repos, semaine à 22 %")])

    def test_best_by_hand_notes_ccs_without_notification(self):
        from ccs_app import switch_log
        write(self.store / "state.json", dict(STATE, updated_at=time.time()))
        ok = subprocess.CompletedProcess([], 0, "ok", "")
        with mock.patch.object(core, "run_ccs", return_value=ok):
            run("best", "--switch")
        self.assertEqual(core.load_json(switch_log.origin_path())["via"], "ccs")
        self.assertEqual(self.sent, [])

    def test_best_failure_and_already_active(self):
        from ccs_app import switch_log
        write(self.store / "state.json", dict(STATE, updated_at=time.time()))
        bad = subprocess.CompletedProcess([], 1, "", "ccs: 'pro' : connexion perdue")
        with mock.patch.object(core, "run_ccs", return_value=bad):
            self.assertEqual(run("best", "--switch", "--notifier")[0], 1)
        self.assertEqual(self.titles(), [("Bascule impossible", "ccs: 'pro' : connexion perdue")])
        self.assertFalse(switch_log.origin_path().exists())   # pas d'origine pour une bascule ratée
        self.sent.clear()
        write(self.store / "state.json", dict(STATE, updated_at=time.time(), best={"name": "perso", "reason": "r"}))
        self.assertEqual(run("best", "--switch", "--notifier")[0], 0)
        self.assertEqual(self.titles()[0][0], "Déjà sur perso")

    def test_pause_notifies(self):
        code, out = run("pause", "1h", "--notifier")
        self.assertEqual(code, 0)
        self.assertRegex(self.titles()[0][0], r"^Pause jusqu'à \d\d:\d\d$")
        self.sent.clear()
        run("pause", "off", "--notifier")
        self.assertEqual(self.titles()[0][0], "Pause levée")
        self.sent.clear()
        with mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(run("pause", "2h", "--notifier")[0], 2)
        self.assertEqual(self.titles()[0][0], "Pause impossible")

    def test_pause_without_notifier_is_silent(self):
        run("pause", "1h")
        self.assertEqual(self.sent, [])


class OriginFromBashTest(HomeTestCase):
    """La note écrite par `ccs` (bash, sans Python) est lue par le service, et le journal
    affiche l'origine de la bascule."""

    def ccs(self, *args, **env):
        import os
        from pathlib import Path
        fake = Path(self.tmp) / "bin"
        fake.mkdir(exist_ok=True)
        (fake / "notify-send").write_text("#!/bin/sh\nexit 0\n")   # jamais le vrai bureau
        (fake / "notify-send").chmod(0o755)
        environ = dict(os.environ, NO_COLOR="1", DBUS_SESSION_BUS_ADDRESS=f"unix:path={self.tmp}/aucun-bus",
                       PATH=f"{fake}:{os.environ.get('PATH', '/usr/bin:/bin')}", **env)
        environ.pop("CCS_VIA", None)
        environ.update(env)
        script = Path(__file__).resolve().parent.parent / "bin" / "ccs"
        return subprocess.run([str(script), *args], capture_output=True, text=True, env=environ, timeout=60)

    def journal_after(self, *args, **env):
        from datetime import datetime, timezone
        from ccs_app import daemon, switch_log
        from ccs_app.store import Store
        store = Store()
        self.addCleanup(store.close)
        store.add_event(time.time() - 60, "switch", "perso", {"mode": "initial"})
        r = self.ccs(*args, **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        daemon.Daemon(store, notifier=lambda a: None).detect_manual_switch(datetime.now(timezone.utc))
        self.assertFalse(switch_log.origin_path().exists())   # lue puis retirée par le service
        return switch_log.load(store, 1, markers={})[0]

    def test_shortcut(self):
        entry = self.journal_after("next", "--notifier")
        self.assertEqual((entry.title, entry.reason), ("perso → pro", "Bascule manuelle par un raccourci clavier"))

    def test_by_hand(self):
        entry = self.journal_after("pro")
        self.assertEqual(entry.reason, "Bascule manuelle par la commande ccs")

    def test_application_note_is_kept(self):
        from ccs_app import switch_log
        switch_log.note_origin("pro", "application")   # notée juste avant par l'application
        entry = self.journal_after("use", "pro")
        self.assertEqual(entry.reason, "Bascule manuelle depuis l'application")

    def test_nothing_noted_when_the_caller_handles_it(self):
        entry = self.journal_after("use", "pro", CCS_VIA="")
        self.assertEqual(entry.reason, "Bascule manuelle (application, icône ou « ccs use »)")


class SilenceCliTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.sent = []
        patch = mock.patch("ccs_app.notify.message", side_effect=lambda t, b="": self.sent.append((t, b)) or 1)
        patch.start()
        self.addCleanup(patch.stop)
        refresh = mock.patch("ccs_app.daemon.request_refresh", return_value=True)
        self.refresh = refresh.start()
        self.addCleanup(refresh.stop)

    def test_status_without_silence(self):
        code, out = run("silence")
        self.assertEqual(code, 0)
        self.assertIn("Pas de silence", out)
        self.refresh.assert_not_called()

    def test_silence_then_status_then_off(self):
        from ccs_app import quiet
        code, out = run("silence", "1h")
        self.assertEqual(code, 0)
        self.assertIn("Silence jusqu'à", out)
        self.assertTrue(quiet.quiet_path().exists())
        self.assertEqual(self.refresh.call_count, 1)
        self.assertIn("Ne pas déranger jusqu'à", run("status")[1])
        code, out = run("quiet", "reprendre")
        self.assertEqual(code, 0)
        self.assertFalse(quiet.quiet_path().exists())
        self.assertEqual(self.refresh.call_count, 2)
        self.assertNotIn("Ne pas déranger", run("status")[1])

    def test_off_without_silence_does_not_wake_the_service(self):
        self.assertEqual(run("silence", "off")[0], 0)
        self.refresh.assert_not_called()

    def test_usage_exit_2(self):
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            code, out = run("silence", "2h")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("usage : ccs silence", err.getvalue())

    def test_notifier(self):
        run("silence", "1h", "--notifier")
        self.assertRegex(self.sent[0][0], r"^Ne pas déranger jusqu'à \d\d:\d\d$")
        self.sent.clear()
        run("silence", "off", "--notifier")
        self.assertEqual(self.sent[0][0], "Silence levé")
        self.sent.clear()
        with mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(run("silence", "2h", "--notifier")[0], 2)
        self.assertEqual(self.sent[0][0], "Silence impossible")

    def test_without_notifier_is_silent(self):
        run("silence", "1h")
        self.assertEqual(self.sent, [])


class MomentCliTest(HomeTestCase):
    def test_without_state_exit_1(self):
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            code, out = run("moment")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("Aucun état", err.getvalue())

    def test_with_options(self):
        write(self.store / "state.json", dict(STATE, updated_at=time.time()))
        code, out = run("moment", "--duree", "2h", "--sur", "12h")
        self.assertEqual(code, 0)
        self.assertTrue(out.strip())

    def test_usage_exit_2(self):
        with mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(run("moment", "--duree", "zéro")[0], 2)
            with self.assertRaises(SystemExit) as e:
                run("moment", "--bof")
            self.assertEqual(e.exception.code, 2)


class MoisCliTest(HomeTestCase):
    def test_report_and_previous(self):
        from ccs_app import monthly_report as mr
        built = []
        with mock.patch.object(mr, "build_report", side_effect=lambda s, e: built.append((s, e)) or "r"), \
                mock.patch.object(mr, "format_text", return_value="Rapport de test\n"):
            self.assertEqual(run("mois"), (0, "Rapport de test\n\n"))
            self.assertEqual(run("mois", "--precedent", "2")[0], 0)
        self.assertEqual(len(built), 2)
        self.assertEqual(mr.shift(built[0][0], -2), built[1][0])

    def test_invalid_count_exit_2(self):
        for bad in ("-1", "deux", "100000"):
            with self.subTest(n=bad), mock.patch("sys.stderr", io.StringIO()), \
                    self.assertRaises(SystemExit) as e:
                run("mois", "--precedent", bad)
            self.assertEqual(e.exception.code, 2)

    def test_failure_exit_1(self):
        from ccs_app import monthly_report as mr
        err = io.StringIO()
        with mock.patch("sys.stderr", err), mock.patch.object(mr, "build_report", side_effect=OSError("x")):
            self.assertEqual(run("mois")[0], 1)
        self.assertIn("Rapport impossible", err.getvalue())


class MiseAJourCliTest(HomeTestCase):
    """Jamais de réseau ni d'installation : `installer.command` est simulé."""

    def test_check_only(self):
        from ccs_app import installer
        with mock.patch.object(installer, "command", return_value=(0, "CCS 9.9.9 est disponible.")) as c:
            self.assertEqual(run("mise-a-jour", "--verifier"), (0, "CCS 9.9.9 est disponible.\n"))
            self.assertEqual(c.call_args.args[0], ["--verifier"])
            self.assertEqual(run("maj")[0], 0)
            self.assertEqual(c.call_args.args[0], [])

    def test_progress_is_printed_and_failure_goes_to_stderr(self):
        from ccs_app import installer

        def fake(args, out=print, **_):
            out("Téléchargement…")
            return 1, "Échec simulé"
        err = io.StringIO()
        with mock.patch.object(installer, "command", side_effect=fake), mock.patch("sys.stderr", err):
            code, out = run("mise-a-jour")
        self.assertEqual((code, out), (1, "Téléchargement…\n"))
        self.assertIn("Échec simulé", err.getvalue())

    def test_unknown_option_exit_2(self):
        with mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as e:
            run("mise-a-jour", "--force")
        self.assertEqual(e.exception.code, 2)
