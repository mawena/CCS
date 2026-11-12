import os
import signal
from unittest import mock

from ccs_app import sessions, terminal
from ccs_app.sessions import Session
from ccs_app.terminal import TabState
from tests.helpers import HomeTestCase

WHICH = {"env": "/usr/bin/env", "bash": "/usr/bin/bash"}


def which(name, **_kw):
    return WHICH.get(name)


class LaunchTestCase(HomeTestCase):
    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.object(terminal.shutil, "which", side_effect=which),
                        mock.patch.object(sessions, "_claude_bin", return_value="/home/u/.local/bin/claude")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.environ = {"HOME": str(self.home), "PATH": "/usr/bin:/bin", "SHELL": "/usr/bin/zsh",
                        "LANG": "fr_FR.UTF-8"}


class ClaudeLaunchTest(LaunchTestCase):
    def test_new_session_runs_claude_through_login_bash(self):
        launch = terminal.claude_launch("/home/u/Work/App", environ=self.environ)
        self.assertEqual(launch.kind, "claude")
        self.assertEqual(launch.cwd, "/home/u/Work/App")
        self.assertEqual(launch.argv, ("/usr/bin/bash", "-lc", "exec /home/u/.local/bin/claude"))
        self.assertIsNone(launch.session_id)
        self.assertEqual(launch.title, "App")

    def test_resume_quotes_the_identifier_and_keeps_it(self):
        launch = terminal.claude_launch("/w/App", resume="abc 1", title="Export CSV", environ=self.environ)
        self.assertEqual(launch.argv[-1], "exec /home/u/.local/bin/claude --resume 'abc 1'")
        self.assertEqual((launch.session_id, launch.title), ("abc 1", "Export CSV"))

    def test_environment_colors_and_local_bin_in_path(self):
        env = terminal.claude_launch("/w/App", environ=self.environ).env
        self.assertEqual(env["TERM"], "xterm-256color")
        self.assertEqual(env["COLORTERM"], "truecolor")
        self.assertEqual(env["PATH"], f"{self.home}/.local/bin:/usr/bin:/bin")
        self.environ["PATH"] = f"/usr/bin:{self.home}/.local/bin"
        env = terminal.claude_launch("/w/App", environ=self.environ).env
        self.assertEqual(env["PATH"], f"/usr/bin:{self.home}/.local/bin")  # déjà présent : inchangé

    def test_envv_is_a_list_of_assignments(self):
        launch = terminal.claude_launch("/w/App", environ=self.environ)
        self.assertIn("TERM=xterm-256color", launch.envv())
        self.assertTrue(all("=" in item and not item.startswith("=") for item in launch.envv()))

    def test_session_variables_of_a_parent_claude_are_removed(self):
        self.environ.update(CLAUDECODE="1", CLAUDE_CODE_ENTRYPOINT="cli", CLAUDE_CODE_SSE_PORT="1234",
                            CLAUDE_CONFIG_DIR="/home/u/.claude")
        launch = terminal.claude_launch("/w/App", environ=self.environ)
        self.assertEqual(launch.argv[:7], ("/usr/bin/env", "-u", "CLAUDECODE", "-u", "CLAUDE_CODE_ENTRYPOINT",
                                           "-u", "CLAUDE_CODE_SSE_PORT"))
        self.assertEqual(launch.argv[7:9], ("/usr/bin/bash", "-lc"))
        self.assertNotIn("CLAUDE_CONFIG_DIR", " ".join(launch.argv))  # réglage de l'utilisateur gardé
        self.assertNotIn("CLAUDECODE", launch.env)

    def test_missing_tools_fall_back_to_standard_paths(self):
        WHICH.clear()
        self.addCleanup(WHICH.update, {"env": "/usr/bin/env", "bash": "/usr/bin/bash"})
        self.environ["CLAUDECODE"] = "1"
        argv = terminal.claude_launch("/w/App", environ=self.environ).argv
        self.assertEqual((argv[0], argv[3]), ("/usr/bin/env", "/bin/bash"))

    def test_home_project_title(self):
        self.assertEqual(terminal.claude_launch(str(self.home), environ=self.environ).title, "~")

    def test_extra_arguments_after_claude_and_resume_quoted(self):
        launch = terminal.claude_launch("/w/App", environ=self.environ,
                                        extra_args=("--model", "opus", "--append-system-prompt", "a b'c"))
        self.assertEqual(launch.argv[-1], "exec /home/u/.local/bin/claude --model opus "
                                          "--append-system-prompt 'a b'\"'\"'c'")
        self.assertEqual(launch.extra_args, ("--model", "opus", "--append-system-prompt", "a b'c"))
        launch = terminal.claude_launch("/w/App", resume="s-1", environ=self.environ,
                                        extra_args=["--permission-mode", "plan"])
        self.assertEqual(launch.argv[-1], "exec /home/u/.local/bin/claude --resume s-1 --permission-mode plan")
        self.assertEqual(launch.extra_args, ("--permission-mode", "plan"))  # tuple : Launch reste figé
        self.assertEqual(terminal.claude_launch("/w/App", environ=self.environ).extra_args, ())

    def test_relaunch_keeps_extra_arguments(self):
        tab = TabState(kind="claude", cwd="/w/App", title="Plan", session_id="s-1",
                       extra_args=("--model", "opus", "--permission-mode", "plan"))
        again = terminal.relaunch(tab, environ=self.environ)
        self.assertEqual(again.argv[-1], "exec /home/u/.local/bin/claude --resume s-1 --model opus "
                                         "--permission-mode plan")
        self.assertEqual(again.extra_args, tab.extra_args)
        tab.session_id = None
        self.assertEqual(terminal.relaunch(tab, environ=self.environ).argv[-1],
                         "exec /home/u/.local/bin/claude --model opus --permission-mode plan")


