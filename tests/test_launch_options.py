import shlex
import unittest
from unittest import mock

from ccs_app import launch_options as lo
from ccs_app import switch_log
from ccs_app.launch_options import LaunchSpec, claude_args
from ccs_app.store import Store
from tests.helpers import HomeTestCase


class ClaudeArgsTest(unittest.TestCase):
    def test_no_option_gives_no_argument(self):
        self.assertEqual(claude_args(), [])
        self.assertEqual(claude_args(model="", permission_mode=""), [])

    def test_model_alias_and_full_name(self):
        self.assertEqual(claude_args(model="opus"), ["--model", "opus"])
        self.assertEqual(claude_args(model="sonnet"), ["--model", "sonnet"])
        self.assertEqual(claude_args(model="haiku"), ["--model", "haiku"])
        self.assertEqual(claude_args(model="claude-opus-5-5"), ["--model", "claude-opus-5-5"])
        self.assertEqual(claude_args(model="claude-opus-5-5[1m]"), ["--model", "claude-opus-5-5[1m]"])

    def test_default_model_words_mean_no_flag(self):
        for word in ("default", "défaut", "par défaut", "Par défaut"):
            self.assertEqual(claude_args(model=word), [], word)

    def test_invalid_model_is_refused(self):
        for bad in ("--dangerously-skip-permissions", "opus; rm -rf ~", "a b", "-x"):
            with self.assertRaises(ValueError, msg=bad):
                claude_args(model=bad)

    def test_permission_modes_match_claude_help(self):
        # Valeurs de « claude --help » (Claude Code 2.1.319).
        self.assertEqual(set(lo.PERMISSION_MODE_VALUES),
                         {"acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan"})
        for mode in lo.PERMISSION_MODE_VALUES:
            self.assertEqual(claude_args(permission_mode=mode), ["--permission-mode", mode])

    def test_unknown_permission_mode_is_refused(self):
        with self.assertRaises(ValueError):
            claude_args(permission_mode="yolo")

    def test_resume_and_extra_and_order(self):
        args = claude_args(model="sonnet", permission_mode="plan", resume="abcd-1234", extra=("--add-dir", "/tmp/x"))
        self.assertEqual(args, ["--model", "sonnet", "--permission-mode", "plan", "--resume", "abcd-1234",
                                "--add-dir", "/tmp/x"])

    def test_resume_that_looks_like_an_option_is_refused(self):
        with self.assertRaises(ValueError):
            claude_args(resume="--model")

    def test_extra_must_be_strings(self):
        with self.assertRaises(TypeError):
            claude_args(extra=("--add-dir", 3))


class ChoicesTest(unittest.TestCase):
    def test_models_offered(self):
        values = [v for _label, v in lo.MODELS]
        self.assertEqual(values[0], None)  # « par défaut » en premier
        for alias in ("opus", "sonnet", "haiku"):
            self.assertIn(alias, values)

    def test_permission_choices_cover_every_mode_once(self):
        values = [v for _label, v in lo.PERMISSION_MODES]
        self.assertEqual(values[0], None)
        self.assertEqual(sorted(v for v in values if v), sorted(lo.PERMISSION_MODE_VALUES))

    def test_labels(self):
        self.assertEqual(lo.model_label(None), "Par défaut")
        self.assertEqual(lo.model_label("opus"), "Opus")
        self.assertEqual(lo.model_label("claude-opus-5-5"), "claude-opus-5-5")
        self.assertIn("modifications", lo.permission_label("acceptEdits"))
        for value in [None, *lo.PERMISSION_MODE_VALUES]:
            self.assertTrue(lo.permission_help(value), value)
            self.assertLessEqual(len(lo.permission_label(value)), 30, value)  # tient dans la liste déroulante
        self.assertTrue(lo.is_dangerous("bypassPermissions"))
        self.assertFalse(lo.is_dangerous("plan"))


