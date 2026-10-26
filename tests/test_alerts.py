import copy
import unittest
from datetime import datetime, timedelta, timezone

from ccs_app.alerts import decision_alert, pending_alerts
from ccs_app.autoswitch import Decision
from ccs_app.core import Limit
from ccs_app.forecast import AccountState, Recommendation, SessionForecast, weekly_pace
from ccs_app.settings import DEFAULTS

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)
RESET = NOW + timedelta(hours=2)


def session(pct, reset=RESET):
    return Limit("session", "S", pct, reset)


def state(name, s, active=False, w=10, error=None):
    limits = [session(s), Limit("weekly_all", "W", w, NOW + timedelta(days=4))] if s is not None else []
    return AccountState(name, active, limits, NOW.timestamp(), error)


class AlertsTest(unittest.TestCase):
    def setUp(self):
        self.settings = copy.deepcopy(DEFAULTS)

    def alerts(self, accounts, active="perso", fc=None, best=None, sent=(), previous=None, paces=None):
        return pending_alerts(accounts, active, fc, paces or {}, best, self.settings, NOW,
                              set(sent), previous or {})

    def keys(self, alerts):
        return [a.key.split(":")[0] for a in alerts]

    def test_session_80_then_95_once_each(self):
        a80 = self.alerts([state("perso", 82, True)])
        self.assertEqual(self.keys(a80), ["session80"])
        sent = {a80[0].key}
        a95 = self.alerts([state("perso", 96, True)], sent=sent)
        self.assertEqual(self.keys(a95), ["session95"])
        self.assertEqual(a95[0].urgency, 2)
        sent.add(a95[0].key)
        self.assertEqual(self.alerts([state("perso", 97, True)], sent=sent), [])

    def test_jumping_straight_to_95_sends_only_95(self):
        a = self.alerts([state("perso", 96, True)])
        self.assertEqual(self.keys(a), ["session95"])
        self.assertEqual(self.alerts([state("perso", 97, True)], sent={a[0].key}), [])

    def test_no_duplicate_when_key_already_sent(self):
        first = self.alerts([state("perso", 82, True)])
        self.assertEqual(self.alerts([state("perso", 83, True)], sent={first[0].key}), [])

    def test_key_stable_despite_reset_jitter(self):
        first = self.alerts([state("perso", 82, True)])
        jittered = AccountState("perso", True, [session(83, RESET + timedelta(seconds=40))],
                                NOW.timestamp(), None)
        self.assertEqual(self.alerts([jittered], sent={first[0].key}), [])

    def test_inactive_accounts_get_no_session_alert(self):
        self.assertEqual(self.alerts([state("perso", 10, True), state("pro", 90)]), [])

    def test_eta_alert_under_20_min(self):
        fc = SessionForecast(2.0, NOW + timedelta(minutes=15), "limit", 105)
        a = self.alerts([state("perso", 70, True)], fc=fc)
        self.assertEqual(self.keys(a), ["eta"])
        self.assertIn("vers", a[0].body)
        fc_far = SessionForecast(0.5, NOW + timedelta(minutes=60), "limit", 60)
        self.assertEqual(self.alerts([state("perso", 70, True)], fc=fc_far), [])

    def test_reset_alert_when_session_back_to_zero(self):
        previous = {"pro": session(90, NOW - timedelta(minutes=1))}
        a = self.alerts([state("perso", 10, True), state("pro", 0)], previous=previous)
        self.assertEqual(self.keys(a), ["reset"])
        self.assertIn("pro", a[0].title)

    def test_reset_alert_when_reset_moves_forward(self):
        previous = {"pro": session(90, NOW - timedelta(minutes=1))}
        new = AccountState("pro", False, [session(3, NOW + timedelta(hours=5))], NOW.timestamp(), None)
        self.assertEqual(self.keys(self.alerts([new], active=None, previous=previous)), ["reset"])

    def test_no_reset_alert_when_previous_was_zero(self):
        previous = {"pro": session(0, None)}
        self.assertEqual(self.alerts([state("pro", 0)], active=None, previous=previous), [])

    def test_weekly_ahead_15_points(self):
        acc = state("perso", 10, True, w=60)  # 3/7 de semaine écoulée ≈ 42.9 % idéal
        paces = {"perso": weekly_pace(acc.weekly, NOW)}
        a = self.alerts([acc], paces=paces)
        self.assertEqual(self.keys(a), ["weekly_ahead"])
        acc_ok = state("perso", 10, True, w=50)
        self.assertEqual(self.alerts([acc_ok], paces={"perso": weekly_pace(acc_ok.weekly, NOW)}), [])

    def test_auth_alert(self):
        acc = state("pro", None, error="connexion expirée ou révoquée : supprime ce profil")
        self.assertEqual(self.keys(self.alerts([acc], active=None)), ["auth"])

    def test_disabled_types_are_skipped(self):
        self.settings["alerts"]["resets"] = False
        previous = {"pro": session(90, NOW - timedelta(minutes=1))}
        self.assertEqual(self.alerts([state("pro", 0)], active=None, previous=previous), [])
        self.settings["alerts"]["enabled"] = False
        self.assertEqual(self.alerts([state("perso", 99, True)]), [])

    def test_80_alert_body_suggests_best_account(self):
        best = Recommendation("pro", "au repos, semaine à 5 %")
        a = self.alerts([state("perso", 82, True)], best=best)
        self.assertIn("pro", a[0].body)
        self.assertIn("ccs pro", a[0].body)


class DecisionAlertTest(unittest.TestCase):
    def test_switch_and_exhausted(self):
        sw = decision_alert(Decision("switch", "pro", "perso à 98 % → pro", "perso", None), NOW)
        self.assertEqual(sw.urgency, 1)
        self.assertIn("pro", sw.body)
        ex = decision_alert(Decision("exhausted", None, "tous épuisés", "perso", RESET.timestamp()), NOW)
        self.assertEqual(ex.urgency, 2)
        self.assertTrue(ex.key.startswith("exhausted:perso:"))
        self.assertIsNone(decision_alert(Decision("none", None, ""), NOW))


class ResetNoiseTest(AlertsTest):
    def test_reset_alert_only_after_heavy_use(self):
        prev60 = {"pro": session(60, NOW - timedelta(minutes=1))}
        self.assertEqual(self.alerts([state("pro", 0)], active=None, previous=prev60), [])
        prev85 = {"pro": session(85, NOW - timedelta(minutes=1))}
        self.assertEqual(self.keys(self.alerts([state("pro", 0)], active=None, previous=prev85)), ["reset"])
