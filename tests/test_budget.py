"""Budget par projet : stockage, semaine, dépense par dossier, alertes uniques, commande."""

import json
import os
import unittest
from datetime import datetime, timedelta, timezone

from ccs_app import budget, costs
from tests.helpers import HomeTestCase, write

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)      # mercredi
SETTINGS = {"alerts": {"weekly_report_day": 0, "weekly_report_hour": 9}, "budget": {}}


def answer(cwd, ts, input_tokens, msg_id):
    """Ligne de journal : 1 000 000 de tokens d'entrée en Sonnet 4.6 = 3 $."""
    return json.dumps({
        "type": "assistant", "timestamp": ts.isoformat().replace("+00:00", "Z"), "cwd": cwd,
        "message": {"id": msg_id, "model": "claude-sonnet-4-6", "role": "assistant",
                    "usage": {"input_tokens": input_tokens, "output_tokens": 0}}})


class BudgetCase(HomeTestCase):
    def setUp(self):
        super().setUp()
        costs.clear_cache()
        self.addCleanup(costs.clear_cache)
        self.app = self.home / "Work" / "App"
        self.other = self.home / "Work" / "Autre"
        for d in (self.app / "src", self.other):
            d.mkdir(parents=True)
        self.projects = self.home / ".claude" / "projects"

    def journal(self, name, lines):
        write(self.projects / name / "s.jsonl", "\n".join(lines) + "\n")

    def start(self):
        return budget.week_bounds(NOW, SETTINGS)[0]


class StorageTest(BudgetCase):
    def test_set_load_and_file_format(self):
        self.assertEqual(budget.set_budget(str(self.app), 25), 25.0)
        self.assertEqual(budget.load(), {str(self.app): 25.0})
        path = self.store / "budgets.json"
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
        data = json.loads(path.read_text())
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["budgets"], {str(self.app): {"weekly": 25.0}})

    def test_remove_and_invalid_amounts(self):
        budget.set_budget(str(self.app), 10)
        budget.set_budget(str(self.app), None)
        self.assertEqual(budget.load(), {})
        for bad in (0, -5, float("nan"), float("inf"), True, "12", 10 ** 9):
            with self.assertRaises(ValueError):
                budget.set_budget(str(self.app), bad)

    def test_corrupt_or_foreign_file_means_no_budget(self):
        for content in ("pas du json", "[]", json.dumps({"version": 9, "budgets": {"/x": {"weekly": 1}}})):
            write(self.store / "budgets.json", content)
            self.assertEqual(budget.load(), {})
        write(self.store / "budgets.json", json.dumps({"version": 1, "budgets": {
            "/ok": {"weekly": 5}, "relatif": {"weekly": 5}, "/neg": {"weekly": -1}, "/str": "x"}}))
        self.assertEqual(budget.load(), {"/ok": 5.0})
        budget.set_budget(str(self.app), 3)            # un enregistrement remplace le fichier illisible
        self.assertEqual(set(budget.load()), {"/ok", str(self.app)})

    def test_nearest_project(self):
        b = {str(self.home / "Work"): 50.0, str(self.app): 25.0}
        self.assertEqual(budget.nearest(str(self.app / "src"), b), str(self.app))
        self.assertEqual(budget.nearest(str(self.other), b), str(self.home / "Work"))
        self.assertIsNone(budget.nearest(str(self.home / "Work2"), b))
        self.assertIsNone(budget.nearest("", b))


