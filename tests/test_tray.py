import unittest

from ccs_app.tray import label_for


def state(*limits, active="perso"):
    return {"active": active, "accounts": [
        {"name": "perso", "active": True,
         "limits": [{"kind": k, "percent": p} for k, p in limits]}]}


class TrayLabelTest(unittest.TestCase):
    def test_label_for(self):
        self.assertEqual(label_for(state(("session", 32), ("weekly_all", 40))), "◔ 32 %")
        self.assertEqual(label_for(state(("session", 10), ("weekly_all", 98))), "⚠ 98 %")
        self.assertEqual(label_for(state(("session", 96))), "⚠ 96 %")
        self.assertEqual(label_for({}), "—")
        self.assertEqual(label_for(state(active=None)), "—")
        self.assertEqual(label_for(state()), "—")

    def test_label_quarters(self):
        self.assertEqual(label_for(state(("session", 5))), "○ 5 %")
        self.assertEqual(label_for(state(("session", 60))), "◑ 60 %")
        self.assertEqual(label_for(state(("session", 80))), "◕ 80 %")


from datetime import datetime, timedelta, timezone  # noqa: E402

from ccs_app.tray import gauge_svg, icon_name_for, menu_lines  # noqa: E402

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def iso(minutes):
    return (NOW + timedelta(minutes=minutes)).isoformat()


FULL = {
    "updated_at": NOW.timestamp() - 120, "active": "perso", "capacity": 1.2,
    "best": {"name": "boulot", "reason": "au repos, semaine à 22 %"},
    "accounts": [
        {"name": "perso", "active": True, "error": None,
         "limits": [{"kind": "session", "label": "S", "percent": 72, "resets_at": iso(80)},
                    {"kind": "weekly_all", "label": "W", "percent": 49, "resets_at": iso(3000)}],
         "forecast": {"verdict": "limit", "eta": iso(40)}},
        {"name": "boulot", "active": False, "error": "HTTP 429 : rate limited",
         "limits": [{"kind": "session", "label": "S", "percent": 0, "resets_at": None},
                    {"kind": "weekly_all", "label": "W", "percent": 89, "resets_at": iso(2000)}]},
    ],
    "orchestrator": {"enabled": True, "reserve": ["boulot"], "next_wake": iso(80),
                     "plan": [{"name": "boulot", "start": iso(150), "end": iso(450), "kind": "planned"},
                              {"name": "perso", "start": iso(-220), "end": iso(80), "kind": "current"}]},
}


class GaugeIconTest(unittest.TestCase):
    def test_gauge_color_and_fill(self):
        ok, warn, crit = gauge_svg(30), gauge_svg(75), gauge_svg(96)
        self.assertIn("#33d17a", ok)
        self.assertIn("#f6a034", warn)
        self.assertIn("#e01b24", crit)
        self.assertIn('stroke-dasharray="30.0 100"', ok)
        self.assertIn("<svg", gauge_svg(None))

    def test_icon_name_changes_with_state(self):
        self.assertEqual(icon_name_for(FULL), "ccs-gauge-70")
        self.assertEqual(icon_name_for({}), "ccs-gauge-none")


class MenuLinesTest(unittest.TestCase):
    def lines(self, state=FULL):
        return [text for text, _ in menu_lines(state, NOW)]

    def test_header_and_accounts(self):
        lines = self.lines()
        self.assertTrue(lines[0].startswith("Compte actif : perso"))
        self.assertIn("il y a 2 min", lines[0])
        perso = next(l for l in lines if "perso" in l and "session" in l)
        self.assertIn("72 %", perso)
        self.assertIn(datetime.fromisoformat(iso(80)).astimezone().strftime("%H:%M"), perso)
        boulot = next(l for l in lines if l.lstrip().startswith(("○", "●")) and "boulot" in l)
        self.assertIn("réserve", boulot)
        self.assertIn("⚠", boulot)

    def test_switch_action_on_inactive_account(self):
        actions = dict((t, a) for t, a in menu_lines(FULL, NOW))
        boulot = next(a for t, a in actions.items() if "boulot" in t and "session" in t)
        self.assertEqual(boulot, ("use", "boulot"))

    def test_best_forecast_and_orchestrator(self):
        text = "\n".join(self.lines())
        self.assertIn("Meilleur compte : boulot", text)
        self.assertIn("Limite estimée vers", text)
        self.assertIn("Prochaine recharge", text)
        self.assertIn("Capacité restante : 1,2", text)

    def test_empty_state(self):
        self.assertEqual(self.lines({})[0], "Pas encore de données — lance le service")

    def test_weekly_forecast_line_only_when_limit_comes_first(self):
        import copy
        st = copy.deepcopy(FULL)
        st["accounts"][1]["weekly_forecast"] = {"verdict": "limit", "eta": iso(36 * 60),
                                                "rate_per_day": 22, "days_before_reset": 1.2}
        st["accounts"][0]["weekly_forecast"] = {"verdict": "ok", "eta": None,
                                                "rate_per_day": 9, "days_before_reset": None}
        week = [l for l in self.lines(st) if "semaine épuisée" in l]
        self.assertEqual(len(week), 1)
        self.assertIn("boulot", week[0])
        self.assertNotIn("semaine épuisée", "\n".join(self.lines()))


