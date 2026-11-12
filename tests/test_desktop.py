"""Notifications cliquables : actions envoyées, clics reçus, ouverture de l'application."""

import os
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import desktop, notify
from ccs_app.alerts import Alert


class Params:
    def __init__(self, *values):
        self.values = values

    def unpack(self):
        return self.values


class NotifyActionsTest(unittest.TestCase):
    def test_plain_alert_has_no_action(self):
        self.assertEqual(notify.actions_for(Alert("k", "t", "b", 1)), [])

    def test_buttons_and_default_action(self):
        a = Alert("k", "t", "b", 1, (("use:pro", "Basculer sur pro"),))
        self.assertEqual(notify.actions_for(a), ["use:pro", "Basculer sur pro"])
        a = Alert("k", "t", "b", 1, (("show:7:s", "Afficher"),), default="show:7:s")
        # « default » : clic sur la notification elle-même (GNOME n'en fait pas un bouton).
        self.assertEqual(notify.actions_for(a), ["default", "Afficher", "show:7:s", "Afficher"])


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.clicks = []
        self.bridge = desktop.Bridge(lambda key, token=None: self.clicks.append((key, token)),
                                     lambda: None, Path("/nonexistent"))

    def send(self, alert, nid):
        with mock.patch.object(notify, "send", return_value=nid):
            return self.bridge.send(alert)

    def invoke(self, nid, key):
        self.bridge._on_signal(None, None, None, None, "ActionInvoked", Params(nid, key))

    def test_button_click(self):
        self.send(Alert("k", "t", "b", 1, (("use:pro", "Basculer"),)), 5)
        self.invoke(5, "use:pro")
        self.assertEqual(self.clicks, [("use:pro", None)])
        self.invoke(5, "use:pro")  # une seule fois par notification
        self.assertEqual(len(self.clicks), 1)

    def test_click_on_the_notification_uses_its_default_action(self):
        self.send(Alert("k", "t", "b", 1, (("show:7:s", "Afficher"),), default="show:7:s"), 8)
        self.bridge._on_token(None, None, None, None, "ActivationToken", Params(8, "jeton"))
        self.invoke(8, "default")
        self.assertEqual(self.clicks, [("show:7:s", "jeton")])

    def test_default_without_default_action_is_ignored(self):
        self.send(Alert("k", "t", "b", 1, (("use:pro", "Basculer"),)), 9)
        self.invoke(9, "default")
        self.assertEqual(self.clicks, [])

    def test_foreign_notifications_are_ignored(self):
        self.send(Alert("k", "t", "b", 1), 10)  # sans action : pas suivie
        self.invoke(10, "default")
        self.invoke(11, "use:pro")
        self.assertEqual(self.clicks, [])

    def test_memory_is_bounded(self):
        for nid in range(1, desktop.MAX_TRACKED + 50):
            self.send(Alert("k", "t", "b", 1, (("use:pro", "Basculer"),)), nid)
            self.bridge._on_token(None, None, None, None, "ActivationToken", Params(nid, "x"))
        self.assertLessEqual(len(self.bridge.ids), desktop.MAX_TRACKED)
        self.assertLessEqual(len(self.bridge.tokens), desktop.MAX_TRACKED)


class ShowSessionTest(unittest.TestCase):
    def test_object_path(self):
        self.assertEqual(desktop.object_path("io.ccs.ClaudeAccounts"), "/io/ccs/ClaudeAccounts")
        self.assertEqual(desktop.object_path("io.ccs.ClaudeAccounts.Dev"), "/io/ccs/ClaudeAccounts/Dev")
        self.assertEqual(desktop.object_path("org.ex-ample.App"), "/org/ex_ample/App")

    def test_app_id_follows_the_dev_copy(self):
        with mock.patch.dict(os.environ, {"CCS_APP_ID": "io.ccs.ClaudeAccounts.Dev"}):
            self.assertEqual(desktop.app_id(), "io.ccs.ClaudeAccounts.Dev")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(desktop.app_id(), "io.ccs.ClaudeAccounts")

    def test_platform_data(self):
        self.assertEqual(desktop.platform_data(None), {})
        self.assertEqual(set(desktop.platform_data("t")), {"activation-token", "desktop-startup-id"})

    def test_gui_command_leaves_the_service_cgroup(self):
        cmd = desktop.gui_command("7:s", python="/usr/bin/python3", launcher="/usr/bin/claude-accounts",
                                  systemd_run="/usr/bin/systemd-run")
        # Lancée dans sa propre unité : un redémarrage du service ne ferme pas la fenêtre.
        self.assertEqual(cmd[:2], ["/usr/bin/systemd-run", "--user"])
        self.assertIn("--scope", cmd)
        self.assertEqual(cmd[cmd.index("--") + 1:],
                         ["/usr/bin/python3", "/usr/bin/claude-accounts", "gui", "--session", "7:s"])
        plain = desktop.gui_command("7:s", python="/usr/bin/python3", launcher="/usr/bin/claude-accounts",
                                    systemd_run=None)
        self.assertEqual(plain, ["/usr/bin/python3", "/usr/bin/claude-accounts", "gui", "--session", "7:s"])

    def test_running_app_gets_the_action(self):
        calls = []
        with mock.patch.object(desktop, "activate_action", side_effect=lambda *a: calls.append(a) or True), \
                mock.patch.object(desktop, "launch_gui") as launch:
            self.assertEqual(desktop.show_session("7:s", "jeton"), "action")
        self.assertEqual(calls, [(desktop.app_id(), "show-session", "7:s", "jeton")])
        launch.assert_not_called()

    def test_otherwise_the_app_is_launched_on_the_session(self):
        with mock.patch.object(desktop, "activate_action", return_value=False), \
                mock.patch.object(desktop, "launch_gui") as launch:
            self.assertEqual(desktop.show_session("7:s", "jeton"), "lancement")
        launch.assert_called_once_with("7:s", "jeton")

    def test_bus_error_falls_back_to_launch(self):
        with mock.patch.object(desktop, "activate_action", side_effect=RuntimeError("bus")), \
                mock.patch.object(desktop, "launch_gui") as launch:
            self.assertEqual(desktop.show_session("7", None), "lancement")
        launch.assert_called_once()

    def test_invalid_reference_does_nothing(self):
        with mock.patch.object(desktop, "activate_action") as act, \
                mock.patch.object(desktop, "launch_gui") as launch:
            self.assertIsNone(desktop.show_session("--help", None))
        act.assert_not_called()
        launch.assert_not_called()