class SpendTest(BudgetCase):
    def test_week_follows_the_weekly_report(self):
        start = self.start()
        self.assertEqual(start.astimezone().weekday(), 0)
        self.assertEqual(start.astimezone().hour, 9)
        self.assertLessEqual(start, NOW)
        self.assertLess(NOW - start, timedelta(days=7))

    def test_spend_by_project_with_subfolders_and_total(self):
        ts = self.start() + timedelta(hours=2)
        self.journal("p1", [answer(str(self.app / "src"), ts, 1_000_000, "m1"),
                            answer(str(self.app), ts, 1_000_000, "m2"),
                            answer(str(self.other), ts, 2_000_000, "m3"),
                            answer("", ts, 1_000_000, "m4")])
        # Hors semaine : ignorée.
        self.journal("p2", [answer(str(self.app), self.start() - timedelta(days=1), 5_000_000, "m5")])
        st = budget.status(NOW, SETTINGS, projects_dir=self.projects, budgets={str(self.app): 10.0})
        (row,) = st.rows
        self.assertAlmostEqual(row.spent, 6.0)
        self.assertAlmostEqual(row.pct, 60.0)
        self.assertAlmostEqual(st.total, 15.0)
        self.assertAlmostEqual(row.share, 6.0 / 15.0)

    def test_cache_by_size_and_date(self):
        ts = self.start() + timedelta(hours=1)
        self.journal("p1", [answer(str(self.app), ts, 1_000_000, "m1")])
        b = {str(self.app): 10.0}
        self.assertAlmostEqual(budget.status(NOW, SETTINGS, projects_dir=self.projects, budgets=b).rows[0].spent, 3.0)
        with open(self.projects / "p1" / "s.jsonl", "a") as f:
            f.write(answer(str(self.app), ts, 1_000_000, "m2") + "\n")
        self.assertAlmostEqual(budget.status(NOW, SETTINGS, projects_dir=self.projects, budgets=b).rows[0].spent, 6.0)

    def test_no_budget_no_reading(self):
        st = budget.status(NOW, SETTINGS, projects_dir=self.projects, budgets={})
        self.assertEqual((st.rows, st.total), ((), 0.0))

    def test_rows_sorted_by_percent(self):
        ts = self.start() + timedelta(hours=1)
        self.journal("p1", [answer(str(self.app), ts, 1_000_000, "m1"), answer(str(self.other), ts, 1_000_000, "m2")])
        st = budget.status(NOW, SETTINGS, projects_dir=self.projects,
                           budgets={str(self.app): 100.0, str(self.other): 4.0})
        self.assertEqual([r.cwd for r in st.rows], [str(self.other), str(self.app)])


class AlertsTest(BudgetCase):
    def pending(self, now=NOW, settings=SETTINGS):
        return budget.pending_alerts(now, settings, projects_dir=self.projects)

    def test_80_then_100_once_each(self):
        budget.set_budget(str(self.app), 10)
        ts = self.start() + timedelta(hours=1)
        self.assertEqual(self.pending(), [])
        self.journal("p1", [answer(str(self.app), ts, 2_700_000, "m1")])          # 8,1 $ = 81 %
        (a,) = self.pending()
        self.assertIn("80", a.title)
        self.assertTrue(a.key.startswith("budget:"))
        self.assertEqual(self.pending(), [])                                      # une seule fois
        self.journal("p1", [answer(str(self.app), ts, 2_700_000, "m1"),
                            answer(str(self.app), ts, 700_000, "m2")])            # 10,2 $ = 102 %
        (b,) = self.pending()
        self.assertIn("dépassé", b.title)
        self.assertNotEqual(a.key, b.key)
        self.assertEqual(self.pending(), [])

    def test_straight_to_100_marks_80_as_done(self):
        budget.set_budget(str(self.app), 10)
        self.journal("p1", [answer(str(self.app), self.start() + timedelta(hours=1), 4_000_000, "m1")])
        self.assertEqual(len(self.pending()), 1)
        self.assertEqual(self.pending(), [])

    def test_new_week_starts_again(self):
        budget.set_budget(str(self.app), 10)
        self.journal("p1", [answer(str(self.app), self.start() + timedelta(hours=1), 4_000_000, "m1")])
        self.assertEqual(len(self.pending()), 1)
        later = NOW + timedelta(days=7)
        ts = budget.week_bounds(later, SETTINGS)[0] + timedelta(hours=1)
        self.journal("p2", [answer(str(self.app), ts, 4_000_000, "m2")])
        stamp = (ts + timedelta(hours=1)).timestamp()      # date du fichier dans la semaine simulée
        os.utime(self.projects / "p2" / "s.jsonl", (stamp, stamp))
        self.assertEqual(len(self.pending(later)), 1)

    def test_changing_the_amount_resets_the_alerts(self):
        budget.set_budget(str(self.app), 10)
        self.journal("p1", [answer(str(self.app), self.start() + timedelta(hours=1), 4_000_000, "m1")])
        self.assertEqual(len(self.pending()), 1)
        budget.set_budget(str(self.app), 12.5)          # 12 $ de dépense : 96 %
        (a,) = self.pending()
        self.assertIn("80", a.title)

    def test_disabled_and_custom_thresholds(self):
        budget.set_budget(str(self.app), 10)
        self.journal("p1", [answer(str(self.app), self.start() + timedelta(hours=1), 4_000_000, "m1")])
        off = dict(SETTINGS, budget={"enabled": False})
        self.assertEqual(self.pending(settings=off), [])
        custom = dict(SETTINGS, budget={"alert_pcts": [50]})
        (a,) = self.pending(settings=custom)
        self.assertIn("50", a.title)

    def test_alert_text_has_no_conversation_content(self):
        budget.set_budget(str(self.app), 10)
        self.journal("p1", [answer(str(self.app), self.start() + timedelta(hours=1), 4_000_000, "m1")])
        (a,) = self.pending()
        self.assertIn("App", a.title)
        self.assertIn("Rien n'est bloqué", a.body)


