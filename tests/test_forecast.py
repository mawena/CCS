import unittest
from datetime import datetime, timedelta, timezone

from ccs_app.core import Limit
from ccs_app.forecast import (AccountState, best_account, capacity, effective_percent,
                              session_forecast, weekly_pace)

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)


def at(minutes):
    return (NOW + timedelta(minutes=minutes)).timestamp()


def session(pct, reset_in_min):
    reset = NOW + timedelta(minutes=reset_in_min) if reset_in_min is not None else None
    return Limit("session", "Session (5 h)", pct, reset)


def weekly(pct, reset_in_days=4):
    return Limit("weekly_all", "Semaine", pct, NOW + timedelta(days=reset_in_days))


def acc(name, s=None, w=None, active=False, error=None, limits=None):
    if limits is None:
        limits = [x for x in (s, w) if x is not None]
    return AccountState(name, active, limits, NOW.timestamp(), error)


class SessionForecastTest(unittest.TestCase):
    def test_forecast_limit_before_reset(self):
        samples = [(at(-40), 30.0), (at(-20), 40.0), (at(0), 50.0)]
        fc = session_forecast(samples, session(50, 180), NOW)
        self.assertEqual(fc.verdict, "limit")
        self.assertAlmostEqual(fc.rate_per_min, 0.5)
        self.assertEqual(fc.eta, NOW + timedelta(minutes=100))
        self.assertAlmostEqual(fc.minutes_before_reset, 80)

    def test_forecast_ok_when_reset_first(self):
        samples = [(at(-30), 47.0), (at(0), 50.0)]
        fc = session_forecast(samples, session(50, 180), NOW)
        self.assertEqual(fc.verdict, "ok")
        self.assertIsNone(fc.minutes_before_reset)

    def test_forecast_stable(self):
        samples = [(at(-30), 50.0), (at(0), 50.0)]
        self.assertEqual(session_forecast(samples, session(50, 180), NOW).verdict, "stable")

    def test_forecast_unknown_with_one_point(self):
        fc = session_forecast([(at(0), 50.0)], session(50, 180), NOW)
        self.assertEqual(fc.verdict, "unknown")
        self.assertIsNone(fc.eta)

    def test_forecast_unknown_when_points_too_close(self):
        samples = [(at(-5), 40.0), (at(0), 50.0)]
        self.assertEqual(session_forecast(samples, session(50, 180), NOW).verdict, "unknown")

    def test_forecast_ignores_previous_window_points(self):
        # Fenêtre ouverte il y a 30 min (reset dans 4 h 30) : le point à -40 min
        # appartient à l'ancienne fenêtre et ne doit pas fausser la pente.
        samples = [(at(-40), 90.0), (at(-25), 5.0), (at(0), 10.0)]
        fc = session_forecast(samples, session(10, 270), NOW)
        self.assertAlmostEqual(fc.rate_per_min, 0.2)

    def test_forecast_without_limit(self):
        self.assertEqual(session_forecast([], None, NOW).verdict, "unknown")


class WeeklyPaceTest(unittest.TestCase):
    def test_weekly_pace_margin_and_budget(self):
        pace = weekly_pace(weekly(35, 4), NOW)
        self.assertAlmostEqual(pace.elapsed_frac, 3 / 7)
        self.assertAlmostEqual(pace.ideal, 300 / 7)
        self.assertAlmostEqual(pace.margin, 300 / 7 - 35)
        self.assertAlmostEqual(pace.per_day_budget, 16.25)
        self.assertAlmostEqual(pace.days_left, 4)

    def test_weekly_pace_none_without_reset(self):
        self.assertIsNone(weekly_pace(Limit("weekly_all", "W", 10, None), NOW))
        self.assertIsNone(weekly_pace(weekly(10, -1), NOW))


class CapacityAndBestTest(unittest.TestCase):
    def test_effective_percent_after_reset_is_zero(self):
        self.assertEqual(effective_percent(session(80, -1), NOW), 0)
        self.assertEqual(effective_percent(session(80, 10), NOW), 80)
        self.assertEqual(effective_percent(None, NOW), 0)

    def test_capacity_sums_accounts(self):
        accounts = [acc("a", session(31, 60), weekly(35)), acc("b", session(0, None), weekly(10))]
        self.assertAlmostEqual(capacity(accounts, NOW), 0.65 + 0.90)

    def test_capacity_ignores_accounts_without_data(self):
        accounts = [acc("a", session(50, 60)), acc("b", error="réseau", limits=[])]
        self.assertAlmostEqual(capacity(accounts, NOW), 0.5)

    def test_best_prefers_open_window_soonest_reset(self):
        accounts = [acc("idle", session(0, None), weekly(5)),
                    acc("late", session(10, 240), weekly(30)),
                    acc("soon", session(40, 120), weekly(30))]
        rec = best_account(accounts, NOW)
        self.assertEqual(rec.name, "soon")
        self.assertIn("fenêtre ouverte", rec.reason)

    def test_best_idle_by_weekly_margin(self):
        accounts = [acc("a", session(0, None), weekly(60)), acc("b", session(0, None), weekly(20))]
        rec = best_account(accounts, NOW)
        self.assertEqual(rec.name, "b")
        self.assertIn("au repos", rec.reason)

    def test_best_skips_exhausted_and_errors(self):
        accounts = [acc("full", session(95, 60), weekly(10)),
                    acc("broken", error="401", limits=[]),
                    acc("weekfull", session(5, 60), weekly(97)),
                    acc("ok", session(20, 60), weekly(10))]
        self.assertEqual(best_account(accounts, NOW).name, "ok")
        self.assertEqual(best_account(accounts, NOW, exclude={"ok"}), None)

    def test_best_treats_passed_reset_as_available(self):
        accounts = [acc("reset", session(100, -5), weekly(10))]
        self.assertEqual(best_account(accounts, NOW).name, "reset")

    def test_best_returns_none_when_all_exhausted(self):
        self.assertIsNone(best_account([acc("a", session(99, 60), weekly(10))], NOW))

    def test_account_state_without_session_limit(self):
        a = acc("w", limits=[weekly(42)])
        self.assertIsNone(a.session)
        self.assertEqual(a.weekly.percent, 42)
        self.assertEqual(a.max_percent, 42)

    def test_max_effective_uses_all_limits(self):
        a = acc("x", limits=[session(50, 60), weekly(99), Limit("weekly_opus", "O", 70, None)])
        self.assertEqual(a.max_effective(NOW), 99)
        b = acc("y", limits=[session(100, -1), weekly(30)])
        self.assertEqual(b.max_effective(NOW), 30)