class ShellLaunchTest(LaunchTestCase):
    def test_user_shell_in_folder(self):
        launch = terminal.shell_launch("/w/App", environ=self.environ)
        self.assertEqual((launch.kind, launch.cwd, launch.argv), ("shell", "/w/App", ("/usr/bin/zsh",)))
        self.assertEqual(launch.title, "Terminal · App")
        self.assertEqual(launch.env["TERM"], "xterm-256color")

    def test_shell_from_password_database_without_shell_variable(self):
        del self.environ["SHELL"]
        with mock.patch.object(terminal.pwd, "getpwuid", return_value=mock.Mock(pw_shell="/bin/fish")):
            self.assertEqual(terminal.shell_launch("/w", environ=self.environ).argv, ("/bin/fish",))
        with mock.patch.object(terminal.pwd, "getpwuid", side_effect=KeyError):
            self.assertEqual(terminal.shell_launch("/w", environ=self.environ).argv, ("/bin/bash",))

    def test_relaunch_after_exit(self):
        tab = TabState(kind="claude", cwd="/w/App", title="Export", session_id="s-1")
        again = terminal.relaunch(tab, environ=self.environ)
        self.assertEqual((again.kind, again.session_id, again.title), ("claude", "s-1", "Export"))
        self.assertIn("--resume s-1", again.argv[-1])
        new = terminal.relaunch(TabState(kind="claude", cwd="/w/App", title="App"), environ=self.environ)
        self.assertNotIn("--resume", new.argv[-1])  # identifiant jamais connu : nouvelle session
        shell = terminal.relaunch(TabState(kind="shell", cwd="/w", title="Terminal · w"), environ=self.environ)
        self.assertEqual(shell.argv, ("/usr/bin/zsh",))


class ChoiceTest(HomeTestCase):
    def test_embedded_only_when_vte_is_there_and_not_refused(self):
        self.assertEqual(terminal.choose(vte_ready=True), "integre")
        self.assertEqual(terminal.choose(vte_ready=True, external=True), "externe")
        self.assertEqual(terminal.choose(vte_ready=False), "externe")
        self.assertEqual(terminal.choose(vte_ready=False, external=True), "externe")

    def test_disabled_by_environment(self):
        self.assertFalse(terminal.embedded_disabled({}))
        self.assertTrue(terminal.embedded_disabled({"CCS_NO_VTE": "1"}))
        self.assertFalse(terminal.embedded_disabled({"CCS_NO_VTE": ""}))

    def test_install_hint_names_the_package(self):
        self.assertIn("sudo apt install gir1.2-vte-3.91", terminal.VTE_HINT)


class ExitTextTest(HomeTestCase):
    def test_exit_codes_and_signals(self):
        self.assertEqual(terminal.exit_text("claude", 0), "Claude Code s'est arrêté.")
        self.assertEqual(terminal.exit_text("claude", 3 << 8), "Claude Code s'est arrêté (code 3).")
        self.assertEqual(terminal.exit_text("shell", signal.SIGHUP),
                         f"Le terminal s'est fermé (signal {signal.SIGHUP}).")
        self.assertEqual(terminal.exit_text("shell", 0), "Le terminal s'est fermé.")
        self.assertEqual(terminal.exit_text("claude", -1), "Claude Code s'est arrêté.")  # statut illisible

    def test_relaunch_label(self):
        self.assertEqual(terminal.relaunch_label(TabState("claude", "/w", "x", session_id="s")), "Reprendre")
        self.assertEqual(terminal.relaunch_label(TabState("claude", "/w", "x")), "Relancer")
        self.assertEqual(terminal.relaunch_label(TabState("shell", "/w", "x")), "Relancer")


def live(pid, state, sid="s-1", name="app"):
    return Session(pid, sid, name, "/w/App", "App", state, None, 0.0, 0.0, "interactive", "cli")


