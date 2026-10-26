import copy
import unittest
from datetime import datetime, timedelta

from ccs_app import orchestrator as orch
from ccs_app.core import Limit
from ccs_app.forecast import AccountState, WeeklyPace, best_account
from ccs_app.settings import DEFAULTS
from ccs_app.store import Event


def local(day, hh, mm=0):
    """Heure locale du 26/10/2026 (lundi) + `day` jours."""
    return (datetime(2026, 10, 26, hh, mm) + timedelta(days=day)).astimezone()


NOW = local(0, 10)


def acc(name, s=0.0, reset_min=None, w=10.0, age=30, error=None, now=NOW, active=False):
    reset = now + timedelta(minutes=reset_min) if reset_min is not None else None
    limits = [Limit("session", "S", s, reset), Limit("weekly_all", "W", w, now + timedelta(days=3))]
    return AccountState(name, active, limits, now.timestamp() - age, error)


def cfg(**over):
    c = copy.deepcopy(DEFAULTS["orchestrator"])
    c["enabled"] = True
    c.update(over)
    return c


class FakeStore:
    def __init__(self, events=()):
        self._events = list(events)

    def events(self, since, type=None, profile=None):
        return [e for e in self._events if e.ts >= since and (type is None or e.type == type)
                and (profile is None or e.profile == profile)]


class PeriodTest(unittest.TestCase):
    hours = DEFAULTS["orchestrator"]["active_hours"]

    def test_daytime_inside_overnight_range(self):
        self.assertEqual(orch.period_bounds(NOW, self.hours), (local(0, 8), local(1, 2)))

    def test_after_midnight_belongs_to_previous_day(self):
        self.assertEqual(orch.period_bounds(local(1, 1, 30), self.hours), (local(0, 8), local(1, 2)))

    def test_outside_range(self):
        self.assertIsNone(orch.period_bounds(local(1, 3), self.hours))

    def test_simple_range_and_days(self):
        h = {"start": "09:00", "end": "18:00", "days": [0]}
        self.assertEqual(orch.period_bounds(local(0, 12), h), (local(0, 9), local(0, 18)))
        self.assertIsNone(orch.period_bounds(local(0, 19), h))
        self.assertIsNone(orch.period_bounds(local(1, 12), h))  # mardi exclu


class SlotsTest(unittest.TestCase):
    def test_participants_exclude_error_stale_and_weekly_full(self):
        accounts = [acc("b"), acc("a"), acc("err", error="401"), acc("old", age=3600), acc("full", w=96)]
        self.assertEqual(orch.participants(accounts, NOW, cfg()), ["a", "b"])

    def test_two_accounts_are_staggered(self):
        slots = orch.first_slots([acc("b"), acc("a")], NOW, cfg())
        self.assertEqual(slots, {"a": local(0, 8), "b": local(0, 10, 30)})

    def test_single_account_no_offset(self):
        self.assertEqual(orch.first_slots([acc("a")], NOW, cfg()), {"a": local(0, 8)})

    def test_stagger_disabled(self):
        slots = orch.first_slots([acc("a"), acc("b")], NOW, cfg(stagger=False))
        self.assertEqual(slots, {"a": local(0, 8), "b": local(0, 8)})


class StartsDueTest(unittest.TestCase):
    def test_only_accounts_whose_slot_has_come(self):
        self.assertEqual(orch.starts_due([acc("a"), acc("b")], NOW, cfg(), FakeStore()), ["a"])
        later = local(0, 10, 31)
        accounts = [acc("a", now=later), acc("b", now=later)]
        self.assertEqual(orch.starts_due(accounts, later, cfg(), FakeStore()), ["a", "b"])

    def test_open_window_not_started(self):
        self.assertEqual(orch.starts_due([acc("a", 20, 120), acc("b")], NOW, cfg(), FakeStore()), [])

    def test_recent_attempt_not_repeated(self):
        store = FakeStore([Event(NOW.timestamp() - 300, "warmup", "a", {"mode": "orchestrateur"})])
        self.assertEqual(orch.starts_due([acc("a")], NOW, cfg(), store), [])
        old = FakeStore([Event(NOW.timestamp() - 1200, "warmup", "a", {"mode": "orchestrateur"})])
        self.assertEqual(orch.starts_due([acc("a")], NOW, cfg(), old), ["a"])

    def test_nothing_outside_active_hours(self):
        night = local(1, 3)
        self.assertEqual(orch.starts_due([acc("a", now=night)], night, cfg(), FakeStore()), [])

    def test_passed_reset_counts_as_idle(self):
        self.assertEqual(orch.starts_due([acc("a", 80, -2)], NOW, cfg(), FakeStore()), ["a"])


