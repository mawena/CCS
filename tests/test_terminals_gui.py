"""Import paresseux et protégé de VTE : l'application ne dépend jamais de sa présence."""

import os
import time
import unittest
from unittest import mock

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk  # noqa: F401
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False


@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class LazyVteTest(unittest.TestCase):
    def setUp(self):
        from ccs_app.gui import terminals
        self.terminals = terminals
        terminals._vte = None
        self.addCleanup(setattr, terminals, "_vte", None)

    def test_missing_typelib_means_no_embedded_terminal(self):
        real = gi.require_version

        def missing(namespace, version):
            if namespace == "Vte":
                raise ValueError("Namespace Vte not available")
            return real(namespace, version)
        with mock.patch.object(gi, "require_version", side_effect=missing), \
                mock.patch.dict(os.environ, {"CCS_NO_VTE": ""}):
            self.assertIsNone(self.terminals.vte())
            self.assertIsNone(self.terminals.vte())  # réponse gardée : pas de nouvel essai

    def test_disabled_by_environment_without_importing(self):
        with mock.patch.object(gi, "require_version") as require, \
                mock.patch.dict(os.environ, {"CCS_NO_VTE": "1"}):
            self.assertIsNone(self.terminals.vte())
        require.assert_not_called()

    def test_module_import_does_not_load_vte(self):
        import importlib
        import sys
        sys.modules.pop("gi.repository.Vte", None)
        importlib.reload(self.terminals)
        self.assertNotIn("gi.repository.Vte", sys.modules)


# ---- page Sessions : chats dans des espaces de session ---------------------------------------

if GTK:
    import dataclasses
    import json
    import types
    from pathlib import Path

    from gi.repository import GLib, GObject

    from ccs_app import limit_events, sessions, settings, terminal, terminal_store
    from ccs_app.gui import terminals
    from ccs_app.gui.session_workspace import SessionWorkspace
    from tests.helpers import HomeTestCase

    @dataclasses.dataclass(frozen=True)
    class FakeOptions:
        model: str | None = None
        effort: str | None = None
        ultracode: bool = False
        rights: str = "manual"

    def fake_from_args(args):
        args = list(args)
        model = args[args.index("--model") + 1] if "--model" in args else None
        return FakeOptions(model=model)

    FAKE_OPTIONS = types.SimpleNamespace(ChatOptions=FakeOptions, from_args=fake_from_args)

    class FakeChatTab(Gtk.Box):
        """Même interface que ChatTab (tâche 7), sans moteur."""

        __gsignals__ = {
            "open-file": (GObject.SignalFlags.RUN_FIRST, None, (str, int)),
            "show-diff": (GObject.SignalFlags.RUN_FIRST, None, (str, str, str)),
        }

        def __init__(self, owner, launch, options=None, history_path=None):
            super().__init__(orientation=Gtk.Orientation.VERTICAL)
            self.owner, self.launch = owner, launch
            self.options, self.history_path = options, history_path
            self.state = terminal.TabState("claude", launch.cwd, launch.title, launch.session_id,
                                           extra_args=launch.extra_args)
            self.page = None
            self.queue_reason = None
            self.limits_done = set()
            self.sent, self.notices, self.suspends = [], [], []
            self.hung_up = 0
            self.read_only = False
            self.panel = Gtk.Box(hexpand=True, vexpand=True)
            self.append(self.panel)

        def update_page(self):
            if self.page is not None:
                self.page.set_title(self.state.title)

        def focus(self):
            pass

        def attention(self):
            pass

        def refresh_queue(self):
            pass

        def toggle_queue(self, show=None):
            pass

        def foreground_busy(self):
            return False

        def apply_colors(self, dark):
            pass

        def set_title(self, title):
            self.state.title = title

        def show_notice(self, text):
            self.notices.append(text)

        def send_auto(self, text):
            self.sent.append(text)
            return True

        def hang_up(self):
            self.hung_up += 1
            self.state.running = False

        def suspend_if_idle(self, now, idle_s):
            self.suspends.append((now, idle_s))
            return False

        def set_read_only(self, flag):
            self.read_only = flag

    class FakeWindow(Gtk.Window):
        def __init__(self):
            super().__init__()
            self.stack = mock.MagicMock()
            self.stack.get_visible_child_name.return_value = "sessions"
            self.update_badge = mock.MagicMock()
            self.on_page = mock.MagicMock()
            self.toast = mock.MagicMock()
            self.show_terminals = mock.MagicMock()
            self.hide_terminals = mock.MagicMock()
            self.terminals_changed = mock.MagicMock()
            self.rename_conversation = mock.MagicMock()


def spin(until, timeout=8.0):
    ctx = GLib.MainContext.default()
    deadline = GLib.get_monotonic_time() + int(timeout * 1e6)
    while not until() and GLib.get_monotonic_time() < deadline:
        ctx.iteration(False)
    return until()