class TabStateTest(HomeTestCase):
    def tab(self, **kw):
        return TabState(**{"kind": "claude", "cwd": "/w/App", "title": "App", "pid": 10, "running": True, **kw})

    def test_find_by_pid_or_conversation(self):
        a, b = self.tab(pid=10, session_id="s-a"), self.tab(pid=11, session_id="s-b", running=False)
        tabs = [a, b]
        self.assertIs(terminal.find_tab(tabs, pid=11), b)
        self.assertIs(terminal.find_tab(tabs, session_id="s-a"), a)
        self.assertIs(terminal.find_tab(tabs, session_id="s-b"), b)  # même arrêté : l'onglet est là
        self.assertIsNone(terminal.find_tab(tabs, pid=99))
        self.assertIsNone(terminal.find_tab(tabs))
        shell = TabState("shell", "/w", "Terminal · w", pid=12, running=True)
        self.assertIsNone(terminal.find_tab([shell], session_id=None))

    def test_sync_learns_session_id_and_state_by_pid(self):
        a, b = self.tab(pid=10), self.tab(pid=11, state="busy")
        done = terminal.sync_tabs([a, b], [live(10, "idle", sid="s-new"), live(11, "waiting", sid="s-b")])
        self.assertEqual((a.session_id, a.state), ("s-new", "idle"))
        self.assertEqual((b.session_id, b.state), ("s-b", "waiting"))
        self.assertEqual(done, [b])  # a travaillé puis s'est arrêté de travailler

    def test_sync_ignores_stopped_tabs_and_shells_and_follows_resume(self):
        stopped = self.tab(pid=10, running=False, session_id="old", state="busy")
        shell = TabState("shell", "/w", "t", pid=11, running=True)
        same = self.tab(pid=12, session_id="first", state="idle")
        terminal.sync_tabs([stopped, shell, same], [live(10, "idle", "x"), live(11, "busy", "y"),
                                                    live(12, "busy", "second")])
        self.assertEqual((stopped.session_id, stopped.state), ("old", "busy"))
        self.assertIsNone(shell.session_id)
        self.assertEqual((same.session_id, same.state), ("second", "busy"))  # /resume dans claude

    def test_sync_session_not_listed_yet(self):
        a = self.tab(pid=10, state="busy")
        self.assertEqual(terminal.sync_tabs([a], []), [])
        self.assertEqual(a.state, "busy")

    def test_indicator(self):
        self.assertEqual(terminal.indicator(self.tab(state="busy")), (True, None, "travaille"))
        self.assertEqual(terminal.indicator(self.tab(state="waiting")),
                         (False, "dialog-question-symbolic", "attend ta réponse"))
        self.assertEqual(terminal.indicator(self.tab(state="idle")), (False, None, "au repos"))
        self.assertEqual(terminal.indicator(self.tab(state=None)), (False, None, None))
        self.assertEqual(terminal.indicator(self.tab(running=False, state="busy")),
                         (False, "media-playback-stop-symbolic", "arrêtée"))

    def test_close_question_for_the_window(self):
        tabs = [self.tab(), self.tab(running=False), TabState("shell", "/w", "t", running=True)]
        self.assertEqual(terminal.running_claude(tabs), 1)
        heading, body = terminal.close_question(tabs)
        self.assertEqual(heading, "Fermer la fenêtre ?")
        self.assertEqual(body, "Une session Claude Code tourne encore dans l'application. "
                               "La conversation est enregistrée : tu pourras la reprendre.")
        tabs.append(self.tab())
        _, body = terminal.close_question(tabs)
        self.assertEqual(body, "2 sessions Claude Code tournent encore dans l'application. "
                               "Les conversations sont enregistrées : tu pourras les reprendre.")
        busy_shell = TabState("shell", "/w", "t", running=True, busy=True)
        _, body = terminal.close_question([busy_shell])
        self.assertEqual(body, "Un programme tourne encore dans un terminal de l'application : il sera arrêté.")
        _, body = terminal.close_question([self.tab(), busy_shell])
        self.assertTrue(body.startswith("Une session Claude Code tourne") and "il sera arrêté" in body)

    def test_nothing_to_confirm(self):
        idle_shell = TabState("shell", "/w", "t", running=True)
        self.assertIsNone(terminal.close_question([self.tab(running=False), idle_shell]))
        self.assertIsNone(terminal.close_question([]))
        self.assertIsNone(terminal.tab_close_question(self.tab(running=False)))
        self.assertIsNone(terminal.tab_close_question(idle_shell))

    def test_tab_close_question(self):
        heading, body = terminal.tab_close_question(self.tab(title="Export CSV"))
        self.assertEqual(heading, "Fermer « Export CSV » ?")
        self.assertEqual(body, "Claude Code sera arrêté. La conversation est enregistrée : tu pourras la reprendre.")
        shell = TabState("shell", "/w", "Terminal · w", running=True, busy=True)
        self.assertEqual(terminal.tab_close_question(shell),
                         ("Fermer « Terminal · w » ?", "Le programme en cours sera arrêté."))


