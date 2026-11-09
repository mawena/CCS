import unittest
from datetime import datetime, timedelta, timezone

from ccs_app import best_time

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat()


def acct(name, sess=None, sess_in=None, week=10.0, week_in=timedelta(days=4), error=None,
         fetched=NOW):
    """sess : % de session utilisé (None = pas de fenêtre en cours) ; sess_in : délai de réinit."""
    limits = []
    if sess is not None:
        limits.append({"kind": "session", "label": "Session (5 h)", "percent": sess,
                       "resets_at": iso(NOW + sess_in)})
    if week is not None:
        limits.append({"kind": "weekly_all", "label": "Semaine", "percent": week,
                       "resets_at": iso(NOW + week_in)})
    return {"name": name, "limits": limits, "error": error,
            "fetched_at": fetched.timestamp()}


def state(*accounts, **extra):
    return {"updated_at": NOW.timestamp(), "accounts": list(accounts), **extra}


def H(h):
    return timedelta(hours=h)


class ScoreTest(unittest.TestCase):
    def score(self, st, start_h=0, duration=3):
        r = best_time.compute(st, duration_h=duration, span_h=24, now=NOW)
        return {s.start: s.score for s in r.curve}[NOW + H(start_h)]

    def test_live_window_gives_what_remains(self):
        st = state(acct("perso", sess=40, sess_in=H(4)))
        self.assertAlmostEqual(self.score(st), 0.6)

    def test_window_reset_during_task_adds_a_fresh_window(self):
        st = state(acct("perso", sess=80, sess_in=H(1)))
        self.assertAlmostEqual(self.score(st), 0.2 + 1.0)

    def test_idle_account_starts_a_fresh_window_at_departure(self):
        st = state(acct("perso", sess=None))
        self.assertAlmostEqual(self.score(st, 2), 1.0)

    def test_expired_window_counts_as_idle(self):
        st = state(acct("perso", sess=90, sess_in=H(1)))
        # départ après la réinitialisation : fenêtre neuve
        self.assertAlmostEqual(self.score(st, 2), 1.0)

    def test_task_longer_than_a_window_chains_windows(self):
        st = state(acct("perso", sess=None))
        self.assertAlmostEqual(self.score(st, 0, duration=10), 2.0)

    def test_late_window_counts_only_in_proportion(self):
        # fenêtre qui ne laisse que 30 min avant la fin de la tâche
        st = state(acct("perso", sess=100, sess_in=H(2.5)))
        self.assertAlmostEqual(self.score(st, 0, duration=3), 0.5)

    def test_accounts_add_up(self):
        st = state(acct("a", sess=50, sess_in=H(4)), acct("b", sess=None))
        self.assertAlmostEqual(self.score(st), 1.5)

    def test_weekly_exhausted_account_contributes_nothing(self):
        st = state(acct("a", sess=None, week=100), acct("b", sess=None))
        self.assertAlmostEqual(self.score(st), 1.0)

    def test_weekly_exhausted_account_comes_back_after_weekly_reset(self):
        st = state(acct("a", sess=None, week=100, week_in=H(6)))
        self.assertAlmostEqual(self.score(st, 0), 0.0)
        self.assertAlmostEqual(self.score(st, 7), 1.0)

    def test_weekly_remainder_caps_the_total(self):
        # 1 % de semaine restant : bien moins qu'une fenêtre
        st = state(acct("a", sess=None, week=99))
        self.assertLess(self.score(st, 0, duration=10), 0.5)

    def test_error_accounts_are_ignored_but_listed(self):
        st = state(acct("a", sess=None, error="connexion révoquée"), acct("b", sess=None))
        r = best_time.compute(st, now=NOW)
        self.assertAlmostEqual(r.curve[0].score, 1.0)
        self.assertEqual([n for n, _ in r.ignored], ["a"])

    def test_transient_errors_keep_the_data(self):
        st = state(acct("a", sess=None, error="HTTP 429"))
        r = best_time.compute(st, now=NOW)
        self.assertAlmostEqual(r.curve[0].score, 1.0)
        self.assertEqual(r.ignored, [])

    def test_no_usable_account(self):
        r = best_time.compute(state(acct("a", error="connexion révoquée")), now=NOW)
        self.assertIsNone(r.best)
        self.assertIn("Aucun compte", best_time.format_text(r))


