import copy
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from ccs_app import costs, monthly_report as mr, weekly_report
from ccs_app.core import Limit
from ccs_app.costs import Answer
from ccs_app.settings import DEFAULTS
from ccs_app.store import Event, Store
from tests.helpers import HomeTestCase, write

DAY = timedelta(days=1)
# Mardi 10 novembre 2026, 12:00 heure locale.
NOW = datetime(2026, 11, 10, 12, 0).astimezone()
OCT = datetime(2026, 10, 1).astimezone()
NOV = datetime(2026, 11, 1).astimezone()


def local(*args):
    return datetime(*args).astimezone()


def settings(**alerts):
    s = copy.deepcopy(DEFAULTS)
    s["alerts"].update(alerts)
    return s


def ans(ts, model="claude-opus-5-5", cwd="/home/u/Work/App", out=1000):
    tokens = (0, out, 0, 0, 0)
    return Answer(ts.timestamp(), model, cwd, tokens, costs.reprice(tokens, model))


class BoundsTest(unittest.TestCase):
    def test_month_start_is_local_midnight(self):
        self.assertEqual(mr.month_start(2026, 10), local(2026, 10, 1))
        self.assertEqual(mr.month_start(2026, 13), local(2027, 1, 1))
        self.assertEqual(mr.month_start(2026, 0), local(2025, 12, 1))

    def test_shift_crosses_years(self):
        self.assertEqual(mr.shift(NOV, -1), OCT)
        self.assertEqual(mr.shift(NOV, -11), local(2025, 12, 1))
        self.assertEqual(mr.shift(local(2026, 12, 1), 1), local(2027, 1, 1))

    def test_month_of_uses_local_time(self):
        self.assertEqual(mr.month_of(local(2026, 10, 31, 23, 59)), OCT)
        self.assertEqual(mr.month_of(local(2026, 11, 1, 0, 0)), NOV)
        self.assertEqual(mr.month_of(NOW.astimezone(timezone.utc)), NOV)

    def test_choices_current_then_eleven_previous(self):
        c = mr.month_choices(NOW)
        self.assertEqual(len(c), 12)
        self.assertEqual(c[0], (NOV, NOW))
        self.assertEqual(c[1], (OCT, NOV))
        self.assertEqual(c[11][0], local(2025, 12, 1))
        self.assertEqual(c[11][1], local(2026, 1, 1))

    def test_labels_and_key(self):
        self.assertEqual(mr.month_label(OCT), "octobre 2026")
        self.assertEqual(mr.report_key(OCT), "monthly_report:2026-10")
        self.assertEqual(mr.report_key(local(2026, 2, 1)), "monthly_report:2026-02")


