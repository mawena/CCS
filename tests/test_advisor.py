import copy
import json
import math
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ccs_app import advisor, costs
from ccs_app.core import Limit, Profile
from ccs_app.settings import DEFAULTS
from ccs_app.store import Event, Store
from tests.helpers import HomeTestCase, write

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
H = 3600
DAY = 24 * H
WEEK = 7 * DAY


def weekly_series(start, end, first_reset, rate_per_h, step=H):
    """Relevés hebdomadaires : pourcentage qui monte de `rate_per_h` par heure depuis le
    début de la fenêtre (plafonné à 100), réinitialisé toutes les semaines."""
    out, reset, t = [], first_reset, start
    while t < end:
        while t >= reset:
            reset += WEEK
        pct = min(100.0, (t - (reset - WEEK)) / H * rate_per_h)
        out.append((t, pct, reset))
        t += step
    return out


def session_series(start, end, per_window, busy_h=3, step=H / 4):
    """Fenêtres de 5 h enchaînées : `per_window` % consommés pendant les `busy_h` premières heures."""
    out, t = [], start
    while t < end:
        window_start = start + ((t - start) // (5 * H)) * 5 * H
        elapsed = (t - window_start) / H
        pct = min(per_window, per_window * elapsed / busy_h)
        out.append((t, pct, window_start + 5 * H))
        t += step
    return out


def settings(**advisor_cfg):
    s = copy.deepcopy(DEFAULTS)
    s["advisor"].update(advisor_cfg)
    return s


class PlanDetectionTest(unittest.TestCase):
    def test_plan_keys(self):
        self.assertEqual(advisor.plan_key("pro"), "pro")
        self.assertEqual(advisor.plan_key("max", "default_claude_max_5x"), "max5")
        self.assertEqual(advisor.plan_key("max", "default_claude_max_20x"), "max20")
        self.assertEqual(advisor.plan_key("max"), "max5")
        self.assertEqual(advisor.plan_key("ultra"), "max20")
        self.assertIsNone(advisor.plan_key("team"))
        self.assertIsNone(advisor.plan_key("?"))

    def test_detect_plans_with_overrides(self):
        profiles = [Profile("perso", "a@x", "", "pro", True), Profile("boulot", "b@y", "", "max", False),
                    Profile("equipe", "c@z", "", "team", False)]
        plans, uncertain, unknown = advisor.detect_plans(profiles, {}, tiers={"boulot": None})
        self.assertEqual(plans, {"perso": "pro", "boulot": "max5"})
        self.assertEqual(uncertain, ["boulot"])
        self.assertEqual(unknown, [("equipe", "team")])
        plans, uncertain, _ = advisor.detect_plans(profiles, {"boulot": "max20", "perso": "n'importe"},
                                                   tiers={})
        self.assertEqual(plans["boulot"], "max20")
        self.assertEqual(plans["perso"], "pro")  # surcharge invalide ignorée
        self.assertEqual(uncertain, [])
        plans, uncertain, _ = advisor.detect_plans(profiles[1:2], {},
                                                   tiers={"boulot": "default_claude_max_20x"})
        self.assertEqual((plans, uncertain), ({"boulot": "max20"}, []))


class PricesTest(unittest.TestCase):
    def test_table_is_dated_and_sourced(self):
        self.assertRegex(advisor.PLAN_PRICES_DATE, r"^\d{4}-\d{2}-\d{2}$")
        self.assertIn("claude.com/pricing", advisor.PLAN_PRICES_SOURCE)
        self.assertEqual({k: p.price for k, p in advisor.PLANS.items()},
                         {"pro": 20.0, "max5": 100.0, "max20": 200.0})
        self.assertIsNone(advisor.PLANS["max20"].session)  # Ultra : pas de limite de 5 h

    def test_override_and_invalid_values(self):
        prices, custom = advisor.plan_prices(settings(plan_prices={"pro": 17, "max5": "cher",
                                                                   "max20": -1, "autre": 3}))
        self.assertEqual(prices, {"pro": 17.0, "max5": 100.0, "max20": 200.0})
        self.assertTrue(custom)
        self.assertEqual(advisor.plan_prices(settings()), ({"pro": 20.0, "max5": 100.0, "max20": 200.0}, False))

    def test_prices_become_stale(self):
        dated = datetime.fromisoformat(advisor.PLAN_PRICES_DATE).replace(tzinfo=timezone.utc)
        self.assertFalse(advisor.prices_stale(dated + timedelta(days=30)))
        self.assertTrue(advisor.prices_stale(dated + timedelta(days=advisor.PLAN_PRICES_MAX_AGE_DAYS + 1)))


class IncrementsTest(unittest.TestCase):
    R = 1_000_000.0

    def test_same_window(self):
        self.assertEqual(advisor.increments([(0, 10, self.R), (60, 30, self.R), (120, 30, self.R)]),
                         [(60, 20)])

    def test_reset_passed_counts_the_new_window_from_zero(self):
        self.assertEqual(advisor.increments([(0, 90, 100.0), (200, 5, 100.0 + WEEK)]), [(200, 5)])

    def test_jitter_on_reset_time_is_the_same_window(self):
        self.assertEqual(advisor.increments([(0, 50, self.R), (60, 50.5, self.R + 40)]), [(60, 0.5)])

    def test_drop_without_reset_time_is_a_new_window(self):
        self.assertEqual(advisor.increments([(0, 50, None), (60, 2, None)]), [(60, 2)])

    def test_first_sample_is_only_a_baseline(self):
        self.assertEqual(advisor.increments([(0, 40, self.R)]), [])
        self.assertEqual(advisor.increments([]), [])


class RecommendTest(unittest.TestCase):
    PRICES = {"pro": 20.0, "max5": 100.0, "max20": 200.0}

    def rec(self, weekly, session, max_accounts=3):
        return advisor.recommend(weekly, session, self.PRICES, max_accounts)

    def test_cheapest_fit(self):
        best, fits = self.rec(1.5, 1.2)
        self.assertEqual((best.label, best.price), ("2 Pro", 40.0))
        best, _ = self.rec(2.5, 1.0)
        self.assertEqual(best.label, "3 Pro")
        best, _ = self.rec(4.5, 2.0)
        self.assertEqual((best.label, best.price), ("Max", 100.0))
        best, _ = self.rec(0.5, 0.3)
        self.assertEqual(best.label, "Pro")

    def test_session_need_can_decide(self):
        best, _ = self.rec(0.8, 1.6)
        self.assertEqual(best.label, "2 Pro")

    def test_ultra_has_no_five_hour_limit(self):
        best, _ = self.rec(9.0, 40.0)
        self.assertEqual(best.label, "Ultra")
        self.assertTrue(math.isinf(best.session))
        best, _ = self.rec(12.0, 3.0)
        self.assertEqual((best.label, best.price), ("Ultra + 2 Pro", 240.0))

    def test_nothing_fits_gives_the_biggest(self):
        best, fits = self.rec(100.0, 1.0)
        self.assertEqual(fits, [])
        self.assertEqual(best.label, "3 Ultra")
        best, _ = self.rec(100.0, 1.0, max_accounts=1)
        self.assertEqual(best.label, "Ultra")

    def test_combo_of_current_plans(self):
        c = advisor.combo_of(["pro", "max5", "pro"], self.PRICES)
        self.assertEqual((c.label, c.price, c.weekly, c.session, c.accounts), ("Max + 2 Pro", 140.0, 7.0, 7.0, 3))


class AnalyzeTest(unittest.TestCase):
    def two_pro(self, rate_a=0.5, rate_b=0.25, per_window=60, start=None):
        start = start if start is not None else NOW.timestamp() - 15 * DAY
        end = NOW.timestamp()
        return {
            "perso": {"weekly_all": weekly_series(start, end, start + 2 * DAY, rate_a),
                      "session": session_series(start, end, per_window)},
            "boulot": {"weekly_all": weekly_series(start, end, start + 5 * DAY, rate_b),
                       "session": session_series(start, end, per_window)},
        }

    def analyze(self, samples, plans=None, cfg=None, **kw):
        return advisor.analyze(samples, plans or {"perso": "pro", "boulot": "pro"}, NOW,
                               cfg or settings(weeks=2), **kw)

    def test_needs_per_week_and_recommendation(self):
        a = self.analyze(self.two_pro())
        self.assertTrue(a.enough_data)
        self.assertEqual(len(a.weeks), 2)
        for w in a.weeks:
            self.assertAlmostEqual(w.weekly, 0.84 + 0.42, delta=0.02)
            self.assertAlmostEqual(w.session_peak, 1.2, delta=0.05)
            self.assertEqual(w.limit_hits, 0)
            self.assertAlmostEqual(w.coverage, 1.0)
        self.assertAlmostEqual(a.weekly_target, 1.26 * 1.2, delta=0.03)
        self.assertEqual(a.recommended.label, "2 Pro")
        self.assertEqual(a.current.label, "2 Pro")
        self.assertAlmostEqual(a.unused_share, 1 - 1.26 / 2, delta=0.02)
        text = "\n".join(a.reasons)
        self.assertIn("ta formule actuelle", text)
        self.assertIn("Aucune limite atteinte", text)
        self.assertIn("20 % de marge", text)

    def test_limits_and_blocking_raise_the_need(self):
        samples = self.two_pro(rate_a=0.6, rate_b=0.6)
        ev = [Event(NOW.timestamp() - 3 * DAY, "alert", None, {"key": "exhausted:perso:123"}),
              Event(NOW.timestamp() - 2 * DAY, "alert", "blocage", {"key": "blocage:1"}),
              Event(NOW.timestamp() - 2 * DAY + 60, "switch", "boulot", {"mode": "blocage"}),
              Event(NOW.timestamp() - 9 * DAY, "alert", "blocage", {"key": "deja"})]
        a = self.analyze(samples, events=ev)
        recent, older = a.weeks
        self.assertEqual(recent.blocked, 1)  # le blocage suivi d'une bascule ne compte pas
        self.assertEqual(older.blocked, 0)
        self.assertGreaterEqual(recent.limit_hits, 1)
        self.assertAlmostEqual(recent.need, recent.weekly * (1 + advisor.CAPPED_BONUS))
        self.assertEqual(a.recommended.label, "3 Pro")
        text = "\n".join(a.reasons)
        self.assertIn("Limite atteinte", text)
        self.assertIn("Bloqué sans autre compte", text)
        self.assertIn("20 $/mois de plus", text)

    def test_overpaying_max_for_light_usage(self):
        start = NOW.timestamp() - 15 * DAY
        samples = {"perso": {"weekly_all": weekly_series(start, NOW.timestamp(), start + DAY, 0.08),
                             "session": session_series(start, NOW.timestamp(), 10)}}
        a = self.analyze(samples, plans={"perso": "max5"})
        self.assertAlmostEqual(a.weeks[0].weekly, 0.08 * 168 / 100 * 5, delta=0.03)
        self.assertEqual(a.recommended.label, "Pro")
        self.assertEqual(a.current.label, "Max")
        self.assertGreater(a.unused_share, 0.8)
        self.assertIn("80 $/mois d'économie", "\n".join(a.reasons))

    def test_single_account_alternative_when_several_accounts_are_advised(self):
        a = self.analyze(self.two_pro(rate_a=0.6, rate_b=0.6))
        self.assertEqual(a.recommended.label, "3 Pro")
        self.assertEqual([c.label for c in a.alternatives], ["Max"])
        self.assertIn("Sans bascule", "\n".join(a.reasons))

    def test_partial_week_is_scaled_and_short_history_is_not_enough(self):
        a = self.analyze(self.two_pro(start=NOW.timestamp() - 5 * DAY))
        self.assertEqual(len(a.weeks), 1)  # l'autre semaine n'a aucun relevé
        self.assertAlmostEqual(a.weeks[0].coverage, 5 / 7)
        self.assertAlmostEqual(a.weeks[0].need, a.weeks[0].weekly * 7 / 5)
        a = self.analyze(self.two_pro(start=NOW.timestamp() - 2 * DAY))
        self.assertFalse(a.enough_data)
        self.assertIsNone(a.recommended)
        self.assertIn("Pas assez de relevés", "\n".join(a.reasons))

    def test_api_equivalent_and_prices_note(self):
        api = costs.Cost({"entree": 0, "sortie": 0, "cache_ecriture": 0, "cache_lecture": 0}, 812.0, {}, False, 10)
        a = self.analyze(self.two_pro(), api=api, api_days=14)
        text = "\n".join(a.reasons)
        self.assertAlmostEqual(a.api_monthly, 812.0 * 30.44 / 14)
        self.assertIn("Équivalent API", text)
        self.assertIn("40 $/mois", text)
        self.assertIn("claude.com/pricing", text)
        self.assertNotIn("à vérifier", text)

    def test_uncertain_and_unknown_plans_are_explained(self):
        a = self.analyze(self.two_pro(), uncertain=["boulot"], unknown=[("equipe", "team")])
        text = "\n".join(a.reasons)
        self.assertIn("« boulot » : Max supposé", text)
        self.assertIn("advisor.profile_plans", text)
        self.assertIn("« equipe »", text)

    def test_format_text(self):
        text = advisor.format_text(self.analyze(self.two_pro()))
        self.assertTrue(text.startswith("Conseiller de formule"))
        self.assertIn("Conseil : 2 Pro — 40 $/mois", text)
        self.assertIn("• ", text)


class ComputeTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.db = Store()
        self.addCleanup(self.db.close)
        self.projects = Path(tempfile.mkdtemp(prefix="ccs-advisor-"))
        self.addCleanup(shutil.rmtree, self.projects)
        costs.clear_cache()
        start = NOW.timestamp() - 15 * DAY
        for name, rate in (("perso", 0.5), ("pro", 0.05)):
            for ts, pct, reset in weekly_series(start, NOW.timestamp(), start + DAY, rate):
                self.db.add_samples(ts, name, [Limit("weekly_all", "W", pct,
                                                     datetime.fromtimestamp(reset, timezone.utc))])

    def test_compute_reads_store_profiles_and_journals(self):
        line = {"type": "assistant", "timestamp": (NOW - timedelta(days=1)).isoformat(), "cwd": "/w/App",
                "message": {"id": "m1", "model": "claude-opus-5-5",
                            "usage": {"input_tokens": 0, "output_tokens": 1_000_000}}}
        write(self.projects / "-w-App" / "s1.jsonl", json.dumps(line) + "\n")
        a = advisor.compute(now=NOW, settings=settings(weeks=2), store=self.db, projects_dir=self.projects)
        self.assertEqual(a.plans, {"perso": "pro", "pro": "max5"})
        self.assertEqual(a.uncertain, ["pro"])
        self.assertEqual(a.api.reponses, 1)
        self.assertAlmostEqual(a.api.dollars, 20.0)
        self.assertAlmostEqual(a.weeks[0].weekly, 0.84 + 0.084 * 5, delta=0.05)
        self.assertEqual(a.current.label, "Max + Pro")

    def test_profile_plans_override(self):
        s = settings(weeks=2, profile_plans={"pro": "max20"})
        a = advisor.compute(now=NOW, settings=s, store=self.db, projects_dir=self.projects, with_api=False)
        self.assertEqual(a.plans["pro"], "max20")
        self.assertEqual(a.uncertain, [])
        self.assertIsNone(a.api)


if __name__ == "__main__":
    unittest.main()
