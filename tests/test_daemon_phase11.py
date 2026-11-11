"""Raccordement du service aux fonctions de la phase 11 : téléphone, tâches, archive,
budget, alerte de contexte lourd."""

import threading
import unittest
from datetime import timedelta
from unittest import mock

from ccs_app import alerts, daemon, phone, tasks
from tests.helpers import fake_http
from tests.test_daemon import NOW, DaemonBase, per_account, usage


def tick(d, settings, when=NOW):
    with fake_http(per_account(perso=usage(30), pro=usage(5))):
        return d.tick(settings, when)


class PhoneTest(DaemonBase):
    def test_every_alert_goes_through_phone_send_once(self):
        a = alerts.Alert("attente:1:2", "Projet attend", "corps", 1)
        with mock.patch.object(phone, "send") as send:
            self.d.notifier(a)
        send.assert_called_once()
        self.assertIs(send.call_args.args[0], a)
        self.assertEqual(self.sent, [a])

    def test_task_alert_passes_the_folder_name_only(self):
        folder = self.home / "Work" / "Appli"
        folder.mkdir(parents=True)
        t = tasks.add("faire quelque chose de secret", cwd=str(folder), now=NOW)
        a = tasks.finished_alert(tasks.update(t.id, state=tasks.DONE, finished=NOW.timestamp()))
        with mock.patch.object(phone, "send") as send:
            self.d.notifier(a)
        self.assertEqual(send.call_args.kwargs["project"], "Appli")
        self.assertEqual(self.sent, [a])

    def test_a_failing_phone_never_blocks_the_desktop(self):
        a = alerts.Alert("switch:x", "t", "b", 1)
        with mock.patch.object(phone, "send", side_effect=RuntimeError("réseau")):
            self.d.notifier(a)
        self.assertEqual(self.sent, [a])

    def test_disabled_phone_sends_nothing_over_the_network(self):
        a = alerts.Alert("switch:x", "t", "b", 1)
        with mock.patch.object(phone, "deliver") as deliver:
            self.d.settings = self.settings
            self.d.notifier(a)
        deliver.assert_not_called()


class TasksTest(DaemonBase):
    def test_tick_runs_tasks_and_sends_their_alerts(self):
        a = alerts.Alert("task:abc:done", "Tâche finie", "ok", 1, default="task:abc")
        with mock.patch.object(tasks, "tick", return_value=[a]) as tk:
            tick(self.d, self.settings)
        self.assertEqual(tk.call_args.args[0], NOW)
        self.assertIs(tk.call_args.args[1], self.settings)
        self.assertEqual(tk.call_args.args[3], False)        # pas en pause
        self.assertIn(a, self.sent)

    def test_pause_is_transmitted(self):
        from ccs_app import pause
        pause.set_pause(None, NOW)
        with mock.patch.object(tasks, "tick", return_value=[]) as tk:
            tick(self.d, self.settings)
        self.assertIs(tk.call_args.args[3], True)

    def test_wakes_every_30_s_while_a_task_is_waiting(self):
        tasks.add("x", cwd=str(self.home), now=NOW)
        with mock.patch.object(tasks, "tick", return_value=[]):
            delay = tick(self.d, self.settings)
        self.assertEqual(delay, daemon.TASKS_WAKE_S)
        self.assertTrue(self.d.tasks_active)

    def test_normal_cadence_without_active_task(self):
        with mock.patch.object(tasks, "tick", return_value=[]):
            self.assertEqual(tick(self.d, self.settings), 300)
        self.assertFalse(self.d.tasks_active)

    def test_a_failing_tasks_module_does_not_stop_the_service(self):
        with mock.patch.object(tasks, "tick", side_effect=RuntimeError("boum")):
            delay = tick(self.d, self.settings)
        self.assertEqual(delay, 300)
        self.assertTrue((self.store / "state.json").exists())

    def test_notification_click_shows_the_task(self):
        shown = []
        self.d.task_shower = lambda tid, token=None: shown.append((tid, token))
        self.assertFalse(self.d.handle_action("task:abc123", NOW, token="jeton"))
        self.assertEqual(shown, [("abc123", "jeton")])

    def test_disabled_tasks_are_not_polled_for_wake(self):
        self.settings["tasks"]["enabled"] = False
        tasks.add("x", cwd=str(self.home), now=NOW)
        with mock.patch.object(tasks, "tick", return_value=[]):
            self.assertEqual(tick(self.d, self.settings), 300)