class EnvironTest(HomeTestCase):
    def test_defaults_to_process_environment(self):
        with mock.patch.dict(os.environ, {"PATH": "/opt/bin"}), \
                mock.patch.object(sessions, "_claude_bin", return_value="claude"):
            env = terminal.claude_launch("/w").env
        self.assertEqual(env["PATH"], f"{self.home}/.local/bin:/opt/bin")


def live_at(pid, state, since, sid="s-1", waiting_for=None):
    return Session(pid, sid, "app", "/w/App", "App", state, waiting_for, 0.0, since, "interactive", "cli")


class SyncTurnTest(HomeTestCase):
    def tab(self, **kw):
        return TabState(**{"kind": "claude", "cwd": "/w/App", "title": "App", "pid": 10, "running": True, **kw})

    def test_busy_start_comes_from_the_session_record(self):
        a = self.tab(state="idle")
        terminal.sync_tabs([a], [live_at(10, "busy", 500.0)], now=600.0)
        self.assertEqual(a.busy_since, 500.0)
        terminal.sync_tabs([a], [live_at(10, "idle", 700.0)], now=800.0)
        self.assertEqual(a.busy_since, 500.0)  # gardé : début du dernier tour

    def test_busy_start_without_date_is_the_first_time_it_was_seen(self):
        a = self.tab(state="idle")
        terminal.sync_tabs([a], [live_at(10, "busy", 0.0)], now=600.0)
        terminal.sync_tabs([a], [live_at(10, "busy", 0.0)], now=603.0)
        self.assertEqual(a.busy_since, 600.0)

    def test_waiting_reason_is_kept(self):
        a = self.tab()
        terminal.sync_tabs([a], [live_at(10, "waiting", 1.0, waiting_for="input needed")], now=2.0)
        self.assertEqual((a.state, a.waiting_for), ("waiting", "input needed"))
        terminal.sync_tabs([a], [live_at(10, "idle", 3.0)], now=4.0)
        self.assertIsNone(a.waiting_for)


