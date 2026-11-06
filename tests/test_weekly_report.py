import copy
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from ccs_app import costs, weekly_report
from ccs_app.core import Limit
from ccs_app.costs import Answer
from ccs_app.forecast import AccountState
from ccs_app.settings import DEFAULTS
from ccs_app.store import Event, Store
from tests.helpers import HomeTestCase, write

# Jeudi 5 novembre 2026, 12:00 heure locale.
NOW = datetime(2026, 11, 5, 12, 0).astimezone()
DAY = timedelta(days=1)
WEEK = timedelta(days=7)


def account(name, weekly_reset):
    return AccountState(name, False, [Limit("weekly_all", "W", 30, weekly_reset)], NOW.timestamp(), None)


def settings(**alerts):
    s = copy.deepcopy(DEFAULTS)
    s["alerts"].update(alerts)
    return s


class AnchorTest(unittest.TestCase):
    def test_fixed_day_and_hour(self):
        s = settings(weekly_report_day=0, weekly_report_hour=9)
        self.assertEqual(weekly_report.week_anchor([], NOW, s), datetime(2026, 11, 2, 9, 0).astimezone())
        monday_early = datetime(2026, 11, 9, 8, 0).astimezone()
        self.assertEqual(weekly_report.week_anchor([], monday_early, s),
                         datetime(2026, 11, 2, 9, 0).astimezone())
        self.assertEqual(weekly_report.week_anchor([], datetime(2026, 11, 9, 9, 30).astimezone(), s),
                         datetime(2026, 11, 9, 9, 0).astimezone())

    def test_majority_of_accounts(self):
        # Semaines commencées il y a 1 j (a), 1,5 j (b) et 3 j (c) : la plupart (2 sur 3)
        # ont commencé leur nouvelle semaine au début de celle de b.
        accs = [account("a", NOW + 6 * DAY), account("b", NOW + 5.5 * DAY), account("c", NOW + 4 * DAY)]
        anchor = weekly_report.week_anchor(accs, NOW, settings())
        self.assertEqual(anchor, NOW - 1.5 * DAY)

    def test_anchor_is_stable_through_the_week(self):
        accs = [account("a", NOW + 6 * DAY), account("b", NOW + 5.5 * DAY), account("c", NOW + 4 * DAY)]
        first = weekly_report.week_anchor(accs, NOW, settings())
        later = NOW + 4.5 * DAY  # c a recommencé une semaine entre-temps
        accs2 = [account("a", NOW + 6 * DAY), account("b", NOW + 5.5 * DAY), account("c", NOW + 11 * DAY)]
        self.assertEqual(weekly_report.week_anchor(accs2, later, settings()), first)
        after_b = NOW + 5.6 * DAY  # b a recommencé : nouvelle semaine du bilan
        accs3 = [account("a", NOW + 6 * DAY), account("b", NOW + 12.5 * DAY), account("c", NOW + 11 * DAY)]
        self.assertEqual(weekly_report.week_anchor(accs3, after_b, settings()), first + WEEK)

    def test_two_accounts_need_both(self):
        accs = [account("a", NOW + 6 * DAY), account("b", NOW + 4 * DAY)]
        self.assertEqual(weekly_report.week_anchor(accs, NOW, settings()), NOW - DAY)

    def test_without_weekly_data_falls_back_to_monday(self):
        accs = [AccountState("a", True, [], None, None), account("b", NOW - DAY)]  # fenêtre expirée
        self.assertEqual(weekly_report.week_anchor(accs, NOW, settings()),
                         datetime(2026, 11, 2, 9, 0).astimezone())

    def test_week_choices(self):
        s = settings(weekly_report_day=0, weekly_report_hour=9)
        weeks = weekly_report.week_choices([], NOW, s, count=3)
        monday = datetime(2026, 11, 2, 9, 0).astimezone()
        self.assertEqual(weeks[0], (monday, NOW))  # semaine en cours
        self.assertEqual(weeks[1], (monday - WEEK, monday))
        self.assertEqual(weeks[3], (monday - 3 * WEEK, monday - 2 * WEEK))