class RankingTest(unittest.TestCase):
    def test_best_start_is_when_windows_reset_during_the_task(self):
        st = state(acct("a", sess=100, sess_in=H(4)))
        r = best_time.compute(st, duration_h=3, now=NOW)
        # réinit à 16:00 : une heure de recouvrement suffit, donc départ dès 14:00
        self.assertEqual(r.best.start, NOW + H(2))
        self.assertAlmostEqual(r.best.score, 1.0)
        self.assertFalse(r.now_is_best)

    def test_now_wins_when_within_ten_percent(self):
        st = state(acct("a", sess=5, sess_in=H(40)))   # 0,95 maintenant, rien de mieux
        r = best_time.compute(st, duration_h=3, now=NOW)
        self.assertTrue(r.now_is_best)
        self.assertEqual(r.best.start, NOW)
        self.assertIn("maintenant", best_time.format_text(r))

    def test_ties_pick_earliest(self):
        st = state(acct("a", sess=None))
        r = best_time.compute(st, now=NOW)
        self.assertEqual(r.best.start, NOW)

    def test_alternatives_are_distinct_and_spaced(self):
        st = state(acct("a", sess=100, sess_in=H(4)), acct("b", sess=100, sess_in=H(10)))
        r = best_time.compute(st, duration_h=3, now=NOW)
        starts = [r.best.start] + [s.start for s in r.alternatives]
        self.assertEqual(len(set(starts)), len(starts))
        self.assertLessEqual(len(r.alternatives), 3)
        for i, a in enumerate(starts):
            for b in starts[i + 1:]:
                self.assertGreaterEqual(abs((a - b).total_seconds()), 5400)

    def test_candidates_every_fifteen_minutes(self):
        st = state(acct("a", sess=None))
        r = best_time.compute(st, span_h=2, now=NOW + timedelta(minutes=7))
        starts = [s.start for s in r.curve]
        self.assertEqual(starts[0], NOW + timedelta(minutes=7))
        self.assertEqual(starts[1], NOW + timedelta(minutes=15))
        self.assertEqual(starts[2] - starts[1], timedelta(minutes=15))
        self.assertLess(starts[-1], NOW + timedelta(minutes=7) + H(2))

    def test_everything_exhausted_has_no_best(self):
        st = state(acct("a", sess=None, week=100, week_in=H(100)))
        r = best_time.compute(st, span_h=24, now=NOW)
        self.assertIsNone(r.best)
        self.assertIn("Aucun quota", best_time.format_text(r))

    def test_pause_is_reported(self):
        st = state(acct("a", sess=None), pause={"since": iso(NOW), "until": None, "label": "manuelle"})
        r = best_time.compute(st, now=NOW)
        self.assertTrue(r.paused)
        self.assertIn("pause", best_time.format_text(r))


class ExplainTest(unittest.TestCase):
    def test_explanation_names_accounts(self):
        st = state(acct("perso", sess=100, sess_in=timedelta(hours=2, minutes=5)),
                   acct("pro", sess=40, sess_in=H(40)),
                   acct("travail", sess=None, week=100, week_in=H(100)))
        r = best_time.compute(st, duration_h=3, now=NOW)
        text = r.best.text
        self.assertIn("perso repart à neuf à", text)
        self.assertIn("pro a encore 60 %", text)
        self.assertIn("travail : semaine épuisée", text)
        self.assertIn("fenêtre", text)

    def test_french_decimal_comma(self):
        self.assertEqual(best_time.windows_text(1.8), "1,8 fenêtre de 5 h")
        self.assertEqual(best_time.windows_text(2.0), "2 fenêtres de 5 h")


class CommandTest(unittest.TestCase):
    ST = state(acct("a", sess=None))

    def test_default(self):
        code, text = best_time.command([], state=self.ST, now=NOW)
        self.assertEqual(code, 0)
        self.assertIn("3 h", text)

    def test_options(self):
        code, text = best_time.command(["--duree", "6h", "--sur", "12h"], state=self.ST, now=NOW)
        self.assertEqual(code, 0)
        self.assertIn("6 h", text)
        self.assertIn("12 h", text)
        code, _ = best_time.command(["--duree=90m"], state=self.ST, now=NOW)
        self.assertEqual(code, 0)

    def test_usage_errors(self):
        for args in (["--duree", "12h"], ["--duree", "30m"], ["--duree", "abc"], ["--duree"],
                     ["--sur", "100h"], ["--bof"], ["x"]):
            code, text = best_time.command(args, state=self.ST, now=NOW)
            self.assertEqual(code, 2, args)
            self.assertIn("usage", text)

    def test_no_state(self):
        code, text = best_time.command([], state={}, now=NOW)
        self.assertEqual(code, 1)

    def test_parse_duration(self):
        p = best_time.parse_hours
        self.assertEqual(p("3h"), 3.0)
        self.assertEqual(p("2h30"), 2.5)
        self.assertEqual(p("90m"), 1.5)
        self.assertEqual(p("4"), 4.0)
        self.assertEqual(p("1,5h"), 1.5)
        self.assertIsNone(p("x"))


if __name__ == "__main__":
    unittest.main()