class ResumeDecisionTest(HomeTestCase):
    NOW = 10_000.0

    def tab(self, **kw):
        return TabState(**{"kind": "claude", "cwd": "/w/App", "title": "App", "pid": 10, "running": True,
                           "session_id": "s-1", "state": "idle", "started_at": self.NOW - 3600, **kw})

    def event(self, **kw):
        from ccs_app.limit_events import LimitEvent
        return LimitEvent(**{"session_id": "s-1", "ts": self.NOW - 20, "source": "perso", "target": "pro",
                             "switched": True, "outcome": "switched", **kw})

    def decide(self, tab=None, event=None, **kw):
        return terminal.resume_decision(tab or self.tab(), event or self.event(), self.NOW, **kw)

    def test_switched_and_idle_resumes_with_a_banner(self):
        d = self.decide()
        self.assertEqual(d.action, "resume")
        self.assertEqual(d.text, "Limite atteinte sur perso : bascule sur pro, conversation relancée.")
        self.assertEqual(terminal.RESUME_TEXT, "continue")

    def test_already_switched_by_someone_else_resumes_too(self):
        self.assertEqual(self.decide(event=self.event(outcome="already")).action, "resume")

    def test_not_for_another_conversation_or_a_shell(self):
        self.assertIsNone(terminal.resume_decision(self.tab(), None, self.NOW))
        self.assertIsNone(self.decide(event=self.event(session_id="s-2")))
        self.assertIsNone(self.decide(tab=self.tab(session_id=None)))
        self.assertIsNone(self.decide(tab=TabState("shell", "/w", "t", pid=3, running=True)))

    def test_waits_while_the_hook_decides_or_claude_still_works(self):
        self.assertEqual(self.decide(event=self.event(outcome="pending", switched=False)).action, "wait")
        self.assertEqual(self.decide(tab=self.tab(state="busy")).action, "wait")
        self.assertEqual(self.decide(tab=self.tab(state=None)).action, "wait")

    def test_never_types_into_a_permission_prompt(self):
        tab = self.tab(state="waiting", waiting_for="permission to run Bash")
        self.assertEqual(self.decide(tab=tab).action, "wait")
        self.assertEqual(self.decide(tab=self.tab(state="waiting")).action, "wait")
        tab = self.tab(state="waiting", waiting_for="input needed")
        self.assertEqual(self.decide(tab=tab).action, "resume")

    def test_failed_or_impossible_switch_only_explains(self):
        d = self.decide(event=self.event(switched=False, outcome="failed"))
        self.assertEqual(d.action, "drop")
        self.assertEqual(d.text, "Limite atteinte sur perso : bascule vers pro impossible, "
                                 "pas de reprise automatique.")
        d = self.decide(event=self.event(switched=False, target=None, outcome="exhausted"))
        self.assertEqual(d.text, "Limite atteinte sur perso : aucun autre compte disponible, "
                                 "pas de reprise automatique.")

    def test_pause_never_resumes(self):
        d = self.decide(event=self.event(switched=False, target=None, outcome="paused"))
        self.assertEqual(d.action, "drop")
        self.assertEqual(d.text, "Limite atteinte sur perso : CCS est en pause, "
                                 "pas de bascule ni de reprise automatique.")
        d = self.decide(event=self.event(switched=True, outcome="paused"))  # marqueur incohérent
        self.assertEqual(d.action, "drop")

    def test_user_typed_since_the_limit(self):
        d = self.decide(tab=self.tab(typed_at=self.NOW - 5))
        self.assertEqual(d.action, "drop")
        self.assertEqual(d.text, "Limite atteinte sur perso : bascule sur pro. "
                                 "Pas de reprise automatique : tu as écrit dans la session.")
        self.assertEqual(self.decide(tab=self.tab(typed_at=self.NOW - 60)).action, "resume")  # avant

    def test_disabled_only_explains(self):
        d = self.decide(enabled=False)
        self.assertEqual(d.action, "drop")
        self.assertEqual(d.text, "Limite atteinte sur perso : bascule sur pro. Tape « continue » pour reprendre.")

    def test_stale_or_stopped_or_older_than_the_tab_is_dropped_silently(self):
        old = self.event(ts=self.NOW - terminal.RESUME_MAX_AGE_S - 1)
        self.assertEqual(self.decide(event=old), terminal.ResumeDecision("drop"))
        self.assertEqual(self.decide(tab=self.tab(running=False)), terminal.ResumeDecision("drop"))
        tab = self.tab(started_at=self.NOW - 10)   # onglet (re)lancé après la limite
        self.assertEqual(self.decide(tab=tab), terminal.ResumeDecision("drop"))

    def test_loop_guard_per_hour(self):
        tab = self.tab(resumes=[self.NOW - 3000, self.NOW - 2000, self.NOW - 1000])
        d = self.decide(tab=tab)
        self.assertEqual(d.action, "drop")
        self.assertEqual(d.text, "Limite atteinte sur perso : bascule sur pro. Reprise automatique "
                                 "suspendue (3 reprises en une heure) : tape « continue » pour reprendre.")
        tab = self.tab(resumes=[self.NOW - 4000, self.NOW - 2000, self.NOW - 1000])  # une hors de l'heure
        self.assertEqual(self.decide(tab=tab).action, "resume")
        self.assertEqual(self.decide(tab=tab, max_per_hour=2).action, "drop")

    def test_loop_guard_when_the_previous_resume_is_too_recent(self):
        tab = self.tab(resumes=[self.NOW - 60])
        d = self.decide(tab=tab)
        self.assertEqual(d.action, "drop")
        self.assertEqual(d.text, "Limite atteinte sur perso : bascule sur pro. Reprise automatique "
                                 "suspendue (la précédente date de moins de 2 min) : tape « continue » "
                                 "pour reprendre.")

    def test_unknown_account_names(self):
        d = self.decide(event=self.event(source=None, target=None))
        self.assertEqual(d.text, "Limite atteinte : bascule sur un autre compte, conversation relancée.")


def record(**kw):
    return {"kind": "claude", "cwd": "/w/App", "title": "App", "session_id": "s-1", "extra_args": [],
            "queue": [], **kw}