class UpdateLineTest(unittest.TestCase):
    URL = "https://github.com/mawena/CCS/releases/tag/v0.5.0"

    def test_new_version_line_opens_release_page(self):
        st = dict(FULL, update={"version": "0.5.0", "url": self.URL, "name": "CCS 0.5.0"})
        line = next((t, a) for t, a in menu_lines(st, NOW) if "0.5.0" in t)
        self.assertEqual(line, ("⬆ CCS 0.5.0 disponible — voir la version", ("open", self.URL)))

    def test_no_line_without_update_or_with_foreign_link(self):
        self.assertFalse(any("disponible" in t for t, _ in menu_lines(FULL, NOW)))
        st = dict(FULL, update={"version": "0.5.0", "url": "https://exemple.invalid/x"})
        self.assertFalse(any("disponible" in t for t, _ in menu_lines(st, NOW)))


class SelfRestartTest(unittest.TestCase):
    def test_restart_only_once_the_new_code_is_stable(self):
        from ccs_app.tray import restart_due
        self.assertFalse(restart_due(10.0, 10.0, 10.0))   # rien n'a changé
        self.assertFalse(restart_due(10.0, 10.0, 20.0))   # mise à jour en cours
        self.assertTrue(restart_due(10.0, 20.0, 20.0))    # stable depuis un contrôle
        self.assertFalse(restart_due(10.0, 20.0, 30.0))   # encore en cours

    def test_restart_command_reuses_interpreter_and_arguments(self):
        import sys
        from unittest import mock

        from ccs_app.tray import restart_command
        with mock.patch.object(sys, "orig_argv", ["python3", "-m", "ccs_app.cli", "tray"]):
            self.assertEqual(restart_command(), [sys.executable, "-m", "ccs_app.cli", "tray"])
        with mock.patch.object(sys, "orig_argv", ["/usr/bin/python3", "/usr/bin/claude-accounts",
                                                  "tray"]):
            self.assertEqual(restart_command(),
                             [sys.executable, "/usr/bin/claude-accounts", "tray"])


class PauseMenuTest(unittest.TestCase):
    HOURS = {"start": "08:00", "end": "02:00", "days": list(range(7))}

    def test_choices_when_not_paused(self):
        from ccs_app.tray import pause_menu
        line, items = pause_menu(None, NOW, self.HOURS)
        self.assertIsNone(line)
        self.assertEqual([c for _, c in items], ["1h", "4h", "demain", "manuel"])
        self.assertEqual(items[0][0], "1 heure")

    def test_resume_when_paused(self):
        from ccs_app.pause import PauseState
        from ccs_app.tray import pause_menu
        line, items = pause_menu(PauseState(NOW, NOW + timedelta(hours=1)), NOW, self.HOURS)
        self.assertIn("En pause jusqu'à", line)
        self.assertEqual(items, [("Reprendre maintenant", "reprendre")])
        line, _ = pause_menu(PauseState(NOW, None), NOW, self.HOURS)
        self.assertIn("reprise manuelle", line)

    def test_label_shows_pause(self):
        self.assertEqual(label_for(state(("session", 32)), paused=True), "⏸ ◔ 32 %")
        self.assertEqual(label_for({}, paused=True), "⏸ —")


class SessionLinesTest(unittest.TestCase):
    def test_session_lines(self):
        import time
        from ccs_app.sessions import Session
        from ccs_app.tray import session_lines
        s = Session(7, "x", "gigit-cb", "/w/GiGit", "GiGit", "waiting", "permission",
                    time.time() - 4000, time.time(), "interactive", "cli")
        self.assertEqual(session_lines([s]), [("GiGit — attend ta réponse (permission)", s)])
        self.assertEqual(session_lines([]), [])


class GaugeCacheTest(unittest.TestCase):
    def test_icon_drawn_at_decile(self):
        from ccs_app.tray import gauge_for_name
        self.assertIn('stroke-dasharray="90.0 100"', gauge_for_name("ccs-gauge-90"))
        self.assertNotIn("stroke-dasharray", gauge_for_name("ccs-gauge-none"))