class PendingAlertTest(unittest.TestCase):
    def setUp(self):
        weekly_report.clear_jobs()
        self.s = settings(weekly_report_day=3, weekly_report_hour=9)   # jeudi 9:00
        self.anchor = datetime(2026, 11, 5, 9, 0).astimezone()
        self.built = []

    def build(self, start, end):
        self.built.append((start, end))
        return weekly_report.WeekReport(start, end)

    def pending(self, now=NOW, sent=(), **kw):
        kw.setdefault("build", self.build)
        kw.setdefault("has_data", lambda *_: True)
        kw.setdefault("run", lambda work: work())
        return weekly_report.pending_alert([], self.s, now, set(sent), **kw)

    def test_once_per_week_at_the_start_of_the_week(self):
        a = self.pending()
        self.assertEqual(a.key, "weekly_report:2026-11-05")
        self.assertEqual(a.title, "Bilan de la semaine")
        self.assertEqual(self.built, [(self.anchor - WEEK, self.anchor)])
        self.assertIsNone(self.pending(sent={a.key}))
        # Clé d'une date voisine (heure de réinitialisation qui a bougé) : pas de doublon.
        self.assertIsNone(self.pending(sent={"weekly_report:2026-11-04"}))
        # Celle de la semaine précédente n'empêche rien.
        self.assertIsNotNone(self.pending(sent={"weekly_report:2026-10-29"}))

    def test_not_before_nor_too_late(self):
        self.assertIsNone(self.pending(now=self.anchor - timedelta(minutes=1)))
        self.assertIsNone(self.pending(now=self.anchor + 2 * DAY + timedelta(minutes=1)))
        self.assertEqual(self.built, [])

    def test_disabled(self):
        self.s["alerts"]["weekly_report"] = False
        self.assertIsNone(self.pending())
        self.assertEqual(self.built, [])

    def test_computed_in_the_background(self):
        jobs = []
        self.assertIsNone(self.pending(run=jobs.append))   # calcul lancé, rien à envoyer encore
        self.assertIsNone(self.pending(run=jobs.append))   # toujours en cours : pas de second calcul
        self.assertEqual(len(jobs), 1)
        jobs[0]()
        self.assertIsNotNone(self.pending(run=jobs.append))

    def test_no_data_means_no_report(self):
        self.assertIsNone(self.pending(has_data=lambda *_: False))
        self.assertIsNone(self.pending(has_data=lambda *_: False))
        self.assertEqual(self.built, [])

    def test_failure_is_retried_an_hour_later(self):
        def boom(start, end):
            raise OSError("illisible")
        with self.assertLogs("ccs.weekly_report", "ERROR"):
            self.assertIsNone(self.pending(build=boom))
        self.assertIsNone(self.pending())
        self.assertIsNotNone(self.pending(now=NOW + timedelta(minutes=61)))


def ans(ts, model="claude-opus-5-5", cwd="/home/u/Work/App", out=1000):
    tokens = (0, out, 0, 0, 0)
    return Answer(ts.timestamp(), model, cwd, tokens, costs.reprice(tokens, model))