class RestoreTest(HomeTestCase):
    def test_tab_record(self):
        tab = TabState("claude", "/w/App", "Export", session_id="s-1", running=True, pid=4,
                       extra_args=("--model", "opus"), queue=["lance les tests"])
        self.assertEqual(terminal.tab_record(tab), record(title="Export", extra_args=["--model", "opus"],
                                                          queue=["lance les tests"]))
        shell = TabState("shell", "/w", "Terminal · w", session_id="ignoré")
        self.assertEqual(terminal.tab_record(shell), {"kind": "shell", "cwd": "/w", "title": "Terminal · w",
                                                      "session_id": None, "extra_args": [], "queue": []})

    def plan(self, records, selected=None, **kw):
        kw.setdefault("folder_exists", lambda cwd: not cwd.startswith("/disparu"))
        kw.setdefault("conversation_exists", lambda cwd, sid: sid != "jamais-ecrite")
        return terminal.restore_plan(records, selected, **kw)

    def test_everything_reopens_in_order(self):
        shell = record(kind="shell", cwd="/w", title="Terminal · w", session_id=None)
        p = self.plan([record(extra_args=["--model", "opus"], queue=["a"]), shell], selected=1)
        self.assertEqual(p.tabs, [terminal.Reopen("claude", "/w/App", "App", "s-1", ("--model", "opus"), ("a",)),
                                  terminal.Reopen("shell", "/w", "Terminal · w", None, (), ())])
        self.assertEqual((p.selected, p.skipped), (1, []))

    def test_skips_missing_folder_open_elsewhere_or_in_a_tab_and_duplicates(self):
        records = [record(cwd="/disparu/App", session_id="a", title="A"),
                   record(session_id="b", title="B"), record(session_id="c", title="C"),
                   record(session_id="d", title="D"), record(session_id="d", title="D bis")]
        p = self.plan(records, selected=3, opened={"b"}, present={"c"})
        self.assertEqual([t.session_id for t in p.tabs], ["d"])
        self.assertEqual(p.selected, 0)
        self.assertEqual(p.skipped, [("A", "dossier introuvable : /disparu/App"),
                                     ("B", "déjà ouverte dans une session Claude Code"),
                                     ("C", "déjà ouverte dans un onglet"),
                                     ("D bis", "en double")])

    def test_selected_tab_skipped(self):
        p = self.plan([record(session_id="a"), record(session_id="b")], selected=1, opened={"b"})
        self.assertIsNone(p.selected)

    def test_conversation_never_written_starts_a_new_session(self):
        p = self.plan([record(session_id="jamais-ecrite"), record(session_id=None)])
        self.assertEqual([(t.kind, t.session_id) for t in p.tabs], [("claude", None), ("claude", None)])

    def test_launch_of_a_reopened_tab(self):
        with mock.patch.object(sessions, "_claude_bin", return_value="/u/claude"), \
                mock.patch.object(terminal.shutil, "which", side_effect=which):
            launch = terminal.Reopen("claude", "/w/App", "Export", "s-1", ("--model", "opus"), ()).launch({})
            self.assertEqual(launch.argv[-1], "exec /u/claude --resume s-1 --model opus")
            self.assertEqual((launch.title, launch.session_id), ("Export", "s-1"))
            shell = terminal.Reopen("shell", "/w", "Terminal · w", None, (), ()).launch({"SHELL": "/bin/zsh"})
            self.assertEqual(shell.argv, ("/bin/zsh",))
            untitled = terminal.Reopen("claude", "/w/App", "", None, (), ()).launch({})
            self.assertEqual(untitled.title, "App")

    def test_question_and_summary(self):
        self.assertEqual(terminal.restore_question(1), "Rouvrir la session de la dernière fois ?")
        self.assertEqual(terminal.restore_question(3), "Rouvrir les 3 sessions de la dernière fois ?")
        self.assertEqual(terminal.restore_summary(2, []), "2 onglets rouverts")
        self.assertEqual(terminal.restore_summary(1, [("B", "déjà ouverte dans une session Claude Code")]),
                         "1 onglet rouvert ; « B » non rouvert : déjà ouverte dans une session Claude Code")
        self.assertEqual(terminal.restore_summary(0, [("A", "x"), ("B", "y")]),
                         "Aucun onglet rouvert ; 2 non rouverts (dossier disparu ou conversation déjà ouverte)")

    def test_merge_keeps_unanswered_tabs_before_the_current_ones(self):
        pending = [record(session_id="a"), record(session_id="b"), record(kind="shell", session_id=None)]
        current = [record(session_id="b", title="B ouvert"), record(session_id="z")]
        merged, selected = terminal.merge_records(pending, 0, current, 1)
        self.assertEqual([r["session_id"] for r in merged], ["a", None, "b", "z"])
        self.assertEqual(selected, 3)
        merged, selected = terminal.merge_records(pending, 1, [], None)
        self.assertEqual((len(merged), selected), (3, 1))
        merged, selected = terminal.merge_records(pending, 1, current, None)
        self.assertIsNone(selected)  # « b » est maintenant un onglet ouvert


class MessageQueueTest(HomeTestCase):
    def test_clean_message(self):
        self.assertEqual(terminal.clean_message("  lance les tests \n"), "lance les tests")
        self.assertEqual(terminal.clean_message("a\r\nb\nc"), "a b c")
        self.assertIsNone(terminal.clean_message(" \n "))
        self.assertIsNone(terminal.clean_message(None))

    def test_add_edit_remove_move(self):
        q = terminal.queue_add([], "un")
        q = terminal.queue_add(q, "deux\n")
        q = terminal.queue_add(q, "   ")
        self.assertEqual(q, ["un", "deux"])
        self.assertEqual(terminal.queue_edit(q, 1, "deux bis"), ["un", "deux bis"])
        self.assertEqual(terminal.queue_edit(q, 0, ""), ["deux"])       # vidé : retiré
        self.assertEqual(terminal.queue_edit(q, 5, "x"), q)             # hors de la file
        self.assertEqual(terminal.queue_remove(q, 0), ["deux"])
        self.assertEqual(terminal.queue_remove(q, 9), q)
        self.assertEqual(terminal.queue_move(["a", "b", "c"], 2, -1), ["a", "c", "b"])
        self.assertEqual(terminal.queue_move(["a", "b", "c"], 0, -1), ["a", "b", "c"])
        self.assertEqual(terminal.queue_move(["a", "b", "c"], 2, 1), ["a", "b", "c"])
        self.assertEqual(q, ["un", "deux"])  # jamais modifiée sur place


