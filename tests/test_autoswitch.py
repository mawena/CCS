import copy
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from ccs_app import autoswitch
from ccs_app.autoswitch import Decision, decide
from ccs_app.core import Limit
from ccs_app.forecast import AccountState, SessionForecast
from ccs_app.settings import DEFAULTS
from ccs_app.store import Event

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)
T = NOW.timestamp()


def acc(name, s, w=10, reset_min=120, active=False, age_s=30):
    limits = [Limit("session", "S", s, NOW + timedelta(minutes=reset_min)),
              Limit("weekly_all", "W", w, NOW + timedelta(days=3))]
    return AccountState(name, active, limits, T - age_s, None)


def ev(ago_s, profile, **detail):
    return Event(T - ago_s, "switch", profile, detail)


class DecideTest(unittest.TestCase):
    def setUp(self):
        self.settings = copy.deepcopy(DEFAULTS)

    def run_decide(self, accounts, active="perso", fc=None, events=(), poll_s=60):
        return decide(accounts, active, fc, self.settings, NOW, list(events), poll_s)

    def test_no_switch_below_threshold(self):
        d = self.run_decide([acc("perso", 90, active=True), acc("pro", 10)])
        self.assertEqual(d.action, "none")

    def test_switch_at_threshold_to_best(self):
        d = self.run_decide([acc("perso", 98, active=True), acc("pro", 10), acc("full", 85)])
        self.assertEqual((d.action, d.target), ("switch", "pro"))
        self.assertEqual(d.source, "perso")
        self.assertEqual(d.source_reset, (NOW + timedelta(minutes=120)).timestamp())

    def test_switch_on_projection(self):
        # 96 % + 5 %/min sur 60 s = 101 % au prochain relevé → bascule maintenant.
        fc = SessionForecast(5.0, None, "limit", 0)
        d = self.run_decide([acc("perso", 96, active=True), acc("pro", 10)], fc=fc, poll_s=60)
        self.assertEqual(d.action, "switch")
        # 96 % + 2 %/min = 98 % : le prochain relevé déclenchera au seuil.
        d = self.run_decide([acc("perso", 96, active=True), acc("pro", 10)],
                            fc=SessionForecast(2.0, None, "limit", 0), poll_s=60)
        self.assertEqual(d.action, "none")

    def test_disabled(self):
        self.settings["auto_switch"]["enabled"] = False
        d = self.run_decide([acc("perso", 99, active=True), acc("pro", 10)])
        self.assertEqual(d.action, "none")

    def test_respects_cooldown_after_auto_switch(self):
        events = [ev(120, "perso", mode="auto", **{"from": "other", "from_reset": None})]
        d = self.run_decide([acc("perso", 99, active=True), acc("pro", 10)], events=events)
        self.assertEqual(d.action, "none")
        self.assertIn("récente", d.reason)

    def test_respects_recent_manual_switch_unless_995(self):
        events = [ev(60, "perso", mode="manual")]
        d = self.run_decide([acc("perso", 99, active=True), acc("pro", 10)], events=events)
        self.assertEqual(d.action, "none")
        d = self.run_decide([acc("perso", 99.6, active=True), acc("pro", 10)], events=events)
        self.assertEqual(d.action, "switch")

    def test_no_return_to_exhausted_account_before_reset(self):
        # pro a été quitté pour épuisement ; sa fenêtre de l'époque n'est pas finie.
        events = [ev(3600, "perso", mode="auto",
                     **{"from": "pro", "from_reset": T + 600})]
        accounts = [acc("perso", 99, active=True), acc("pro", 10), acc("third", 50)]
        d = self.run_decide(accounts, events=events)
        self.assertEqual(d.target, "third")
        # Après le reset de l'époque, pro redevient éligible.
        events = [ev(3600, "perso", mode="auto", **{"from": "pro", "from_reset": T - 1})]
        self.assertEqual(self.run_decide(accounts, events=events).target, "pro")

    def test_exhausted_when_no_target(self):
        d = self.run_decide([acc("perso", 99, active=True), acc("pro", 85, reset_min=30)])
        self.assertEqual(d.action, "exhausted")
        self.assertIn("prochain disponible", d.reason)
        self.assertIn("pro", d.reason)

    def test_stale_data_never_switches(self):
        d = self.run_decide([acc("perso", 99, active=True, age_s=900), acc("pro", 10)])
        self.assertEqual(d.action, "none")

    def test_unsaved_active_account_never_switches(self):
        d = self.run_decide([acc("perso", 99), acc("pro", 10)], active=None)
        self.assertEqual(d.action, "none")

    def test_uses_max_of_all_limits(self):
        d = self.run_decide([acc("perso", 50, w=99, active=True), acc("pro", 10)])
        self.assertEqual((d.action, d.target), ("switch", "pro"))

    def test_passed_reset_does_not_trigger(self):
        d = self.run_decide([acc("perso", 100, reset_min=-1, active=True), acc("pro", 10)])
        self.assertEqual(d.action, "none")