class AggregateTest(unittest.TestCase):
    START = datetime(2026, 10, 29, 9, 0).astimezone()
    END = START + WEEK

    def samples(self):
        s, e = self.START.timestamp(), self.END.timestamp()
        h = 3600
        reset = e + 2 * 86400
        weekly = [(s - 3600, 20.0, reset - 7 * 86400)]
        weekly += [(s + 86400, 50.0, reset - 7 * 86400), (e - 4 * 86400, 2.0, reset),
                   (e - 3600, 40.0, reset)]
        sessions = [(s + 10 * h, 30.0, s + 14 * h), (s + 12 * h, 99.5, s + 14 * h),
                    (s + 30 * h, 10.0, s + 33 * h), (s + 50 * h, 0.0, s + 54 * h)]
        return {"perso": {"weekly_all": weekly, "session": sessions}, "pro": {"weekly_all": [], "session": []}}

    def events(self):
        t = self.START + DAY
        return [Event(t.timestamp(), "switch", "pro", {"mode": "auto"}),
                Event(t.timestamp() + 60, "switch", "perso", {"mode": "manual"}),
                Event(t.timestamp() + 120, "switch", "perso", {"mode": "initial"}),
                Event((self.START - DAY).timestamp(), "switch", "pro", {"mode": "auto"}),
                Event(t.timestamp(), "alert", None, {"key": "session80:perso:1"}),
                Event(t.timestamp(), "alert", None, {"key": "session95:perso:1"}),
                Event(t.timestamp(), "alert", None, {"key": "weekly_report:2026-10-29"}),
                Event(t.timestamp(), "alert", "blocage", {"key": "blocage:1"})]

    def answers(self):
        projects = Path("/home/u/.claude/projects")
        t = self.START + DAY
        return {
            projects / "-home-u-Work-App" / "s1.jsonl": [ans(t), ans(t + timedelta(minutes=10)),
                                                         ans(t + timedelta(hours=2))],
            projects / "-home-u-Work-App" / "s1" / "subagents" / "a.jsonl": [
                ans(t, model="claude-haiku-5-5", out=2000)],
            projects / "-home-u-Blog" / "s2.jsonl": [ans(t, model="claude-sonnet-5-5", cwd="/home/u/Blog")],
        }

    def report(self):
        return weekly_report.aggregate(self.START, self.END, self.samples(), self.events(), self.answers(),
                                       Path("/home/u/.claude/projects"))

    def test_accounts(self):
        r = self.report()
        perso = r.account("perso")
        self.assertEqual(perso.weekly_peak, 50.0)
        self.assertAlmostEqual(perso.weekly_used, 30 + 2 + 38)
        self.assertEqual(perso.windows, 2)          # fenêtres de 5 h entamées (la 3e est à 0 %)
        self.assertEqual(perso.session_hits, 1)
        self.assertEqual(perso.switches_to, 1)
        pro = r.account("pro")
        self.assertIsNone(pro.weekly_peak)
        self.assertEqual(pro.switches_to, 1)

    def test_activity_and_cost(self):
        r = self.report()
        self.assertEqual(r.conversations, 2)      # le sous-agent n'est pas une conversation
        self.assertEqual(r.sessions, 3)           # s1 : reprise après 2 h → 2 sessions ; s2 : 1
        self.assertEqual(r.cost.reponses, 5)
        self.assertAlmostEqual(r.cost.dollars, 3 * 0.02 + 2000 * 0.5 / 1e6 + 0.01)
        self.assertEqual(set(r.by_model), {"opus", "haiku", "sonnet"})
        self.assertEqual(max(r.by_project, key=r.by_project.get), "App")
        self.assertIn("Blog", r.by_project)

    def test_switches_and_alerts(self):
        r = self.report()
        self.assertEqual(r.switches, 2)
        self.assertEqual(r.switches_by_mode, {"auto": 1, "manual": 1})
        self.assertEqual(r.alerts, 2)
        self.assertEqual(r.alerts_by_kind, {"session80": 1, "session95": 1})
        self.assertEqual(r.blocages, 1)

    def test_text_notification_and_comparison(self):
        r = self.report()
        prev = weekly_report.WeekReport(self.START - WEEK, self.START, conversations=1,
                                        cost=costs.Cost({"entree": 0, "sortie": 2500, "cache_ecriture": 0,
                                                         "cache_lecture": 0}, 0.05, {}, False, 2))
        r.previous = prev
        text = weekly_report.format_text(r)
        self.assertTrue(text.startswith("Bilan de la semaine du 29 oct. au 5 nov."))
        self.assertIn("perso : semaine à 50 % au plus", text)
        self.assertIn("2 conversations, 3 sessions, 5 réponses", text)
        self.assertIn("2 bascules (1 automatique, 1 manuelle)", text)
        self.assertIn("2 alertes (1 session à 80 %, 1 session à 95 %)", text)
        self.assertIn("1 blocage", text)
        self.assertIn("Par rapport à la semaine précédente", text)
        self.assertIn("conversations : 2 (+1)", text)
        self.assertIn("tokens : 6,0 k (+140 %)", text)
        alert = weekly_report.notification(r, "weekly_report:2026-11-05")
        self.assertEqual(alert.urgency, 0)
        self.assertIn("2 conversations", alert.body)
        self.assertIn("perso 50 %", alert.body)
        self.assertIn("App", alert.body)
        self.assertLess(len(alert.body), 300)

    def test_big_numbers_stay_readable(self):
        self.assertEqual(weekly_report.fmt_tokens(2_384_300_000), "2,4 Md")
        self.assertEqual(weekly_report.fmt_tokens(6_000), "6,0 k")
        self.assertEqual(weekly_report._plural(10708, "réponse"), "10 708 réponses")
        self.assertEqual(weekly_report._plural(1, "réponse"), "1 réponse")

    def test_empty_week(self):
        r = weekly_report.aggregate(self.START, self.END, {}, [], {}, Path("/p"))
        text = weekly_report.format_text(r)
        self.assertIn("Aucune activité de Claude Code enregistrée", text)
        self.assertIn("aucune activité", weekly_report.notification(r, "k").body)


class BuildReportTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        costs.clear_cache()
        self.db = Store()
        self.addCleanup(self.db.close)
        self.projects = Path(tempfile.mkdtemp(prefix="ccs-week-"))
        self.addCleanup(shutil.rmtree, self.projects)
        self.end = datetime(2026, 11, 5, 9, 0).astimezone()
        self.start = self.end - WEEK
        reset = datetime.fromtimestamp((self.end + 2 * DAY).timestamp(), timezone.utc)
        for days, pct in ((1, 10.0), (3, 40.0), (6, 60.0)):
            self.db.add_samples((self.start + days * DAY).timestamp(), "perso",
                                [Limit("weekly_all", "W", pct, reset)])
        self.db.add_event((self.start + DAY).timestamp(), "switch", "pro", {"mode": "auto"})

    def journal(self, when):
        line = {"type": "assistant", "timestamp": when.isoformat(), "cwd": "/w/App",
                "message": {"id": f"m{when.timestamp():.0f}", "model": "claude-opus-5-5",
                            "usage": {"output_tokens": 1000}}}
        p = self.projects / "-w-App" / f"s{when.timestamp():.0f}.jsonl"
        write(p, json.dumps(line) + "\n")

    def test_build_with_previous_week(self):
        self.journal(self.start + DAY)
        self.journal(self.start - 2 * DAY)
        r = weekly_report.build_report(self.start, self.end, store=self.db, projects_dir=self.projects)
        self.assertEqual(r.account("perso").weekly_peak, 60.0)
        self.assertEqual(r.switches, 1)
        self.assertEqual(r.conversations, 1)
        self.assertIsNotNone(r.previous)
        self.assertEqual(r.previous.conversations, 1)
        self.assertIsNone(r.previous.previous)

    def test_has_data(self):
        self.assertTrue(weekly_report.has_data(self.start, self.end, store=self.db))
        self.assertFalse(weekly_report.has_data(self.start - WEEK, self.start, store=self.db))

    def test_has_data_without_history_file(self):
        self.db.close()
        (self.store / "history.db").unlink()
        self.assertFalse(weekly_report.has_data(self.start, self.end))
        self.assertFalse((self.store / "history.db").exists())


if __name__ == "__main__":
    unittest.main()