class LaunchSpecTest(unittest.TestCase):
    def test_args_and_switch(self):
        spec = LaunchSpec(cwd="/home/u/Work/App", profile="pro", model="opus", permission_mode="acceptEdits")
        self.assertEqual(spec.args(), ["--model", "opus", "--permission-mode", "acceptEdits"])
        self.assertEqual(spec.args(resume="s1"), ["--model", "opus", "--permission-mode", "acceptEdits",
                                                  "--resume", "s1"])
        self.assertTrue(spec.needs_switch("perso"))
        self.assertFalse(spec.needs_switch("pro"))
        self.assertFalse(LaunchSpec("/tmp", None).needs_switch("perso"))

    def test_spec_is_validated(self):
        with self.assertRaises(ValueError):
            LaunchSpec(cwd="/tmp", profile=None, permission_mode="nope")
        with self.assertRaises(ValueError):
            LaunchSpec(cwd="", profile=None)

    def test_shell_command_is_quoted(self):
        spec = LaunchSpec(cwd="/home/u/Mes projets/App", profile=None, model="sonnet")
        cmd = spec.shell_command(claude_bin="/home/u/.local/bin/claude")
        self.assertEqual(shlex.split(cmd), ["cd", "/home/u/Mes projets/App", "&&", "/home/u/.local/bin/claude",
                                            "--model", "sonnet"])

    def test_terminal_command(self):
        spec = LaunchSpec(cwd="/w", profile=None, permission_mode="plan")
        with mock.patch("shutil.which", side_effect=lambda name, **_: f"/usr/bin/{name}"):
            argv = lo.terminal_command(spec, claude_bin="/usr/bin/claude")
        self.assertEqual(argv[:4], ["/usr/bin/gnome-terminal", "--working-directory=/w", "--", "bash"])
        self.assertEqual(argv[4], "-lc")
        self.assertEqual(shlex.split(argv[5]), ["/usr/bin/claude", "--permission-mode", "plan"])

    def test_launch_starts_detached_terminal(self):
        spec = LaunchSpec(cwd="/w", profile=None)
        with mock.patch.object(lo, "terminal_command", return_value=["term", "x"]), \
                mock.patch("subprocess.Popen") as popen:
            lo.launch(spec)
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], ["term", "x"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])


class SwitchTest(HomeTestCase):
    """Bascule avant l'ouverture (faite hors de l'interface par l'application)."""

    def test_nothing_to_do_on_the_active_account(self):
        run = mock.Mock()
        for spec in (LaunchSpec(cwd="/w", profile=None), LaunchSpec(cwd="/w", profile="perso")):
            self.assertEqual(lo.switch_if_needed(spec, active="perso", run=run), (False, None))
        run.assert_not_called()

    def test_switch_then_ok(self):
        import subprocess
        run = mock.Mock(return_value=subprocess.CompletedProcess([], 0, "✔ basculé sur 'pro'", ""))
        self.assertEqual(lo.switch_if_needed(LaunchSpec(cwd="/w", profile="pro"), active="perso", run=run),
                         (True, None))
        run.assert_called_once_with(["use", "pro"])
        # Origine notée pour le journal des bascules (lue par le service).
        self.assertEqual(switch_log.take_origin("pro"), {"via": "nouvelle-session"})

    def test_origin_given_by_the_caller(self):
        import subprocess
        run = mock.Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
        lo.switch_if_needed(LaunchSpec(cwd="/w/App", profile="pro"), active="perso", run=run,
                            via="projet", project="/w/App")
        self.assertEqual(switch_log.take_origin("pro"), {"via": "projet", "project": "/w/App"})

    def test_origin_carried_by_the_spec(self):
        import subprocess
        run = mock.Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
        spec = LaunchSpec(cwd="/w/App/src", profile="pro", origin="projet")
        lo.switch_if_needed(spec, active="perso", run=run)
        self.assertEqual(switch_log.take_origin("pro"), {"via": "projet", "project": "/w/App/src"})
        with self.assertRaises(ValueError):
            LaunchSpec(cwd="/w", profile="pro", origin="ailleurs")

    def test_switch_failure_gives_the_reason(self):
        import subprocess
        run = mock.Mock(return_value=subprocess.CompletedProcess(
            [], 1, "", "\x1b[31mccs: 'pro' : connexion perdue, reconnecte ce compte\x1b[0m\n"))
        switched, error = lo.switch_if_needed(LaunchSpec(cwd="/w", profile="pro"), active="perso", run=run)
        self.assertFalse(switched)
        self.assertEqual(error, "'pro' : connexion perdue, reconnecte ce compte")
        self.assertIsNone(switch_log.take_origin("pro"))
        ev = Store().last_event("error", "pro")
        self.assertEqual(ev.detail, {"op": "manual", "message": "'pro' : connexion perdue, reconnecte ce compte",
                                     "via": "nouvelle-session", "from": "perso"})


class OpenSessionTest(unittest.TestCase):
    def setUp(self):
        self.tabs, self.external = [], []
        self.spec = LaunchSpec(cwd="/w", profile=None, model="opus", permission_mode="plan")

    def open(self, embedded):
        return lo.open_session(self.spec, embedded,
                               lambda cwd, extra_args=(): self.tabs.append((cwd, extra_args)),
                               external=self.external.append)

    def test_embedded_terminal_with_the_options(self):
        self.assertEqual(self.open(True), "integre")
        self.assertEqual(self.tabs, [("/w", ("--model", "opus", "--permission-mode", "plan"))])
        self.assertEqual(self.external, [])

    def test_without_embedded_terminal(self):
        self.assertEqual(self.open(False), "externe")
        self.assertEqual((self.tabs, self.external), ([], [self.spec]))

    def test_options_reach_the_embedded_tab_argv(self):
        from ccs_app import terminal
        launch = terminal.claude_launch("/w", extra_args=self.spec.args(), environ={})
        self.assertIn("--model opus --permission-mode plan", launch.argv[-1])


if __name__ == "__main__":
    unittest.main()