import sys  # noqa: E402
from unittest import mock  # noqa: E402

from tests.helpers import HomeTestCase  # noqa: E402


class AppEntriesTest(unittest.TestCase):
    def test_entries_open_the_right_page(self):
        from ccs_app.desktop import page_name
        from ccs_app.tray import APP_ENTRIES, gui_argv
        labels = [label for label, _ in APP_ENTRIES]
        self.assertEqual(labels, ["Journal des bascules", "Bilan de la semaine", "Ouvrir Comptes Claude"])
        pages = {label: args for label, args in APP_ENTRIES}
        self.assertEqual(page_name(pages["Journal des bascules"][-1]), "history")
        self.assertEqual(page_name(pages["Bilan de la semaine"][-1]), "analysis")
        self.assertEqual(pages["Ouvrir Comptes Claude"], ("gui",))
        with mock.patch.object(sys, "argv", ["/usr/bin/claude-accounts", "tray"]):
            self.assertEqual(gui_argv(("gui", "--page", "historique")),
                             [sys.executable, "/usr/bin/claude-accounts", "gui", "--page", "historique"])


class TraySwitchTest(HomeTestCase):
    def test_switch_notes_the_icon_for_the_journal(self):
        import subprocess
        from ccs_app import core, daemon, switch_log
        from ccs_app.tray import switch_to
        seen = []

        def run(args):
            seen.append((args, core.load_json(switch_log.origin_path())))
            return subprocess.CompletedProcess(args, 0, "ok", "")
        with mock.patch.object(daemon, "request_refresh") as refresh:
            self.assertTrue(switch_to("pro", run=run))
        args, note = seen[0]
        self.assertEqual(args, ["use", "pro"])
        self.assertEqual((note["profile"], note["via"]), ("pro", "icone"))
        refresh.assert_called_once()

    def test_failed_switch_leaves_no_origin(self):
        import subprocess
        from ccs_app import daemon, switch_log
        from ccs_app.tray import switch_to
        with mock.patch.object(daemon, "request_refresh") as refresh:
            self.assertFalse(switch_to("pro", run=lambda a: subprocess.CompletedProcess(a, 1, "", "non")))
        self.assertFalse(switch_log.origin_path().exists())
        refresh.assert_not_called()


class QuietMenuTest(unittest.TestCase):
    def test_label_shows_a_discreet_symbol_during_quiet(self):
        st = state(("session", 32))
        self.assertEqual(label_for(st, quiet=True), "🔕 ◔ 32 %")
        self.assertEqual(label_for(st, paused=True, waiting=2, quiet=True), "⏸ 🔕 ◔ 32 % · 💬 2")
        self.assertEqual(label_for(st), "◔ 32 %")

    def test_menu_without_silence(self):
        from ccs_app.tray import quiet_menu
        label, items, can_resume = quiet_menu(None, NOW)
        self.assertEqual(label, "Ne pas déranger")
        self.assertEqual([c for _, c in items], ["1h", "4h", "demain"])
        self.assertEqual(items[0][0], "1 heure")
        self.assertFalse(can_resume)

    def test_menu_shows_the_state(self):
        from ccs_app.quiet import QuietState
        from ccs_app.tray import quiet_menu
        end = NOW + timedelta(hours=1)
        label, items, can_resume = quiet_menu(QuietState("temporaire", end), NOW)
        self.assertRegex(label, r"^Ne pas déranger — silence jusqu'à \d\d:\d\d$")
        self.assertTrue(can_resume)
        label, _, can_resume = quiet_menu(QuietState("plage", end), NOW)
        self.assertIn("plage", label)
        self.assertFalse(can_resume)
        label, _, can_resume = quiet_menu(QuietState("temporaire", None), NOW)
        self.assertIn("reprise manuelle", label)
        self.assertTrue(can_resume)


class InstallEntryTest(unittest.TestCase):
    def test_entry_for_a_newer_version(self):
        from ccs_app.tray import install_entry
        self.assertEqual(install_entry({"update": {"version": "99.0.0"}}), "Installer CCS 99.0.0…")
        self.assertEqual(install_entry({"update": {"version": "v99.0.1"}}), "Installer CCS 99.0.1…")

    def test_no_entry_otherwise(self):
        from ccs_app.tray import install_entry
        for st in ({}, None, {"update": None}, {"update": {"version": "0.0.1"}}, {"update": {"version": 5}}):
            with self.subTest(state=st):
                self.assertIsNone(install_entry(st))
