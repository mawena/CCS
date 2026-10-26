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
