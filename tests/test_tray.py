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