class ArchiveTest(DaemonBase):
    def test_pass_every_30_minutes_in_a_thread(self):
        from ccs_app import archive
        main = threading.get_ident()
        seen = []
        with mock.patch.object(archive, "tick", side_effect=lambda *a, **k: seen.append(
                threading.get_ident()) or archive.PassResult()) as tk:
            tick(self.d, self.settings)
            self.d.join_jobs()
            tick(self.d, self.settings, NOW + timedelta(minutes=10))
            self.d.join_jobs()
            self.assertEqual(tk.call_count, 1)
            tick(self.d, self.settings, NOW + timedelta(minutes=31))
            self.d.join_jobs()
            self.assertEqual(tk.call_count, 2)
        self.assertNotIn(main, seen)

    def test_never_two_passes_at_once(self):
        from ccs_app import archive
        release = threading.Event()
        started = []

        def slow(*a, **k):
            started.append(1)
            release.wait(5)
            return archive.PassResult()
        with mock.patch.object(archive, "tick", side_effect=slow):
            tick(self.d, self.settings)
            self.assertIsNone(self.d._spawn("archive", lambda: None))
            self.d.last_archive = None            # l'échéance est passée, le fil tourne encore
            tick(self.d, self.settings, NOW + timedelta(hours=1))
            release.set()
            self.d.join_jobs()
        self.assertEqual(len(started), 1)

    def test_a_failing_pass_is_logged_and_nothing_else(self):
        from ccs_app import archive
        with mock.patch.object(archive, "tick", side_effect=OSError("disque plein")), \
                self.assertLogs("ccs.daemon", "ERROR"):
            delay = tick(self.d, self.settings)
            self.d.join_jobs()
        self.assertEqual(delay, 300)

    def test_real_pass_with_the_service_clock(self):
        # Le service a une horloge datetime ; le vrai module d'archive doit la recevoir en
        # secondes (0.8.0 : TypeError au premier passage, rien n'était archivé).
        import json
        import os
        from ccs_app import archive, sessions
        conv = sessions.projects_dir() / "-home-proj" / "abc.jsonl"
        conv.parent.mkdir(parents=True, exist_ok=True)
        conv.write_text(json.dumps({"type": "user", "message": {"content": "x"}}) + "\n")
        old = (NOW - timedelta(days=2)).timestamp()
        os.utime(conv, (old, old))
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.home / "data")}):
            with self.assertNoLogs("ccs.daemon", "ERROR"):
                tick(self.d, self.settings)
                self.d.join_jobs()
            self.assertEqual(archive.stats()[0], 1)

    def test_disabled_archive_is_never_started(self):
        from ccs_app import archive
        self.settings["archive"]["enabled"] = False
        with mock.patch.object(archive, "tick") as tk:
            tick(self.d, self.settings)
            self.d.join_jobs()
        tk.assert_not_called()


class BudgetTest(DaemonBase):
    def test_pending_budget_alerts_are_sent(self):
        from ccs_app import budget
        a = alerts.Alert("budget:/x:2026-W44:80", "Budget", "80 %", 1)
        with mock.patch.object(budget, "pending_alerts", return_value=[a]) as pa:
            tick(self.d, self.settings)
            self.d.join_jobs()
            tick(self.d, self.settings, NOW + timedelta(minutes=5))   # trop tôt
            self.d.join_jobs()
        self.assertEqual(pa.call_count, 1)
        self.assertIn(a, self.sent)

    def test_checked_again_after_15_minutes(self):
        from ccs_app import budget
        with mock.patch.object(budget, "pending_alerts", return_value=[]) as pa:
            tick(self.d, self.settings)
            self.d.join_jobs()
            tick(self.d, self.settings, NOW + timedelta(minutes=16))
            self.d.join_jobs()
        self.assertEqual(pa.call_count, 2)

    def test_disabled_budget_is_not_computed(self):
        from ccs_app import budget
        self.settings["budget"]["enabled"] = False
        with mock.patch.object(budget, "pending_alerts") as pa:
            tick(self.d, self.settings)
            self.d.join_jobs()
        pa.assert_not_called()

    def test_failure_is_contained(self):
        from ccs_app import budget
        with mock.patch.object(budget, "pending_alerts", side_effect=ValueError("x")), \
                self.assertLogs("ccs.daemon", "ERROR"):
            tick(self.d, self.settings)
            self.d.join_jobs()


class ContextAlertTest(DaemonBase):
    def test_sessions_poll_feeds_the_heavy_context_alert(self):
        from ccs_app import context_alert, sessions
        a = alerts.Alert("context:abc", "Contexte lourd", "x", 1)
        with mock.patch.object(sessions, "list_sessions", return_value=[]), \
                mock.patch.object(context_alert, "tick", return_value=[a]) as tk:
            self.d.on_sessions(self.settings, NOW)
        self.assertEqual(tk.call_args.args[1], self.settings)
        self.assertIn(a, self.sent)

    def test_failure_does_not_break_the_session_follow_up(self):
        from ccs_app import context_alert, sessions
        with mock.patch.object(sessions, "list_sessions", return_value=[]), \
                mock.patch.object(context_alert, "tick", side_effect=OSError("x")), \
                self.assertLogs("ccs.daemon", "ERROR"):
            self.d.on_sessions(self.settings, NOW)
        self.assertEqual(self.d.prev_sessions, {})


class ObserveOnlyTest(DaemonBase):
    def test_observation_starts_no_task_archive_or_budget(self):
        from ccs_app import archive, budget
        self.d.background_jobs = False
        with mock.patch.object(tasks, "tick") as tk, mock.patch.object(archive, "tick") as at, \
                mock.patch.object(budget, "pending_alerts") as bp:
            tick(self.d, self.settings)
            self.d.join_jobs()
        tk.assert_not_called()
        at.assert_not_called()
        bp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