class AggregateTest(HomeTestCase):
    """Rapport construit sur un faux dossier de journaux et un historique."""

    def setUp(self):
        super().setUp()
        costs.clear_cache()
        self.db = Store()
        self.addCleanup(self.db.close)
        self.projects = Path(tempfile.mkdtemp(prefix="ccs-month-"))
        self.addCleanup(shutil.rmtree, self.projects)
        self.n = 0

    def journal(self, when, cwd="/w/App", out=1000, model="claude-opus-5-5"):
        self.n += 1
        line = {"type": "assistant", "timestamp": when.astimezone(timezone.utc).isoformat(), "cwd": cwd,
                "message": {"id": f"m{self.n}", "model": model, "usage": {"output_tokens": out}}}
        write(self.projects / f"-{Path(cwd).name}" / f"s{self.n}.jsonl", json.dumps(line) + "\n")

    def weekly(self, when, pct, profile="perso"):
        reset = datetime.fromtimestamp((OCT + 60 * DAY).timestamp(), timezone.utc)
        self.db.add_samples(when.timestamp(), profile, [Limit("weekly_all", "W", pct, reset)])

    def build(self, start, end, **kw):
        return mr.build_report(start, end, store=self.db, projects_dir=self.projects,
                               profiles=[], settings=copy.deepcopy(DEFAULTS), **kw)

    def test_month_boundaries_are_exact(self):
        self.journal(local(2026, 9, 30, 23, 59, 59))     # septembre
        self.journal(local(2026, 10, 1, 0, 0, 0))        # inclus
        self.journal(local(2026, 10, 31, 23, 59, 59))    # inclus
        self.journal(local(2026, 11, 1, 0, 0, 0))        # novembre
        r = self.build(OCT, NOV, previous=False)
        self.assertEqual(r.cost.reponses, 2)
        self.assertEqual(r.base.conversations, 2)
        self.assertFalse(r.partial)

    def test_totals_models_and_top_projects(self):
        for i in range(12):
            self.journal(local(2026, 10, 3 + i), cwd=f"/w/p{i:02d}", out=1000 * (i + 1))
        self.journal(local(2026, 10, 4), cwd="/w/p00", model="claude-haiku-5-5")
        r = self.build(OCT, NOV, previous=False)
        self.assertEqual(len(r.projects), 10)
        self.assertEqual(r.projects[0][0], "p11")
        self.assertGreaterEqual(r.projects[0][1].dollars, r.projects[1][1].dollars)
        self.assertIn("haiku", r.base.by_model)
        self.assertIn("opus", r.base.by_model)
        self.assertEqual(r.cost.reponses, 13)

    def test_accounts_weeks_and_windows(self):
        self.weekly(local(2026, 10, 2), 10.0)
        self.weekly(local(2026, 10, 3), 40.0)
        self.weekly(local(2026, 10, 20), 40.0)
        self.weekly(local(2026, 10, 21), 60.0)
        profile = mock.Mock()
        profile.name = "perso"
        r = mr.build_report(OCT, NOV, store=self.db, projects_dir=self.projects, profiles=[profile],
                            settings=copy.deepcopy(DEFAULTS), previous=False)
        acc = r.base.account("perso")
        self.assertEqual(acc.weekly_peak, 60.0)
        self.assertEqual(acc.weekly_used, 50.0)   # 30 + 0 + 20 points
        text = mr.format_text(r)
        self.assertIn("perso : 0,5 semaine(s) utilisée(s) (pic hebdomadaire à 60 %)", text)

    def test_switches_by_mode_and_monthly_key_not_counted_as_alert(self):
        for mode in ("auto", "auto", "manual", "initial"):
            self.db.add_event(local(2026, 10, 5).timestamp(), "switch", "pro", {"mode": mode})
        self.db.add_event(local(2026, 10, 5).timestamp(), "alert", None, {"key": "monthly_report:2026-09"})
        r = self.build(OCT, NOV, previous=False)
        self.assertEqual(r.base.switches, 3)
        self.assertEqual(r.base.switches_by_mode, {"auto": 2, "manual": 1})
        self.assertEqual(r.base.alerts, 0)

    def test_comparison_with_previous_month(self):
        self.journal(local(2026, 9, 10), out=1000)
        self.journal(local(2026, 10, 10), out=3000)
        r = self.build(OCT, NOV)
        self.assertEqual(r.previous.cost.reponses, 1)
        text = mr.format_text(r)
        self.assertIn("Par rapport au mois précédent", text)
        self.assertRegex(text, r"tokens : 3[,.]0 k \(\+200 % · \+2[,.]0 k\)")
        self.assertIn("conversations : 1 (=)", text)

    def test_decrease_is_signed(self):
        self.journal(local(2026, 9, 10), out=4000)
        self.journal(local(2026, 10, 10), out=1000)
        text = mr.format_text(self.build(OCT, NOV))
        self.assertRegex(text, r"tokens : .* \(−75 % · −")

    def test_partial_month_compares_the_same_number_of_days(self):
        self.journal(local(2026, 10, 2), out=1000)       # dans les 9 premiers jours
        self.journal(local(2026, 10, 25), out=9000)      # hors de la même plage
        self.journal(local(2026, 11, 3), out=2000)
        r = self.build(NOV, NOW)
        self.assertTrue(r.partial)
        self.assertEqual(r.previous.start, OCT)
        self.assertEqual(r.previous.end, OCT + (NOW - NOV))
        self.assertEqual(r.previous.cost.reponses, 1)
        self.assertEqual(r.cost.reponses, 1)
        text = mr.format_text(r)
        self.assertIn("(au 10 nov.)", text)
        self.assertIn("Par rapport au même nombre de jours du mois précédent", text)
        self.assertNotIn("×", text)   # pas de rapport au prix mensuel sur un mois incomplet

    def test_future_samples_and_answers_are_ignored_in_a_partial_month(self):
        self.journal(local(2026, 11, 20))
        self.assertEqual(self.build(NOV, NOW, previous=False).cost.reponses, 0)

    def test_trend_needs_three_months_of_activity(self):
        self.journal(local(2026, 10, 10))
        self.journal(local(2026, 11, 3))
        self.assertEqual(self.build(NOV, NOW).trend, [])
        self.journal(local(2026, 8, 3), out=2000)
        r = self.build(NOV, NOW)
        self.assertEqual([mr.report_key(p.start) for p in r.trend],
                         ["monthly_report:2026-08", "monthly_report:2026-09",
                          "monthly_report:2026-10", "monthly_report:2026-11"])
        self.assertEqual(r.trend[1].tokens, 0)
        self.assertTrue(r.trend[-1].partial)
        self.assertIn("Tendance sur 4 mois", mr.format_text(r))

    def test_no_data(self):
        r = self.build(OCT, NOV)
        self.assertTrue(r.empty)
        text = mr.format_text(r)
        self.assertIn("Aucune activité de Claude Code enregistrée sur ce PC.", text)
        self.assertIn("Aucune bascule", text)
        self.assertEqual(r.trend, [])
        self.assertIn("aucune activité", mr.notification(r, "k").body)

    def test_paid_plans_are_compared_to_the_api_equivalent(self):
        self.journal(local(2026, 10, 10), out=1_000_000)
        profile = mock.Mock()
        profile.name = "perso"
        with mock.patch("ccs_app.advisor.detect_plans", return_value=({"perso": "pro"}, [], [])):
            r = mr.build_report(OCT, NOV, store=self.db, projects_dir=self.projects,
                                profiles=[profile], settings=copy.deepcopy(DEFAULTS), previous=False)
        self.assertEqual(r.paid, 20.0)
        text = mr.format_text(r)
        self.assertIn("contre 20 $/mois payés", text)
        self.assertRegex(text, r"×\d+,\d")
        self.assertIn("contre 20 $", mr.notification(r, "k").body)

    def test_journals_are_read_once_for_the_whole_range(self):
        for m in (7, 8, 9, 10):
            self.journal(local(2026, m, 10))
        with mock.patch.object(costs, "period_answers", wraps=costs.period_answers) as spy:
            self.build(OCT, NOV)
        self.assertEqual(spy.call_count, 1)

    def test_notification_text(self):
        self.journal(local(2026, 9, 10), out=1000)
        self.journal(local(2026, 10, 10), out=2000)
        a = mr.notification(self.build(OCT, NOV), "monthly_report:2026-10")
        self.assertEqual(a.title, "Rapport mensuel")
        self.assertEqual(a.urgency, 0)
        self.assertTrue(a.body.startswith("Octobre 2026 :"))
        self.assertIn("+100 % sur le mois précédent", a.body)
        self.assertIn("Projet principal : App", a.body)