class ReserveTest(unittest.TestCase):
    def test_reserve_set_and_best_account_order(self):
        paces = {"a": WeeklyPace(0.5, 50, -15, 20, 3), "b": WeeklyPace(0.5, 50, 5, 10, 3)}
        self.assertEqual(orch.reserve_set([acc("a"), acc("b")], paces, cfg()), {"a"})
        accounts = [acc("a", 10, 60), acc("b", 0)]
        self.assertEqual(best_account(accounts, NOW).name, "a")
        self.assertEqual(best_account(accounts, NOW, reserve={"a"}).name, "b")
        self.assertEqual(best_account([acc("a", 10, 60)], NOW, reserve={"a"}).name, "a")


class ExpiringTest(unittest.TestCase):
    def decide(self, accounts, events=(), **over):
        return orch.expiring_decision(accounts, "act", NOW, cfg(**over), list(events))

    def test_switches_to_account_losing_quota_soon(self):
        d = self.decide([acc("act", 40, 200, active=True), acc("x", 30, 40)])
        self.assertEqual((d.action, d.target, d.source), ("switch", "x", "act"))
        self.assertIn("70 %", d.reason)

    def test_not_when_little_left_or_far(self):
        self.assertIsNone(self.decide([acc("act", 40, 200, active=True), acc("x", 80, 40)]))
        self.assertIsNone(self.decide([acc("act", 40, 200, active=True), acc("x", 30, 90)]))

    def test_not_when_active_expires_first(self):
        self.assertIsNone(self.decide([acc("act", 40, 30, active=True), acc("x", 30, 40)]))

    def test_stale_or_error_target_ignored(self):
        self.assertIsNone(self.decide([acc("act", 40, 200, active=True), acc("x", 30, 40, age=3600)]))
        self.assertIsNone(self.decide([acc("act", 40, 200, active=True), acc("x", 30, 40, error="e")]))

    def test_cooldown_and_manual_respected(self):
        accounts = [acc("act", 40, 200, active=True), acc("x", 30, 40)]
        recent = Event(NOW.timestamp() - 600, "switch", "act", {"mode": "anticipee"})
        self.assertIsNone(self.decide(accounts, [recent]))
        manual = Event(NOW.timestamp() - 60, "switch", "act", {"mode": "manual"})
        self.assertIsNone(self.decide(accounts, [manual]))

    def test_disabled(self):
        self.assertIsNone(self.decide([acc("act", 40, 200, active=True), acc("x", 30, 40)],
                                      expiring_switch=False))


class PlanTest(unittest.TestCase):
    def test_plan_current_and_chained_windows(self):
        accounts = [acc("a", 50, 120), acc("b")]
        windows = orch.plan(accounts, NOW, cfg())
        a = [(w.start, w.end, w.kind) for w in windows if w.name == "a"]
        self.assertEqual(a[0], (local(0, 7), local(0, 12), "current"))
        self.assertEqual(a[1], (local(0, 12), local(0, 17), "planned"))
        self.assertEqual(a[-1][0], local(0, 22))   # dernier démarrage avant 02:00
        b = [(w.start, w.kind) for w in windows if w.name == "b"]
        self.assertEqual(b[0], (local(0, 10, 30), "planned"))

    def test_next_wake(self):
        accounts = [acc("a", 50, 120), acc("b")]
        self.assertEqual(orch.next_wake(accounts, NOW, cfg()), local(0, 10, 30) + timedelta(seconds=30))
        accounts = [acc("a", 50, 20), acc("b", 10, 200)]
        self.assertEqual(orch.next_wake(accounts, NOW, cfg()), NOW + timedelta(minutes=20, seconds=30))
