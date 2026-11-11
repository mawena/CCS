"""Alerte de contexte lourd : faux journaux, état dans un store temporaire."""

import json
import os
import stat
import unittest

from ccs_app import context_alert as ca
from ccs_app import integration
from ccs_app.sessions import Session
from tests.helpers import HomeTestCase

NOW = 1_800_000_000.0


def line(inp=10, read=0, write=0, model="claude-opus-5-5", side=False, kind="assistant", rid="m"):
    return json.dumps({"type": kind, "isSidechain": side, "timestamp": "2026-11-11T10:00:00Z",
                       "message": {"id": rid, "model": model,
                                   "usage": {"input_tokens": inp, "output_tokens": 5,
                                             "cache_read_input_tokens": read,
                                             "cache_creation_input_tokens": write}}}) + "\n"


def session(pid=10, sid="s1", cwd="/home/u/App"):
    return Session(pid=pid, session_id=sid, name="n", cwd=cwd, project="App", state="idle", waiting_for=None,
                   started_at=NOW - 3600, state_since=NOW - 60, kind="interactive", entrypoint="cli")


class JournalTest(HomeTestCase):
    def journal(self, text, name="j.jsonl"):
        p = self.home / name
        p.write_text(text)
        return p

    def test_context_is_last_main_usage(self):
        p = self.journal(line(5, 1000, 200, rid="a") + line(7, 150_000, 300, rid="b")
                         + line(1, 999999, 0, side=True, rid="c")           # sous-agent : ignoré
                         + line(1, 5, 5, model="<synthetic>", rid="d")      # synthétique : ignoré
                         + "pas du json \"usage\" \"assistant\"\n"
                         + line(0, 0, 0, rid="e"))                          # sans tokens : ignoré
        self.assertEqual(ca.read_context(p), ca.Context(150_307, "claude-opus-5-5"))

    def test_missing_empty_or_unreadable(self):
        self.assertIsNone(ca.read_context(self.home / "absent.jsonl"))
        self.assertIsNone(ca.read_context(self.journal("")))
        self.assertIsNone(ca.read_context(self.journal("{cassé\n" + line(kind="user"))))

    def test_only_the_tail_is_read_but_widens_when_needed(self):
        big = "x" * 1000 + "\n"
        p = self.journal(line(9, 100_000, 0) + big * (ca.TAIL_BYTES // 1000 * 2))
        self.assertEqual(ca.read_context(p).tokens, 100_009)            # au-delà de la fin lue d'abord
        p = self.journal(big * (ca.TAIL_BYTES // 1000 * 2) + line(3, 50, 0))
        self.assertEqual(ca.read_context(p).tokens, 53)

    def test_session_context_uses_the_transcript_of_the_session(self):
        s = session()
        self.assertIsNone(ca.session_context(s))
        d = self.home / ".claude" / "projects" / "-home-u-App"
        d.mkdir(parents=True)
        (d / "s1.jsonl").write_text(line(1, 2, 3))
        self.assertEqual(ca.session_context(s).tokens, 6)
        self.assertIsNone(ca.session_context(session(sid="")))


class CostTest(unittest.TestCase):
    def test_cache_read_price_by_model(self):
        self.assertAlmostEqual(ca.message_cost(ca.Context(200_000, "claude-opus-5-5")), 0.04)
        self.assertAlmostEqual(ca.message_cost(ca.Context(200_000, "claude-sonnet-4-6-20260101")), 0.06)
        self.assertAlmostEqual(ca.message_cost(ca.Context(200_000, "claude-haiku-5-5")), 200_000 * 0.05 / 1e6)
        self.assertIsNone(ca.message_cost(ca.Context(200_000, "modele-inconnu")))

    def test_texts(self):
        c = ca.Context(182_400, "claude-opus-5-5")
        self.assertEqual(ca.badge_text(c), "contexte lourd · 182 k")
        self.assertIn("0,04 $", ca.advice_text(c))
        self.assertIn("/compact", ca.advice_text(c))
        self.assertIn("nouvelle session", ca.advice_text(c))
        self.assertNotIn("coûte", ca.advice_text(ca.Context(182_400, "?")))

    def test_config_with_fallbacks(self):
        self.assertEqual(ca.config(None), {"enabled": True, "threshold_tokens": 150_000})
        self.assertEqual(ca.config({"context_alert": {"enabled": False, "threshold_tokens": 90000}}),
                         {"enabled": False, "threshold_tokens": 90000})
        for bad in ({"context_alert": {"threshold_tokens": "x", "enabled": 3}},
                    {"context_alert": {"threshold_tokens": -5}}, {"context_alert": []}):
            self.assertEqual(ca.config(bad), {"enabled": True, "threshold_tokens": 150_000})


class DecideTest(HomeTestCase):
    def heavy(self, tokens=200_000):
        return ca.Context(tokens, "claude-opus-5-5")

    def test_one_alert_per_session(self):
        found = [session(10, "s1"), session(11, "s2")]
        alerts, state = ca.decide(found, {10: self.heavy(), 11: ca.Context(1000, "x")}, None, {}, NOW)
        self.assertEqual([a.key for a in alerts], ["context:s1"])
        self.assertEqual(state, {"s1": NOW})
        a = alerts[0]
        self.assertIn("App", a.title)
        self.assertEqual(a.urgency, 1)
        self.assertTrue(a.default.endswith("10:s1"))
        again, state2 = ca.decide(found, {10: self.heavy(300_000), 11: None}, None, state, NOW + 60)
        self.assertEqual((again, state2), ([], {"s1": NOW}))

    def test_rearms_after_compact_and_purges_closed_sessions(self):
        notified = {"s1": 1.0, "gone": 2.0}
        alerts, state = ca.decide([session(10, "s1")], {10: ca.Context(20_000, "x")}, None, notified, NOW)
        self.assertEqual((alerts, state), ([], {}))
        alerts, _ = ca.decide([session(10, "s1")], {10: self.heavy()}, None, state, NOW)
        self.assertEqual(len(alerts), 1)

    def test_unreadable_journal_keeps_the_mark(self):
        _, state = ca.decide([session(10, "s1")], {10: None}, None, {"s1": 5.0}, NOW)
        self.assertEqual(state, {"s1": 5.0})

    def test_disabled_and_custom_threshold(self):
        off = {"context_alert": {"enabled": False}}
        self.assertEqual(ca.decide([session()], {10: self.heavy()}, off, {}, NOW), ([], {}))
        low = {"context_alert": {"threshold_tokens": 1000}}
        self.assertEqual(len(ca.decide([session()], {10: ca.Context(1500, "x")}, low, {}, NOW)[0]), 1)

    def test_sessions_without_id_are_ignored(self):
        self.assertEqual(ca.decide([session(10, "")], {10: self.heavy()}, None, {}, NOW), ([], {}))


class TickTest(HomeTestCase):
    def write_journal(self, sid, tokens):
        d = self.home / ".claude" / "projects" / "-home-u-App"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{sid}.jsonl").write_text(line(tokens, 0, 0))

    def test_tick_alerts_once_and_remembers_in_the_store(self):
        self.write_journal("s1", 200_000)
        self.write_journal("s2", 10)
        found = [session(10, "s1"), session(11, "s2")]
        first = ca.tick(found, None, NOW)
        self.assertEqual([a.key for a in first], ["context:s1"])
        path = self.store / "context-alerts.json"
        self.assertEqual(json.loads(path.read_text()), {"notified": {"s1": NOW}})
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(ca.tick(found, None, NOW + 5), [])
        self.assertEqual(ca.tick([session(11, "s2")], None, NOW + 9), [])   # s1 terminée : purgée
        self.assertEqual(ca.load_state(), {})

    def test_disabled_touches_nothing(self):
        self.write_journal("s1", 200_000)
        self.assertEqual(ca.tick([session()], {"context_alert": {"enabled": False}}, NOW), [])
        self.assertFalse((self.store / "context-alerts.json").exists())

    def test_corrupt_state_is_ignored(self):
        (self.store / "context-alerts.json").write_text("{cassé")
        self.assertEqual(ca.load_state(), {})
        (self.store / "context-alerts.json").write_text('{"notified": [1]}')
        self.assertEqual(ca.load_state(), {})
        self.write_journal("s1", 200_000)
        self.assertEqual(len(ca.tick([session()], None, NOW)), 1)


class StatuslineTest(HomeTestCase):
    STATE = {"active": "perso", "accounts": [{"name": "perso", "limits": [
        {"kind": "session", "percent": 10, "resets_at": None}]}], "best": {}}

    def payload(self, tokens, path_name="t.jsonl"):
        p = self.home / path_name
        p.write_text(line(tokens, 0, 0))
        return {"transcript_path": str(p)}

    def test_warning_when_heavy(self):
        text = integration.statusline_text(self.STATE, NOW, self.payload(180_000))
        self.assertTrue(text.endswith("⚠ contexte 180 k"), text)

    def test_nothing_when_light_or_without_path_or_unreadable(self):
        for payload in (self.payload(1000), {}, None, {"transcript_path": str(self.home / "absent")},
                        {"transcript_path": 12}):
            self.assertNotIn("contexte", integration.statusline_text(self.STATE, NOW, payload))

    def test_disabled_by_settings(self):
        off = {"context_alert": {"enabled": False}}
        text = integration.statusline_text(self.STATE, NOW, self.payload(180_000), settings=off)
        self.assertNotIn("contexte", text)

    def test_warning_also_without_data_and_with_pause(self):
        text = integration.statusline_text({"pause": {"until": None}}, NOW, self.payload(180_000))
        self.assertTrue(text.startswith("⏸ ") and text.endswith("⚠ contexte 180 k"), text)


if __name__ == "__main__":
    unittest.main()
