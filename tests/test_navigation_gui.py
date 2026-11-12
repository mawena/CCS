"""Navigation en quatre onglets (Accueil, Sessions, Projets, Analyse) : fenêtre réelle dans un
HOME temporaire, sans écran réel (Xvfb), sans service ni vraie session."""

import importlib.util
import os
import unittest
from unittest import mock

from tests.helpers import HomeTestCase

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, GLib, Gtk  # noqa: F401
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False

HAS_PROJECTS = importlib.util.find_spec("ccs_app.gui.projects_page") is not None


@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class NavigationTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        for p in (mock.patch.dict(os.environ, {"CCS_APP_ID": "io.ccs.ClaudeAccounts.TestNav", "CCS_NO_VTE": "1"}),
                  mock.patch("ccs_app.gui.app.refresh_data"),
                  mock.patch("ccs_app.daemon.running_pid", return_value=None),
                  mock.patch("ccs_app.sessions.list_sessions", return_value=[]),
                  mock.patch("ccs_app.updates.available", return_value=None)):
            p.start()
            self.addCleanup(p.stop)
        from ccs_app.gui import app
        self.appmod = app
        self.app = app.App()
        self.win = app.Window(self.app)
        self.addCleanup(self.win.destroy)

    def tab(self):
        return self.win.stack.get_visible_child_name()

    def test_four_tabs_in_order(self):
        pages = self.win.stack.get_pages()
        titles = [(pages.get_item(i).get_name(), pages.get_item(i).get_title())
                  for i in range(pages.get_n_items())]
        self.assertEqual(titles, [("home", "Accueil"), ("sessions", "Sessions"),
                                  ("projects", "Projets"), ("analysis", "Analyse")])

    def test_sessions_tab_always_visible(self):
        page = self.win.stack.get_page(self.win.stack.get_child_by_name("sessions"))
        self.assertTrue(page.get_visible())

    def test_prefs_in_menu_opens_dialog(self):
        shown = []
        with mock.patch.object(Adw.PreferencesDialog, "present", lambda d, parent=None: shown.append(d)):
            self.win.activate_action("prefs", None)
            self.assertEqual(self.win.show_page("reglages"), "prefs")
        self.assertEqual(len(shown), 2)
        self.assertIsInstance(shown[0], Adw.PreferencesDialog)
        self.assertEqual(self.tab(), "home")   # les réglages ne sont pas un onglet

    def test_prefs_entry_is_in_the_main_menu(self):
        labels = []

        def walk(widget):
            if isinstance(widget, Gtk.MenuButton) and widget.get_menu_model() is not None:
                model = widget.get_menu_model()
                labels.extend(model.get_item_attribute_value(i, "label", None).get_string()
                              for i in range(model.get_n_items()))
            child = widget.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()
        walk(self.win.header)
        self.assertIn("Réglages", labels)

    def test_task_link_lands_on_home_planning(self):
        self.win.stack.set_visible_child_name("analysis")
        with mock.patch.object(self.win.planning.tasks_view, "show_task", return_value=True) as show:
            self.assertEqual(self.win.show_task("7"), "planning")
        show.assert_called_once_with("7")
        self.assertEqual(self.tab(), "home")

    def test_old_page_names_land_on_the_right_tab(self):
        for name, tab in (("comptes", "home"), ("planning", "home"), ("terminaux", "sessions"),
                          ("sessions", "sessions"), ("historique", "analysis"), ("analyse", "analysis"),
                          ("projets", "projects"), ("accueil", "home"), ("accounts", "home")):
            self.win.stack.set_visible_child_name("sessions" if tab != "sessions" else "home")
            self.assertEqual(self.win.show_page(name), tab, name)
            self.assertEqual(self.tab(), tab, name)
        self.assertIsNone(self.win.show_page("inconnu"))

    def test_history_page_opens_the_history_part(self):
        self.win.show_page("historique")
        self.assertEqual(self.win.analysis_hub.current(), "history")
        self.win.show_page("analyse")
        self.assertEqual(self.win.analysis_hub.current(), "analysis")

    def test_ctrl_numbers_switch_tabs(self):
        # Les accélérateurs sont posés à la création de la fenêtre par App.window().
        app2 = self.appmod.App()
        with mock.patch.object(self.appmod, "Window", return_value=self.win):
            app2.window()
        for key, tab in enumerate(("home", "sessions", "projects", "analysis"), 1):
            self.assertEqual(app2.get_actions_for_accel(f"<Control>{key}"), [f"win.show-tab('{tab}')"])
        self.assertEqual(app2.get_actions_for_accel("<Control>comma"), ["win.prefs"])
        for tab in ("analysis", "projects", "sessions", "home"):
            self.win.activate_action("show-tab", GLib.Variant("s", tab))
            self.assertEqual(self.tab(), tab)

    def test_badge_counts_waiting_sessions(self):
        from types import SimpleNamespace
        waiting = [SimpleNamespace(state="waiting"), SimpleNamespace(state="busy"),
                   SimpleNamespace(state="waiting")]
        with mock.patch("ccs_app.sessions.list_sessions", return_value=waiting), \
                mock.patch("ccs_app.gui.app.in_thread", side_effect=lambda work, done: done(work())):
            self.win.update_badge()
        page = self.win.stack.get_page(self.win.stack.get_child_by_name("sessions"))
        self.assertEqual(page.get_badge_number(), 2)
        self.assertTrue(page.get_needs_attention())

    def test_open_session_opens_claude_in_the_folder(self):
        with mock.patch.object(self.win, "open_claude", return_value="integre") as opened:
            self.win.open_session("/tmp/projet")
        opened.assert_called_once_with("/tmp/projet")

    @unittest.skipIf(HAS_PROJECTS, "la vraie page Projets est là")
    def test_provisional_projects_page(self):
        self.assertIsInstance(self.win.projects, Adw.StatusPage)

    @unittest.skipUnless(HAS_PROJECTS, "page Projets (tâche 8) pas encore fusionnée")
    def test_projects_tab_holds_the_projects_page(self):
        from ccs_app.gui.projects_page import ProjectsPage
        self.assertIsInstance(self.win.projects, ProjectsPage)

    @unittest.skip("tâche 9 : l'aperçu épinglé n'existe pas encore")
    def test_overview_pinned_in_sessions(self):
        pass


@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class HomeEventsTest(HomeTestCase):
    def test_recent_events_newest_first_and_limited(self):
        from ccs_app.gui import home_page
        from ccs_app.tasks import Task
        done = [Task(id=str(i), message=f"tâche {i}", cwd="/x", state="done", finished=1000.0 + i)
                for i in range(12)]
        with mock.patch("ccs_app.tasks.all", return_value=done), \
                mock.patch("ccs_app.switch_log.load", return_value=[]):
            events = home_page.recent_events(None, now=2000.0)
        self.assertEqual(len(events), home_page.EVENTS_SHOWN)
        self.assertEqual([e[0] for e in events], sorted((e[0] for e in events), reverse=True))
        self.assertEqual(events[0][0], 1011.0)


if __name__ == "__main__":
    unittest.main()