class ExecuteTest(unittest.TestCase):
    def test_execute_runs_ccs_and_logs_event(self):
        store = mock.Mock()
        d = Decision("switch", "pro", "raison", "perso", 123.0)
        ok = subprocess.CompletedProcess([], 0, "✔ basculé", "")
        with mock.patch.object(autoswitch.core, "run_ccs", return_value=ok) as run:
            self.assertTrue(autoswitch.execute(d, store, NOW))
        run.assert_called_once_with(["use", "pro"])
        store.add_event.assert_called_once_with(
            T, "switch", "pro", {"mode": "auto", "from": "perso", "from_reset": 123.0,
                                 "reason": "raison"})

    def test_execute_failure_logs_error(self):
        store = mock.Mock()
        d = Decision("switch", "pro", "r", "perso", None)
        ko = subprocess.CompletedProcess([], 1, "", "ccs: erreur")
        with mock.patch.object(autoswitch.core, "run_ccs", return_value=ko):
            self.assertFalse(autoswitch.execute(d, store, NOW))
        self.assertEqual(store.add_event.call_args.args[1], "error")

    def test_execute_none_does_nothing(self):
        store = mock.Mock()
        self.assertFalse(autoswitch.execute(Decision("none", None, "", None, None), store, NOW))
        store.add_event.assert_not_called()


class TargetEligibilityTest(unittest.TestCase):
    """Revue finale C2 : une cible périmée ou en erreur n'est jamais choisie."""

    def setUp(self):
        self.settings = copy.deepcopy(DEFAULTS)

    def test_stale_target_is_never_chosen(self):
        accounts = [acc("perso", 99, active=True), acc("pro", 5, age_s=3 * 86400)]
        d = decide(accounts, "perso", None, self.settings, NOW, [], 60)
        self.assertNotEqual(d.action, "switch")

    def test_auth_error_target_is_never_chosen(self):
        revoked = acc("pro", 5)
        revoked.error = "connexion expirée ou révoquée : supprime ce profil"
        d = decide([acc("perso", 99, active=True), revoked], "perso", None, self.settings, NOW, [], 60)
        self.assertNotEqual(d.action, "switch")

    def test_fresh_target_still_chosen_among_stale(self):
        accounts = [acc("perso", 99, active=True), acc("old", 1, age_s=3600), acc("ok", 30)]
        d = decide(accounts, "perso", None, self.settings, NOW, [], 60)
        self.assertEqual(d.target, "ok")


class ReserveDecideTest(unittest.TestCase):
    def test_threshold_switch_prefers_non_reserve(self):
        s = copy.deepcopy(DEFAULTS)
        accounts = [acc("perso", 99, active=True), acc("pro", 10, reset_min=60), acc("third", 40, reset_min=200)]
        d = decide(accounts, "perso", None, s, NOW, [], 60, reserve={"pro"})
        self.assertEqual(d.target, "third")