class PendingAlertTest(unittest.TestCase):
    def setUp(self):
        mr.clear_jobs()
        self.s = settings(monthly_report_hour=9)
        self.built = []

    def build(self, start, end):
        self.built.append((start, end))
        return mr.MonthReport(start, end, end, weekly_report.WeekReport(start, end))

    def pending(self, now=local(2026, 11, 1, 9, 30), sent=(), s=None, **kw):
        kw.setdefault("build", self.build)
        kw.setdefault("has_data", lambda *_: True)
        kw.setdefault("run", lambda work: work())
        return mr.pending_alert([], s or self.s, now, set(sent), **kw)

    def test_once_per_month_on_the_first(self):
        a = self.pending()
        self.assertEqual(a.key, "monthly_report:2026-10")
        self.assertEqual(a.title, "Rapport mensuel")
        self.assertEqual(self.built, [(OCT, NOV)])
        self.assertIsNone(self.pending(sent={"monthly_report:2026-10"}))
        self.assertEqual(len(self.built), 1)

    def test_not_before_the_hour_nor_after_the_grace_period(self):
        self.assertIsNone(self.pending(now=local(2026, 11, 1, 8, 59)))
        self.assertIsNone(self.pending(now=local(2026, 10, 31, 12, 0)))
        self.assertIsNone(self.pending(now=local(2026, 11, 3, 0, 0)))
        self.assertIsNone(self.pending(now=NOW))
        self.assertEqual(self.built, [])
        self.assertIsNotNone(self.pending(now=local(2026, 11, 2, 22, 0)))

    def test_hour_setting_and_invalid_hour(self):
        s = settings(monthly_report_hour=14)
        self.assertIsNone(self.pending(now=local(2026, 11, 1, 13, 0), s=s))
        self.assertIsNotNone(self.pending(now=local(2026, 11, 1, 14, 0), s=s))
        mr.clear_jobs()
        s = settings(monthly_report_hour=99)
        self.assertIsNone(self.pending(now=local(2026, 11, 1, 8, 0), s=s))
        self.assertIsNotNone(self.pending(now=local(2026, 11, 1, 9, 0), s=s))

    def test_default_hour_without_setting(self):
        s = settings()
        s["alerts"].pop("monthly_report_hour", None)
        self.assertIsNone(self.pending(now=local(2026, 11, 1, 8, 0), s=s))
        self.assertIsNotNone(self.pending(now=local(2026, 11, 1, 9, 0), s=s))

    def test_january_reports_december(self):
        a = self.pending(now=local(2027, 1, 1, 10, 0))
        self.assertEqual(a.key, "monthly_report:2026-12")

    def test_disabled(self):
        self.assertIsNone(self.pending(s=settings(monthly_report=False)))
        self.assertEqual(self.built, [])

    def test_enabled_without_setting(self):
        s = copy.deepcopy(DEFAULTS)
        s["alerts"].pop("monthly_report", None)
        self.assertIsNotNone(self.pending(s=s))

    def test_computed_in_the_background(self):
        queued = []
        self.assertIsNone(self.pending(run=queued.append))
        self.assertEqual(self.built, [])
        queued.pop()()
        self.assertEqual(self.pending(run=queued.append).key, "monthly_report:2026-10")
        self.assertEqual(queued, [])

    def test_less_than_a_week_of_data_means_no_report(self):
        self.assertIsNone(self.pending(has_data=lambda *_: False))
        self.assertIsNone(self.pending(has_data=lambda *_: False))
        self.assertEqual(self.built, [])

    def test_failure_is_retried_an_hour_later(self):
        def boom(start, end):
            raise OSError("illisible")
        with self.assertLogs("ccs.monthly_report", "ERROR"):
            self.assertIsNone(self.pending(build=boom))
        self.assertIsNone(self.pending(now=local(2026, 11, 1, 10, 0)))
        self.assertEqual(self.built, [])
        self.assertIsNotNone(self.pending(now=local(2026, 11, 1, 10, 31)))

    def test_service_frees_the_journal_cache_after_the_report(self):
        with mock.patch.object(mr, "build_report", return_value="r"), \
                mock.patch.object(costs, "clear_cache") as clear:
            self.assertEqual(mr._build_and_free(OCT, NOV), "r")
        clear.assert_called_once()

    def test_data_requirement_is_seven_days(self):
        with mock.patch.object(weekly_report, "has_data", return_value=True) as has:
            self.assertTrue(mr._has_data(OCT, NOV))
        self.assertEqual(has.call_args.kwargs["span"], timedelta(days=7))


