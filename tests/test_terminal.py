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