class WindowOpenTest(unittest.TestCase):
    def test_window_open_at_zero_percent_when_reset_is_set(self):
        # Constaté le 26/10 : juste après un démarrage, l'API renvoie 0 % avec une heure de fin.
        from ccs_app.forecast import window_open
        self.assertTrue(window_open(acc("w", session(0, 290)), NOW))
        self.assertFalse(window_open(acc("w", session(0, None)), NOW))
        self.assertFalse(window_open(acc("w", session(40, -1)), NOW))


class WeeklyForecastTest(unittest.TestCase):
    """Fin de semaine prévue au rythme moyen depuis le début de la semaine."""

    def wf(self, pct, reset_in_days):
        from ccs_app.forecast import weekly_forecast
        return weekly_forecast(weekly(pct, reset_in_days), NOW)

    def test_limit_before_reset(self):
        # 3 jours écoulés, 60 % utilisés : 20 %/jour, 100 % dans 2 jours, 2 jours avant la fin.
        wf = self.wf(60, 4)
        self.assertEqual(wf.verdict, "limit")
        self.assertAlmostEqual(wf.rate_per_day, 20)
        self.assertEqual(wf.eta, NOW + timedelta(days=2))
        self.assertAlmostEqual(wf.days_before_reset, 2)

    def test_ok_when_reset_comes_first(self):
        wf = self.wf(30, 4)  # 10 %/jour : 100 % dans 7 jours, après la réinitialisation
        self.assertEqual(wf.verdict, "ok")
        self.assertAlmostEqual(wf.rate_per_day, 10)
        self.assertIsNone(wf.days_before_reset)

    def test_unused_week_is_ok(self):
        wf = self.wf(0, 4)
        self.assertEqual(wf.verdict, "ok")
        self.assertIsNone(wf.eta)

    def test_unknown_at_the_very_start_of_the_week(self):
        # 2 h 24 écoulées : le rythme d'un début de semaine n'est pas significatif.
        self.assertEqual(self.wf(10, 6.9).verdict, "unknown")

    def test_already_full(self):
        wf = self.wf(100, 4)
        self.assertEqual(wf.verdict, "limit")
        self.assertEqual(wf.eta, NOW)
        self.assertAlmostEqual(wf.days_before_reset, 4)

    def test_none_without_usable_limit(self):
        from ccs_app.forecast import weekly_forecast
        self.assertIsNone(weekly_forecast(None, NOW))
        self.assertIsNone(weekly_forecast(Limit("weekly_all", "W", 10, None), NOW))
        self.assertIsNone(weekly_forecast(weekly(10, -1), NOW))

    def test_as_dict_for_state(self):
        d = self.wf(60, 4).as_dict()
        self.assertEqual(d["verdict"], "limit")
        self.assertEqual(d["eta"], (NOW + timedelta(days=2)).isoformat())
        self.assertAlmostEqual(d["rate_per_day"], 20)
        self.assertAlmostEqual(d["days_before_reset"], 2)


class WeeklyForecastTextTest(unittest.TestCase):
    def test_fmt_when(self):
        from ccs_app.forecast import fmt_when
        local = NOW.astimezone()
        self.assertEqual(fmt_when(NOW, NOW), f"aujourd'hui à {local:%H:%M}")
        tomorrow = NOW + timedelta(days=1)
        self.assertEqual(fmt_when(tomorrow, NOW), f"demain à {tomorrow.astimezone():%H:%M}")
        later = (NOW + timedelta(days=3)).astimezone()
        self.assertIn(f" {later.day} ", fmt_when(later, NOW))
        self.assertTrue(fmt_when(later, NOW).endswith(f"à {later:%H:%M}"))

    def test_fmt_days(self):
        from ccs_app.forecast import fmt_days
        self.assertEqual(fmt_days(1.5), "1,5 j")
        self.assertEqual(fmt_days(0.25), "6 h")
        self.assertEqual(fmt_days(0.01), "moins d'une heure")

    def test_text_for_limit_and_ok(self):
        from ccs_app.forecast import weekly_forecast, weekly_forecast_text
        limit = weekly_forecast(weekly(60, 4), NOW).as_dict()
        text = weekly_forecast_text(limit, NOW)
        self.assertIn("limite prévue", text)
        self.assertIn("20 %/jour", text)
        self.assertIn("2,0 j avant la réinitialisation", text)
        ok = weekly_forecast_text(weekly_forecast(weekly(30, 4), NOW).as_dict(), NOW)
        self.assertIn("tient jusqu'à la réinitialisation", ok)
        self.assertIsNone(weekly_forecast_text(None, NOW))
        self.assertIsNone(weekly_forecast_text({"verdict": "unknown"}, NOW))