class HasDataSpanTest(HomeTestCase):
    def test_week_default_and_month_span(self):
        db = Store()
        self.addCleanup(db.close)
        reset = datetime.fromtimestamp((OCT + 40 * DAY).timestamp(), timezone.utc)
        db.add_samples((NOV - 5 * DAY).timestamp(), "perso", [Limit("weekly_all", "W", 5.0, reset)])
        p = mock.Mock()
        p.name = "perso"
        self.assertTrue(weekly_report.has_data(OCT, NOV, store=db, profiles=[p]))
        self.assertFalse(weekly_report.has_data(OCT, NOV, store=db, profiles=[p], span=timedelta(days=7)))
        db.add_samples((NOV - 8 * DAY).timestamp(), "perso", [Limit("weekly_all", "W", 6.0, reset)])
        self.assertTrue(weekly_report.has_data(OCT, NOV, store=db, profiles=[p], span=timedelta(days=7)))


class CommandTest(unittest.TestCase):
    def run_cmd(self, args, **kw):
        calls = []

        def build(start, end):
            calls.append((start, end))
            return mr.MonthReport(start, end, end, weekly_report.WeekReport(start, end))
        code, text = mr.command(args, now=NOW, build=kw.get("build", build))
        return code, text, calls

    def test_default_is_the_last_complete_month(self):
        code, text, calls = self.run_cmd([])
        self.assertEqual(code, 0)
        self.assertEqual(calls, [(OCT, NOV)])
        self.assertTrue(text.startswith("Rapport mensuel : octobre 2026"))

    def test_precedent(self):
        _code, _text, calls = self.run_cmd(["--precedent", "2"])
        self.assertEqual(calls, [(local(2026, 8, 1), local(2026, 9, 1))])
        _code, _text, calls = self.run_cmd(["--precedent=10"])
        self.assertEqual(calls, [(local(2025, 12, 1), local(2026, 1, 1))])

    def test_namespace_arguments(self):
        _code, _text, calls = self.run_cmd(mock.Mock(precedent=1))
        self.assertEqual(calls, [(local(2026, 9, 1), local(2026, 10, 1))])

    def test_usage_errors_give_code_2(self):
        for bad in (["--precedent"], ["--precedent", "x"], ["--precedent", "-1"],
                    ["--precedent", "121"], ["--inconnu"], ["oups"]):
            code, text, calls = self.run_cmd(bad)
            self.assertEqual(code, 2, bad)
            self.assertTrue(text.startswith("Usage : ccs mois"), text)
            self.assertEqual(calls, [])

    def test_failure_gives_code_1(self):
        def boom(start, end):
            raise OSError("journaux illisibles")
        code, text, _ = self.run_cmd([], build=boom)
        self.assertEqual((code, text), (1, "Rapport impossible : journaux illisibles"))


class EvolutionTest(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(mr.evolution(5, 5, str), " (=)")
        self.assertEqual(mr.evolution(150, 100, mr._count), " (+50 % · +50)")
        self.assertEqual(mr.evolution(5, 0, mr._count), " (nouveau · +5)")
        self.assertEqual(mr.evolution(50, 100, mr._count), " (−50 % · −50)")
        self.assertEqual(mr.evolution(0.0, 0.0, str), " (=)")


if __name__ == "__main__":
    unittest.main()