class QueueDecisionTest(HomeTestCase):
    NOW = 50_000.0

    def tab(self, **kw):
        base = {"kind": "claude", "cwd": "/w/App", "title": "App", "pid": 10, "running": True,
                "session_id": "s-1", "state": "idle", "state_since": self.NOW - 10,
                "busy_since": self.NOW - 60, "queue": ["premier", "second"]}
        return TabState(**{**base, **kw})

    def next(self, tab, **kw):
        return terminal.queue_next(tab, self.NOW, **kw)

    def test_turn_finished_sends_the_first_message(self):
        self.assertEqual(self.next(self.tab()), terminal.QueueDecision("premier", None))

    def test_nothing_queued_or_not_claude(self):
        self.assertEqual(self.next(self.tab(queue=[])), terminal.QueueDecision(None, None))
        shell = TabState("shell", "/w", "t", running=True, queue=["x"])
        self.assertEqual(self.next(shell), terminal.QueueDecision(None, None))

    def test_never_while_working_or_waiting_for_a_permission(self):
        d = self.next(self.tab(state="busy"))
        self.assertEqual(d, terminal.QueueDecision(None, "Claude travaille : envoi à la fin du tour."))
        d = self.next(self.tab(state="waiting", waiting_for="permission to run Bash"))
        self.assertEqual(d, terminal.QueueDecision(None, "Claude attend ta réponse : rien n'est envoyé."))
        self.assertEqual(self.next(self.tab(state="waiting", waiting_for="input needed")).text, "premier")
        self.assertIsNone(self.next(self.tab(state=None)).text)

    def test_stopped_session(self):
        self.assertEqual(self.next(self.tab(running=False)).reason, "Session arrêtée.")

    def test_turn_just_finished_waits_a_moment(self):
        d = self.next(self.tab(state_since=self.NOW - 1))
        self.assertEqual(d, terminal.QueueDecision(None, None))

    def test_one_message_per_turn(self):
        tab = self.tab(sent_at=self.NOW - 5)            # envoyé, claude n'a pas encore travaillé
        self.assertEqual(self.next(tab).reason, "Envoi précédent en cours.")
        tab = self.tab(sent_at=self.NOW - 5, busy_since=self.NOW - 4)   # tour suivant terminé
        self.assertEqual(self.next(tab).text, "premier")
        tab = self.tab(sent_at=self.NOW - terminal.QUEUE_STALL_S - 1)  # aucun tour observé
        self.assertEqual(self.next(tab).text, "premier")

    def test_turn_date_truncated_to_the_millisecond(self):
        # Claude Code date ses changements d'état à la milliseconde : un tour lancé dans la
        # même milliseconde que l'envoi paraît commencer juste avant lui.
        tab = self.tab(sent_at=self.NOW - 5.0004, busy_since=self.NOW - 5.001)
        self.assertEqual(self.next(tab).text, "premier")
        # Entrée tapée par l'utilisateur (sa demande) dans la milliseconde du début du tour.
        tab = self.tab(typed_at=self.NOW - 59.9996, busy_since=self.NOW - 60.0)
        self.assertEqual(self.next(tab).text, "premier")

    def test_user_typed_in_the_session(self):
        d = self.next(self.tab(typed_at=self.NOW - 30))  # après le début du dernier tour
        self.assertEqual(d.reason, "Tu as écrit dans la session : envoi à la fin du prochain tour.")
        self.assertEqual(self.next(self.tab(typed_at=self.NOW - 90)).text, "premier")  # avant le tour

    def test_added_while_claude_is_free(self):
        tab = self.tab(busy_since=None, queued_at=self.NOW - 5)
        self.assertEqual(self.next(tab).text, "premier")
        tab = self.tab(busy_since=self.NOW - 60, sent_at=self.NOW - 50, queued_at=self.NOW - 5)
        self.assertEqual(self.next(tab).text, "premier")

    def test_restored_queue_waits_for_a_turn(self):
        tab = self.tab(busy_since=None, queued_at=None)
        self.assertEqual(self.next(tab).reason, "Envoi à la fin du prochain tour de Claude.")

    def test_limit_blocks_until_a_new_turn(self):
        d = self.next(self.tab(), blocked=True)
        self.assertEqual(d.reason, "Session bloquée par une limite : envoi après la reprise.")
        d = self.next(self.tab(limit_at=self.NOW - 20))
        self.assertEqual(d.reason, "Session bloquée par une limite : envoi après la reprise.")
        self.assertEqual(self.next(self.tab(limit_at=self.NOW - 70)).text, "premier")  # tour depuis

    def test_sync_records_when_the_state_changed(self):
        tab = TabState("claude", "/w/App", "App", pid=10, running=True, state="busy", state_since=1.0)
        terminal.sync_tabs([tab], [live_at(10, "busy", 0.0)], now=5.0)
        self.assertEqual(tab.state_since, 1.0)
        terminal.sync_tabs([tab], [live_at(10, "idle", 7.0)], now=8.0)
        self.assertEqual(tab.state_since, 7.0)
        terminal.sync_tabs([tab], [live_at(10, "busy", 0.0)], now=9.0)
        self.assertEqual(tab.state_since, 9.0)