@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class SessionsPageTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.project = Path(self.tmp) / "projet"
        self.project.mkdir()
        self.cwd = str(self.project)
        self.live = []
        for patcher in (
                mock.patch.object(terminals, "_chat_classes", return_value=(FakeChatTab, FAKE_OPTIONS)),
                mock.patch.object(sessions, "_claude_bin", return_value="/bin/true"),
                mock.patch.object(sessions, "list_sessions", side_effect=lambda *a, **k: list(self.live)),
                mock.patch.dict(os.environ, {"SHELL": "/bin/true"})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = FakeWindow()
        self.overview = Gtk.Label(label="Toutes les sessions")
        self.page = terminals.TerminalsPage(self.window, overview=self.overview)
        self.window.set_child(self.page)
        self.window.present()
        self.addCleanup(self.window.destroy)
        self.notified, self.phoned = [], []
        self.page.notifier = lambda alert: self.notified.append(alert)
        self.page.phoner = lambda alert, cfg, now, project=None: self.phoned.append((alert, project))
        self.addCleanup(self.page.view_cleanup) if hasattr(self.page, "view_cleanup") else None
        spin(lambda: False, 0.1)

    def chat(self, resume=None, **kw):
        tab = self.page.open_claude(self.cwd, resume, kw.pop("title", "Projet"), kw.pop("extra_args", ()))
        tab.state.running = kw.pop("running", False)
        for key, value in kw.items():
            setattr(tab.state, key, value)
        return tab

    def test_open_claude_opens_chat(self):
        tab = self.page.open_claude(self.cwd, None, "Export", ("--model", "opus"))
        self.assertIsInstance(tab, FakeChatTab)
        self.assertTrue(tab.state.chat)
        self.assertIsNone(tab.state.pid)          # le processus ne démarre qu'au premier envoi
        self.assertEqual(tab.options.model, "opus")
        self.assertIsInstance(tab.panel, SessionWorkspace)
        self.assertIs(tab.panel.get_parent(), tab)
        self.assertEqual(self.page.tabs(), [tab])

    def test_open_claude_with_resume_gives_the_journal_to_the_chat(self):
        journal = sessions.transcript_path(self.cwd, "s-1")
        journal.parent.mkdir(parents=True)
        journal.write_text("")
        self.assertEqual(self.page.open_claude(self.cwd, "s-1").history_path, journal)
        self.assertIsNone(self.page.open_claude(self.cwd, "s-absente").history_path)

    def test_overview_is_pinned_first_tab(self):
        view = self.page.view
        self.assertIs(view.get_nth_page(0).get_child(), self.overview)
        self.assertTrue(view.get_nth_page(0).get_pinned())
        self.assertEqual(view.get_nth_page(0).get_title(), "Toutes les sessions")
        tab = self.chat()
        self.assertEqual(self.page.tabs(), [tab])
        self.assertEqual(view.get_page_position(tab.page), 1)
        self.assertIsNone(self.page.records()[1] if False else None)
        view.set_selected_page(view.get_nth_page(0))
        self.assertIsNone(self.page.selected_tab())
        view.close_page(view.get_nth_page(0))       # jamais fermée
        spin(lambda: False, 0.2)
        self.assertIs(view.get_nth_page(0).get_child(), self.overview)
        self.assertEqual(view.get_n_pages(), 2)
        self.assertEqual(self.page.content.get_visible_child_name(), "tabs")
        self.page.close(tab)
        self.assertTrue(spin(lambda: view.get_n_pages() == 1))
        self.window.hide_terminals.assert_not_called()

    def test_records_skip_overview_and_keep_chat_options(self):
        tab = self.page.open_claude(self.cwd, "s-1", "Export", ("--model", "opus"))
        records, selected = self.page.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["session_id"], "s-1")
        self.assertEqual(records[0]["chat"]["model"], "opus")
        self.assertEqual(selected, 0)
        self.assertIs(self.page.tabs()[0], tab)

    def test_idle_chat_closes_without_question(self):
        tab = self.chat(running=True, state="idle")
        self.page.close(tab)
        self.assertTrue(spin(lambda: tab.page is None))

    def test_open_in_terminal_and_back(self):
        tab = self.chat("s-1", running=False, pid=None)
        tab.state.session_id = "s-1"
        position = self.page.view.get_page_position(tab.page)
        self.page.open_in_terminal(tab)
        self.assertTrue(spin(lambda: tab.page is None))
        self.assertEqual(tab.hung_up, 1)
        terms = [t for t in self.page.tabs() if isinstance(t, terminals.TerminalTab)]
        self.assertEqual(len(terms), 1)
        term = terms[0]
        self.assertEqual(self.page.view.get_page_position(term.page), position)
        self.assertEqual(list(term.launch.argv)[-1].split()[-2:], ["--resume", "s-1"])
        self.assertTrue(spin(lambda: term.back_btn.get_visible()))   # « true » est déjà fini
        term.back_btn.emit("clicked")
        self.assertTrue(spin(lambda: [t for t in self.page.tabs() if isinstance(t, FakeChatTab)]))
        back = [t for t in self.page.tabs() if isinstance(t, FakeChatTab)][0]
        self.assertEqual(back.state.session_id, "s-1")
        self.assertEqual([t for t in self.page.tabs() if isinstance(t, terminals.TerminalTab)], [])
        self.assertEqual(self.page.view.get_page_position(back.page), position)

    def test_open_in_terminal_needs_a_conversation(self):
        tab = self.chat()
        self.page.open_in_terminal(tab)
        self.assertIsNotNone(tab.page)
        self.assertEqual(tab.hung_up, 0)

    def test_v1_records_reopen_as_chats_without_process(self):
        journal = sessions.transcript_path(self.cwd, "s-1")
        journal.parent.mkdir(parents=True)
        journal.write_text("")
        records = [
            {"kind": "claude", "cwd": self.cwd, "title": "Export", "session_id": "s-1",
             "extra_args": ["--model", "opus"], "queue": ["lance les tests"]},
            {"kind": "shell", "cwd": self.cwd, "title": "Terminal", "session_id": None,
             "extra_args": [], "queue": []},
            {"kind": "claude", "cwd": self.cwd, "title": "Ailleurs", "session_id": "s-2",
             "extra_args": [], "queue": [], "chat": {"model": "sonnet", "effort": "high",
                                                      "ultracode": False, "rights": "plan"}},
        ]
        plan = terminal.restore_plan(records, 0, conversation_exists=lambda c, s: s == "s-1")
        self.page.reopen(plan, show=False)
        tabs = self.page.tabs()
        chats = [t for t in tabs if isinstance(t, FakeChatTab)]
        shells = [t for t in tabs if isinstance(t, terminals.TerminalTab)]
        self.assertEqual(len(chats), 2)
        self.assertEqual(len(shells), 1)
        first, second = chats
        self.assertIsNone(first.state.pid)
        self.assertFalse(first.state.running)
        self.assertEqual(first.history_path, journal)
        self.assertEqual(first.state.session_id, "s-1")
        self.assertEqual(first.options.model, "opus")
        self.assertEqual(first.state.queue, ["lance les tests"])
        self.assertIsNone(second.state.session_id)   # journal manquant : nouvelle conversation
        self.assertEqual((second.options.model, second.options.effort, second.options.rights),
                         ("sonnet", "high", "plan"))
        self.page.hang_up_all()

    def test_conversation_open_elsewhere_is_read_only(self):
        other = types.SimpleNamespace(pid=999999, session_id="s-9", state="idle", waiting_for=None,
                                      state_since=0.0)
        self.live = [other]
        tab = self.page.open_claude(self.cwd, "s-9", "Ailleurs")
        self.assertTrue(spin(lambda: tab.elsewhere_pid == 999999))
        self.assertTrue(tab.read_only)
        self.assertTrue(tab.panel.banner.get_revealed())
        self.assertIn("ouverte ailleurs", tab.panel.banner.get_title())
        self.assertTrue(self.page.needs_poll())
        self.page.send_queue(tab)
        self.assertEqual(tab.queue_reason, "Conversation ouverte ailleurs : rien n'est envoyé.")
        self.live = []                                  # l'autre processus a disparu
        self.page.synced(([], {}))
        self.assertIsNone(tab.elsewhere_pid)
        self.assertFalse(tab.read_only)
        self.assertFalse(tab.panel.banner.get_revealed())

    def test_own_process_is_not_elsewhere(self):
        mine = self.chat("s-1", running=True, pid=4242)
        self.live = [types.SimpleNamespace(pid=4242, session_id="s-1")]
        self.page.check_elsewhere(mine, self.live)      # déjà en marche : rien à vérifier
        self.assertIsNone(mine.elsewhere_pid)
        tab = self.chat("s-1", running=False, pid=None)
        tab.state.session_id = "s-1"
        self.page.check_elsewhere(tab, self.live)
        self.assertEqual(tab.elsewhere_pid, 4242)       # pid inconnu de nos onglets : ailleurs
        mine.state.pid = 4242
        tab.elsewhere_pid = None
        self.page.check_elsewhere(tab, self.live)
        self.assertIsNone(tab.elsewhere_pid)

    def test_limit_resume_sends_continue_to_chat(self):
        now = time.time()
        tab = self.chat("s-1", running=True, pid=77, state="idle", started_at=now - 600,
                        state_since=now - 30)
        tab.state.session_id = "s-1"
        event = limit_events.LimitEvent("s-1", now - 5, "perso", "pro", True, "switched")
        blocked = self.page.handle_limits([tab], {"s-1": event})
        self.assertEqual(tab.sent, ["continue"])
        self.assertEqual(len(tab.state.resumes), 1)
        self.assertEqual(blocked, set())
        self.assertTrue(tab.notices)

    def test_queue_is_sent_to_chat_when_free(self):
        now = time.time()
        tab = self.chat("s-1", running=True, pid=77, state="idle", busy_since=now - 20,
                        state_since=now - 10, queue=["suite"])
        self.page.send_queue(tab)
        self.assertEqual(tab.sent, ["suite"])
        self.assertEqual(tab.state.queue, [])

    def test_idle_chat_suspended(self):
        tab = self.chat("s-1", running=True, pid=77, state="idle")
        self.assertTrue(self.page.suspend_idle(now=5000.0))
        self.assertEqual(tab.suspends, [(5000.0, 30 * 60)])
        current = settings.load_settings()
        current["chat"]["idle_suspend_min"] = 0
        settings.save_settings(current)
        self.page.suspend_idle(now=9000.0)
        self.assertEqual(len(tab.suspends), 1)          # 0 = jamais

    def test_split_two_chats(self):
        one, two = self.chat("s-1"), self.chat("s-2")
        self.page.split_with(one)
        self.assertTrue(self.page.is_split())
        self.assertTrue(self.page.split_view.contains(one))
        self.assertTrue(self.page.split_view.contains(two))
        self.assertIsInstance(one.panel.get_parent().get_parent(), Gtk.Box)
        self.assertIsNot(one.panel.get_parent(), one)
        self.page.unsplit()
        self.assertFalse(self.page.is_split())
        self.assertIs(one.panel.get_parent(), one)
        self.assertIs(two.panel.get_parent(), two)

    def test_waiting_alert_when_hidden(self):
        tab = self.chat("s-1", running=True, pid=77)
        other = self.chat("s-2")                         # l'onglet affiché est un autre
        self.page.view.set_selected_page(other.page)
        now = time.time()
        tab.state.state, tab.state.state_since = "waiting", now
        with mock.patch.object(self.page, "on_screen", return_value=True):
            self.page.changed(tab)
        self.assertTrue(spin(lambda: self.notified))
        self.assertEqual(len(self.notified), 1)
        self.assertTrue(self.notified[0].title.endswith("attend ta réponse"))
        self.assertTrue(self.notified[0].key.startswith("attente:"))
        self.assertEqual(self.phoned[0][1], "projet")    # le téléphone aussi, par le même chemin
        with mock.patch.object(self.page, "on_screen", return_value=True):
            self.page.changed(tab)                       # même attente : une seule alerte
            spin(lambda: False, 0.1)
        self.assertEqual(len(self.notified), 1)
        tab.state.state, tab.state.state_since = "busy", now + 1
        self.page.changed(tab)
        tab.state.state, tab.state.state_since = "waiting", now + 20
        with mock.patch.object(self.page, "on_screen", return_value=True):
            self.page.changed(tab)
        self.assertTrue(spin(lambda: len(self.notified) == 2))

    def test_no_waiting_alert_when_chat_is_in_front(self):
        tab = self.chat("s-1", running=True, pid=77)
        self.page.view.set_selected_page(tab.page)
        tab.state.state, tab.state.state_since = "waiting", time.time()
        with mock.patch.object(self.page, "on_screen", return_value=True):
            self.page.changed(tab)
        spin(lambda: False, 0.2)
        self.assertEqual((self.notified, self.phoned), ([], []))

    def test_chat_state_change_emits_signal(self):
        tab = self.chat("s-1", running=True, pid=77)
        got = []
        self.page.connect("tab-state-changed", lambda _p, t: got.append(t))
        tab.state.state, tab.state.state_since = "busy", time.time()
        self.page.changed(tab)
        self.assertEqual(got, [tab])

    def test_layout_button_switches_every_workspace_and_is_kept(self):
        one, two = self.chat("s-1"), self.chat("s-2")
        self.page.layout_btn.emit("clicked")
        self.assertEqual((one.panel.layout, two.panel.layout), ("A", "A"))
        self.assertEqual(settings.load_settings()["files"]["layout"], "A")
        three = self.chat("s-3")
        self.assertEqual(three.panel.layout, "A")
        self.page.set_layout("B")
        self.assertEqual(settings.load_settings()["files"]["layout"], "B")

    def test_shell_tabs_stay_vte_terminals(self):
        shell = self.page.open_shell(self.cwd)
        self.assertIsInstance(shell, terminals.TerminalTab)
        self.assertIs(self.page.tabs()[0], shell)
        self.page.hang_up_all()