class PageNameTest(unittest.TestCase):
    def test_real_names_of_the_window(self):
        for name in desktop.PAGES:
            self.assertEqual(desktop.page_name(name)[0], name)

    def test_french_names_without_accents_or_case(self):
        expected = {"comptes": ("home", "accounts"), "Planning": ("home", "planning"),
                    "SESSIONS": ("sessions", None), "terminaux": ("sessions", None),
                    "historique": ("analysis", "history"), "analyse": ("analysis", "analysis"),
                    "réglages": ("prefs", None), "reglages": ("prefs", None),
                    " sessions ": ("sessions", None), "accueil": ("home", None)}
        for text, name in expected.items():
            self.assertEqual(desktop.page_name(text), name, text)

    def test_conversations_lead_to_sessions(self):
        # L'ancien onglet Conversations fait partie de l'onglet Sessions.
        self.assertEqual(desktop.page_name("conversations"), ("sessions", None))

    def test_unknown(self):
        for text in ("", "inconnu", None, "sessions2", "projets"):   # la page Projets a été retirée
            self.assertIsNone(desktop.page_name(text))

    def test_names_shown_to_the_user(self):
        self.assertEqual(desktop.PAGE_CHOICES, ("accueil", "sessions", "analyse", "comptes",
                                                "planning", "historique", "terminaux", "reglages"))
        for text in desktop.PAGE_CHOICES:
            self.assertIn(desktop.page_name(text)[0], desktop.PAGES + ("prefs",))

    def test_old_page_names_map_to_new_tabs(self):
        self.assertEqual(desktop.page_name("historique"), ("analysis", "history"))
        self.assertEqual(desktop.page_name("terminaux"), ("sessions", None))
        self.assertEqual(desktop.page_name("planning"), ("home", "planning"))
        self.assertEqual(desktop.PAGES, ("home", "sessions", "analysis"))

    def test_canonical_names_are_the_subpage_keys(self):
        for text, key in (("comptes", "accounts"), ("accueil", "home"),
                          ("historique", "history"), ("Réglages", "prefs")):
            self.assertEqual(desktop.canonical_page(text), key)
            self.assertIn(key, desktop.SUBPAGES)
        self.assertIsNone(desktop.canonical_page("inconnu"))


if __name__ == "__main__":
    unittest.main()


class ShowTaskTest(unittest.TestCase):
    def test_running_app_gets_the_show_task_action(self):
        calls = []
        with mock.patch.object(desktop, "activate_action", side_effect=lambda *a: calls.append(a) or True), \
                mock.patch.object(desktop, "launch_gui") as launch:
            self.assertEqual(desktop.show_task("ab12cd", "jeton"), "action")
        self.assertEqual(calls, [(desktop.app_id(), "show-task", "ab12cd", "jeton")])
        launch.assert_not_called()

    def test_closed_app_is_launched_on_the_planning_page(self):
        with mock.patch.object(desktop, "activate_action", return_value=False), \
                mock.patch.object(desktop, "launch_gui") as launch:
            self.assertEqual(desktop.show_task("ab12cd", None), "lancement")
        launch.assert_called_once_with("ab12cd", None, args=("--page", "planning", "--task", "ab12cd"))

    def test_launch_command_targets_the_planning_page(self):
        cmd = desktop.gui_command("x", python="/usr/bin/python3", launcher="/usr/bin/claude-accounts",
                                  systemd_run=None, args=("--page", "planning"))
        self.assertEqual(cmd, ["/usr/bin/python3", "/usr/bin/claude-accounts", "gui", "--page", "planning"])

    def test_invalid_identifier_does_nothing(self):
        with mock.patch.object(desktop, "activate_action") as act, \
                mock.patch.object(desktop, "launch_gui") as launch:
            self.assertIsNone(desktop.show_task("--help", None))
            self.assertIsNone(desktop.show_task("", None))
        act.assert_not_called()
        launch.assert_not_called()