class ChatTabsTest(HomeTestCase):
    """Onglets de chat : état tenu par le moteur, fermeture, réouverture, autres processus."""

    def chat(self, **kw):
        kw.setdefault("running", True)
        return TabState("claude", "/w/App", "App", session_id="s-1", pid=7, chat=True, **kw)

    def test_sync_tabs_leaves_chats_alone(self):
        tab = self.chat(state="idle", state_since=1.0)
        done = terminal.sync_tabs([tab], [live_at(7, "busy", 5.0)], now=9.0)
        self.assertEqual((tab.state, tab.state_since, done), ("idle", 1.0, []))

    def test_idle_chat_closes_without_question(self):
        self.assertFalse(terminal.needs_confirm(self.chat(state="idle")))
        self.assertFalse(terminal.needs_confirm(self.chat(state="waiting", waiting_for="input")))
        self.assertIsNone(terminal.tab_close_question(self.chat(state="idle")))
        self.assertIsNone(terminal.close_question([self.chat(state="idle")]))

    def test_busy_or_permission_chat_asks_before_closing(self):
        self.assertTrue(terminal.needs_confirm(self.chat(state="busy")))
        self.assertTrue(terminal.needs_confirm(self.chat(state="waiting", waiting_for="permission")))
        title, _body = terminal.close_question([self.chat(state="busy"), self.chat(state="idle")])
        self.assertEqual(title, "Fermer la fenêtre ?")

    def test_terminal_claude_still_asks_when_idle(self):
        tab = TabState("claude", "/w/App", "App", running=True, state="idle")
        self.assertTrue(terminal.needs_confirm(tab))

    def test_chat_without_process_is_not_shown_as_stopped(self):
        tab = TabState("claude", "/w/App", "App", session_id="s-1", chat=True)
        self.assertEqual(terminal.indicator(tab), (False, None, None))
        tab.exit_status = 1
        self.assertEqual(terminal.indicator(tab), terminal.STOPPED)

    def test_queue_goes_to_a_chat_without_process(self):
        tab = TabState("claude", "/w/App", "App", session_id="s-1", chat=True, queue=["un"],
                       queued_at=10.0)
        self.assertEqual(terminal.queue_next(tab, 100.0).text, "un")
        tab.chat = False
        self.assertEqual(terminal.queue_next(tab, 100.0).reason, "Session arrêtée.")

    def test_record_carries_chat_options(self):
        chat = {"model": "opus", "effort": None, "ultracode": False, "rights": "plan"}
        self.assertEqual(terminal.tab_record(self.chat(), chat=chat)["chat"], chat)
        self.assertNotIn("chat", terminal.tab_record(self.chat()))
        shell = TabState("shell", "/w", "Terminal · w")
        self.assertNotIn("chat", terminal.tab_record(shell, chat=chat))

    def test_restore_plan_keeps_chat_options(self):
        chat = {"model": "opus", "effort": "high", "ultracode": False, "rights": None}
        p = terminal.restore_plan([record(chat=chat), record(session_id=None, kind="shell")],
                                  folder_exists=lambda c: True, conversation_exists=lambda c, s: True)
        self.assertEqual(p.tabs[0].chat, chat)
        self.assertIsNone(p.tabs[1].chat)

    def test_elsewhere_pid(self):
        live = [live_at(50, "idle", 1.0), live_at(60, "busy", 1.0)]
        live[0].session_id, live[1].session_id = "s-1", "s-2"
        self.assertEqual(terminal.elsewhere_pid("s-1", live), 50)
        self.assertIsNone(terminal.elsewhere_pid("s-1", live, own_pids={50}))
        self.assertIsNone(terminal.elsewhere_pid("s-3", live))
        self.assertIsNone(terminal.elsewhere_pid(None, live))

    def test_waiting_alert_key_is_per_wait(self):
        tab = self.chat(state="waiting", state_since=100.4)
        first = terminal.waiting_alert_key(tab)
        tab.state_since = 200.0
        self.assertNotEqual(first, terminal.waiting_alert_key(tab))
        self.assertTrue(terminal.is_waiting_for_user(tab))
        tab.state = "idle"
        self.assertFalse(terminal.is_waiting_for_user(tab))