class CommandTest(BudgetCase):
    def run_cmd(self, args):
        out = []
        code = budget.command(args, SETTINGS, accounts=[], projects_dir=self.projects, now=NOW,
                              home=str(self.home), cwd=str(self.home), out=out.append)
        return code, "\n".join(out)

    def test_state_without_budget(self):
        code, text = self.run_cmd([])
        self.assertEqual(code, 0)
        self.assertIn("Aucun budget", text)

    def test_set_show_and_remove(self):
        code, text = self.run_cmd(["Work/App", "25"])
        self.assertEqual(code, 0)
        self.assertIn("~/Work/App", text)
        self.assertEqual(budget.load(), {str(self.app): 25.0})
        self.journal("p1", [answer(str(self.app), self.start() + timedelta(hours=1), 1_000_000, "m1")])
        code, text = self.run_cmd([])
        self.assertEqual(code, 0)
        self.assertIn("~/Work/App", text)
        self.assertIn("12 %", text)
        self.assertIn("100 % de la semaine", text)
        code, text = self.run_cmd(["Work/App", "aucun"])
        self.assertEqual((code, budget.load()), (0, {}))
        self.assertIn("supprimé", text)
        self.assertEqual(self.run_cmd(["Work/App", "none"])[0], 0)

    def test_decimal_comma_and_dollar_sign(self):
        self.assertEqual(self.run_cmd(["Work/App", "12,5"])[0], 0)
        self.assertEqual(budget.load()[str(self.app)], 12.5)
        self.assertEqual(self.run_cmd(["Work/App", "30$"])[0], 0)
        self.assertEqual(budget.load()[str(self.app)], 30.0)

    def test_errors(self):
        self.assertEqual(self.run_cmd(["Work/App"])[0], 2)
        self.assertEqual(self.run_cmd(["a", "b", "c"])[0], 2)
        code, text = self.run_cmd(["Work/App", "beaucoup"])
        self.assertEqual(code, 2)
        self.assertIn("montant invalide", text)
        self.assertEqual(self.run_cmd(["Work/App", "-3"])[0], 2)
        code, text = self.run_cmd(["Work/Introuvable", "10"])
        self.assertEqual(code, 1)
        self.assertIn("introuvable", text)
        self.assertEqual(budget.load(), {})

    def test_default_output_is_print(self):
        from io import StringIO
        from contextlib import redirect_stdout
        buf = StringIO()
        with redirect_stdout(buf):
            self.assertEqual(budget.command(["x"]), 2)
        self.assertIn("usage", buf.getvalue())


class ConfigTest(unittest.TestCase):
    def test_config_fallbacks(self):
        self.assertEqual(budget.config({}), {"enabled": True, "alert_pcts": [80, 100]})
        self.assertEqual(budget.config({"budget": {"alert_pcts": "x", "enabled": False}}),
                         {"enabled": False, "alert_pcts": [80, 100]})
        self.assertEqual(budget.config({"budget": {"alert_pcts": [100, 50, 50]}})["alert_pcts"], [50, 100])


if __name__ == "__main__":
    unittest.main()
