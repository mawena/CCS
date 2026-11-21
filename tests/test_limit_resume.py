"""Relance des conversations bloquées par une limite, à la levée de la limite."""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from ccs_app import core, limit_events, limit_resume
from ccs_app.forecast import AccountState
from tests.helpers import HomeTestCase

SID = "5b1d0c3e-aaaa-4bbb-8ccc-0123456789ab"
SID2 = "6c2e1d4f-bbbb-4ccc-8ddd-0123456789ab"
NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
TS = NOW.timestamp()


def account(name, active, session_pct, session_in_h=2.0, weekly_pct=10, weekly_in_h=72, error=None):
    limits = [core.Limit("session", "5 h", session_pct, NOW + timedelta(hours=session_in_h)),
              core.Limit("weekly", "semaine", weekly_pct, NOW + timedelta(hours=weekly_in_h))]
    return AccountState(name, active, limits, TS, error)


SETTINGS = {"auto_switch": {"target_max_weekly": 90}, "limit_resume": {"enabled": True, "outside": "notify"}}


class LiftAtTest(HomeTestCase):
    def test_active_session_reset(self):
        at = limit_resume.lift_at([account("perso", True, 100)], "perso", NOW)
        self.assertEqual(at, NOW + timedelta(hours=2, seconds=limit_resume.MARGIN_S))

    def test_weekly_limit_waits_for_the_week(self):
        at = limit_resume.lift_at([account("perso", True, 30, weekly_pct=100, weekly_in_h=50)], "perso", NOW)
        self.assertEqual(at, NOW + timedelta(hours=50, seconds=limit_resume.MARGIN_S))

    def test_other_account_freed_sooner(self):
        accounts = [account("perso", True, 100, session_in_h=4), account("pro", False, 99, session_in_h=1)]
        at = limit_resume.lift_at(accounts, "perso", NOW)
        self.assertEqual(at, NOW + timedelta(hours=1, seconds=limit_resume.MARGIN_S))

    def test_broken_account_ignored_and_unknown_retries_later(self):
        accounts = [account("pro", False, 99, session_in_h=1, error="connexion révoquée")]
        at = limit_resume.lift_at(accounts, "perso", NOW)
        self.assertEqual(at, NOW + timedelta(seconds=limit_resume.UNKNOWN_S))

    def test_plan_respects_the_pause(self):
        accounts = [account("perso", True, 100, session_in_h=1)]
        self.assertIsNone(limit_resume.plan(accounts, "perso", NOW, paused=False))
        until = NOW + timedelta(hours=3)
        self.assertEqual(limit_resume.plan(accounts, "perso", NOW, paused=until), until.timestamp())

    def test_config(self):
        self.assertEqual(limit_resume.config({}), {"enabled": True, "outside": "notify"})
        self.assertEqual(limit_resume.config({"limit_resume": {"enabled": False, "outside": "x"}}),
                         {"enabled": False, "outside": "notify"})


class AdvanceTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.sent = []

    def advance(self, now, accounts, **kw):
        kw.setdefault("live", [])
        return limit_resume.advance(now, accounts, "perso", SETTINGS, set(), self.sent.append, **kw)

    def test_exhausted_is_planned_then_lifted_once_for_all(self):
        limit_events.record(SID, TS, "perso", None, False, "exhausted", "/w/A")
        limit_events.record(SID2, TS, "perso", None, False, "exhausted", "/w/B")
        blocked = [account("perso", True, 100, session_in_h=1)]
        nxt = self.advance(TS, blocked)
        events = limit_events.load_all()
        self.assertEqual({e.outcome for e in events.values()}, {"planned"})
        self.assertEqual(nxt, TS + 3600 + limit_resume.MARGIN_S)
        self.assertEqual(self.sent, [])
        # À l'heure : la fenêtre de 5 h est réinitialisée (pourcentage effectif 0).
        later = TS + 3700
        self.advance(later, blocked)
        events = limit_events.load_all()
        self.assertEqual({e.outcome for e in events.values()}, {"lifted"})
        self.assertEqual(events[SID].lifted_at, later)
        self.assertFalse(events[SID].switched)
        self.assertEqual(len(self.sent), 1)          # une seule notification pour les deux
        self.assertIn("2 conversations", self.sent[0].body)

    def test_due_but_still_blocked_retries(self):
        limit_events.record(SID, TS, "perso", None, False, "planned", resume_at=TS - 1)
        still = [account("perso", True, 100, session_in_h=0.001)]    # données en retard
        with mock.patch.object(limit_resume, "_switch", return_value=None):
            nxt = self.advance(TS, still)
        e = limit_events.load_all()[SID]
        self.assertEqual(e.outcome, "planned")
        self.assertGreater(e.resume_at, TS)
        self.assertEqual(nxt, e.resume_at)

    def test_due_with_another_account_free_switches(self):
        limit_events.record(SID, TS, "perso", None, False, "planned", resume_at=TS - 1)
        accounts = [account("perso", True, 100, session_in_h=3), account("pro", False, 10)]
        with mock.patch.object(limit_resume, "_switch", return_value="pro") as sw:
            self.advance(TS, accounts)
        sw.assert_called_once()
        e = limit_events.load_all()[SID]
        self.assertEqual((e.outcome, e.target, e.switched), ("lifted", "pro", True))
        self.assertIn("compte pro", self.sent[0].body)

    def test_disabled_does_nothing(self):
        limit_events.record(SID, TS, "perso", None, False, "exhausted")
        s = {**SETTINGS, "limit_resume": {"enabled": False}}
        limit_resume.advance(TS, [account("perso", True, 100)], "perso", s, set(), self.sent.append)
        self.assertEqual(limit_events.load_all()[SID].outcome, "exhausted")

    def test_lock_held_elsewhere_skips(self):
        limit_events.record(SID, TS, "perso", None, False, "exhausted")
        import fcntl
        path = self.store / "hook.lock"
        with open(path, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            nxt = self.advance(TS, [account("perso", True, 100)])
        self.assertEqual(nxt, TS + limit_resume.CHECK_S)
        self.assertEqual(limit_events.load_all()[SID].outcome, "exhausted")

    def test_unclaimed_lifted_notifies_or_resumes_in_background(self):
        limit_events.record(SID, TS, "perso", None, False, "lifted", self.tmp, lifted_at=TS)
        spawned = []
        self.advance(TS + 10, [], spawner=lambda *a: spawned.append(a) or True)
        self.assertIn(SID, limit_events.load_all())           # délai de grâce : rien encore
        self.advance(TS + limit_resume.GRACE_S + 1, [], spawner=lambda *a: spawned.append(a) or True)
        self.assertNotIn(SID, limit_events.load_all())
        self.assertEqual(spawned, [])                          # « notify » par défaut
        self.assertIn("continue", self.sent[-1].body)
        # Réglage « resume » et conversation fermée : relance en arrière-plan.
        limit_events.record(SID, TS, "perso", None, False, "lifted", self.tmp, lifted_at=TS)
        s = {**SETTINGS, "limit_resume": {"enabled": True, "outside": "resume"}}
        limit_resume.advance(TS + 999, [], "perso", s, set(), self.sent.append, live=[],
                             spawner=lambda *a: spawned.append(a) or True)
        self.assertEqual(spawned, [(self.tmp, SID)])
        # Toujours ouverte ailleurs : notification seulement.
        limit_events.record(SID, TS, "perso", None, False, "lifted", self.tmp, lifted_at=TS)
        limit_resume.advance(TS + 999, [], "perso", s, set(), self.sent.append,
                             live=[SimpleNamespace(session_id=SID)],
                             spawner=lambda *a: spawned.append(a) or True)
        self.assertEqual(len(spawned), 1)

    def test_planned_marker_survives_the_daily_prune(self):
        limit_events.record(SID, TS, "perso", None, False, "planned", resume_at=time.time() + 3 * 86400)
        path = limit_events.path(SID)
        import os
        os.utime(path, (time.time() - 2 * 86400, time.time() - 2 * 86400))
        limit_events.prune()
        self.assertTrue(path.exists())


class FollowerTest(HomeTestCase):
    def test_planned_note_once_then_resume_once(self):
        f = limit_resume.Follower()
        limit_events.record(SID, TS, "perso", None, False, "planned", resume_at=TS + 3600)
        ev = limit_events.load_all()[SID]
        out = f.step(ev, TS, True)
        self.assertEqual(out[0][0], "notice")
        self.assertIn("relance prévue à", out[0][1])
        self.assertEqual(f.step(ev, TS + 1, True), [])
        limit_events.record(SID, TS, "perso", "perso", False, "lifted", lifted_at=TS + 3600)
        ev = limit_events.load_all()[SID]
        self.assertEqual(f.step(ev, TS + 3601, False), [])       # Claude occupé : on attend
        out = f.step(ev, TS + 3602, True)
        self.assertEqual(out[0], ("send", "continue"))
        self.assertNotIn(SID, limit_events.load_all())           # pris : personne d'autre
        self.assertEqual(f.step(ev, TS + 3603, True), [])

    def test_user_typed_since_the_limit(self):
        f = limit_resume.Follower()
        f.typed(TS + 10)
        limit_events.record(SID, TS, "perso", None, False, "lifted", lifted_at=TS + 60)
        out = f.step(limit_events.load_all()[SID], TS + 70, True)
        self.assertEqual([a[0] for a in out], ["notice"])
        self.assertNotIn(SID, limit_events.load_all())

    def test_limit_seen_without_hook_writes_a_marker(self):
        f = limit_resume.Follower()
        f.limit_hit(TS)
        self.assertEqual(f.step(None, TS + 10, True, session_id=SID, cwd="/w"), [])
        self.assertNotIn(SID, limit_events.load_all())
        f.step(None, TS + limit_resume.HOOK_WAIT_S, True, session_id=SID, cwd="/w")
        e = limit_events.load_all()[SID]
        self.assertEqual((e.outcome, e.ts, e.cwd), ("exhausted", TS, "/w"))

    def test_at_most_three_per_hour(self):
        f = limit_resume.Follower()
        f.resumes = [TS - 10, TS - 20, TS - 30]
        limit_events.record(SID, TS, "perso", "pro", True, "switched")
        out = f.step(limit_events.load_all()[SID], TS, True)
        self.assertEqual([a[0] for a in out], ["notice"])
        self.assertIn("suspendue", out[0][1])


class TerminalResumesTest(HomeTestCase):
    def test_claude_started_in_a_bridge_terminal(self):
        parents = {500: 400, 400: 300, 300: 1}
        live = [SimpleNamespace(pid=500, session_id=SID, state="idle", waiting_for=None),
                SimpleNamespace(pid=900, session_id=SID2, state="idle", waiting_for=None)]
        limit_events.record(SID, TS, "perso", None, False, "lifted", lifted_at=TS)
        limit_events.record(SID2, TS, "perso", None, False, "lifted", lifted_at=TS)
        history = {}
        out = limit_resume.terminal_resumes(limit_events.load_all(), live, {"t1": 300}, TS, history,
                                            ppid=parents.get)
        self.assertEqual(out, [("t1", SID)])
        self.assertNotIn(SID, limit_events.load_all())
        self.assertIn(SID2, limit_events.load_all())     # hors de ces terminaux : laissé
        self.assertEqual(history, {SID: [TS]})

    def test_busy_claude_is_left_alone(self):
        live = [SimpleNamespace(pid=500, session_id=SID, state="busy", waiting_for=None)]
        limit_events.record(SID, TS, "perso", None, False, "lifted", lifted_at=TS)
        self.assertEqual(limit_resume.terminal_resumes(limit_events.load_all(), live, {"t1": 500}, TS, {}), [])

    def test_descends_from(self):
        parents = {5: 4, 4: 3, 3: 1}
        self.assertTrue(limit_resume.descends_from(5, 3, parents.get))
        self.assertFalse(limit_resume.descends_from(5, 7, parents.get))


class BridgeChatLimitsTest(HomeTestCase):
    def test_chat_receives_note_then_continue(self):
        from ccs_app.server import bridge_chat

        class Engine:
            session_id, state = SID, "idle"
            sent = []

            def send_if_idle(self, text):
                self.sent.append(text)
                return True

        bridge = SimpleNamespace(busy_checks=[], close_hooks=[], tick_hooks=[], add_handlers=lambda h: None)
        hub = bridge_chat.ChatHub(bridge)
        self.assertIn(hub.limits_pass, bridge.tick_hooks)
        chat = bridge_chat._Chat("c1", self.tmp)
        chat.engine = Engine()
        hub.chats["c1"] = chat
        limit_events.record(SID, time.time(), "perso", None, False, "planned", resume_at=time.time() + 3600)
        with mock.patch.object(limit_resume, "advance"):
            asyncio.run(hub.limits_pass())
        self.assertTrue(hub.busy())                  # le pont reste ouvert jusqu'à la relance
        self.assertEqual(chat.buf[-1]["event"]["type"], "Notice")
        self.assertIn("relance prévue", chat.buf[-1]["event"]["text"])
        ev = limit_events.load_all()[SID]
        limit_events.update(ev, outcome="lifted", lifted_at=time.time())
        with mock.patch.object(limit_resume, "advance"):
            asyncio.run(hub.limits_pass())
        self.assertEqual(Engine.sent, ["continue"])
        self.assertEqual([i["event"]["type"] for i in list(chat.buf)[-2:]], ["UserSent", "Notice"])
