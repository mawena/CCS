import copy
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from ccs_app import costs, model_advice
from ccs_app.core import Limit
from ccs_app.costs import Answer
from ccs_app.forecast import AccountState
from ccs_app.settings import DEFAULTS

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
RESET = NOW + timedelta(hours=2)


def ans(model, inp=0, out=0, cr=0, minutes_ago=5):
    tokens = (inp, out, 0, 0, cr)
    return Answer((NOW - timedelta(minutes=minutes_ago)).timestamp(), model, "/w/App", tokens,
                  costs.reprice(tokens, model))


def account(session=85, weekly=40, name="perso"):
    return AccountState(name, True, [Limit("session", "S", session, RESET),
                                     Limit("weekly_all", "W", weekly, NOW + timedelta(days=3))],
                        NOW.timestamp(), None)


class SummaryTest(unittest.TestCase):
    def test_dominant_family_by_dollars(self):
        u = model_advice.summarize([ans("claude-opus-5-5", out=1000), ans("claude-haiku-5-5", out=5000),
                                    ans("claude-opus-5-5", out=500)])
        self.assertEqual(u.family, "opus")
        self.assertEqual(u.model, "claude-opus-5-5")
        self.assertEqual(u.answers, 2)
        self.assertEqual(u.tokens, (0, 1500, 0, 0, 0))

    def test_no_answers(self):
        self.assertIsNone(model_advice.summarize([]))

    def test_unknown_price_uses_the_family_reference(self):
        u = model_advice.summarize([ans("claude-opus-4-1", out=1000)])
        self.assertEqual(u.family, "opus")
        self.assertGreater(u.dollars, 0)

    def test_mythos_is_in_the_fable_family(self):
        self.assertEqual(model_advice.family("claude-mythos-5-1"), "fable")
        self.assertEqual(model_advice.family("Opus 5.5"), "opus")
        self.assertIsNone(model_advice.family(""))


class StretchTest(unittest.TestCase):
    def test_output_heavy_opus_to_sonnet_doubles(self):
        u = model_advice.summarize([ans("claude-opus-5-5", out=1_000_000)])
        self.assertAlmostEqual(model_advice.stretch(u, "sonnet"), 2.0)

    def test_cache_read_heavy_mix_gains_less(self):
        # Opus 5.5 et Sonnet 5.5 lisent le cache au même prix : le gain se réduit.
        u = model_advice.summarize([ans("claude-opus-5-5", out=10_000, cr=10_000_000)])
        self.assertLess(model_advice.stretch(u, "sonnet"), 1.1)

    def test_stretch_text(self):
        self.assertEqual(model_advice.stretch_text(2.0), "×2")
        self.assertEqual(model_advice.stretch_text(1.84), "×1,8")
        self.assertEqual(model_advice.stretch_text(20.0), "plus de ×5")


class AdviceTest(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(DEFAULTS["alerts"])
        self.opus = model_advice.summarize([ans("claude-opus-5-5", out=1_000_000)])

    def test_session_above_threshold_with_opus(self):
        a = model_advice.advice_for(account(85), self.opus, self.cfg, NOW)
        self.assertEqual((a.kind, a.family, a.target), ("session", "opus", "sonnet"))
        alert = model_advice.alert_for(a)
        self.assertEqual(alert.key, f"model_advice:perso:{model_advice.window_id(RESET)}")
        self.assertEqual(alert.title, "perso : session à 85 % avec Opus")
        self.assertIn("Passer à Sonnet (/model sonnet)", alert.body)
        self.assertIn("environ ×2", alert.body)

    def test_weekly_above_threshold(self):
        a = model_advice.advice_for(account(30, 90), self.opus, self.cfg, NOW)
        self.assertEqual(a.kind, "weekly")
        self.assertIn("semaine à 90 %", model_advice.alert_for(a).title)
        # Clé : la fenêtre de 5 h en cours (un seul conseil par fenêtre, quelle que soit la limite).
        self.assertEqual(model_advice.alert_for(a).key, f"model_advice:perso:{model_advice.window_id(RESET)}")

    def test_below_threshold_or_cheapest_family(self):
        self.assertIsNone(model_advice.advice_for(account(70, 50), self.opus, self.cfg, NOW))
        haiku = model_advice.summarize([ans("claude-haiku-5-5", out=1000)])
        self.assertIsNone(model_advice.advice_for(account(90), haiku, self.cfg, NOW))
        self.assertIsNone(model_advice.advice_for(account(90), None, self.cfg, NOW))

    def test_threshold_setting_and_small_gain(self):
        self.cfg["model_advice_pct"] = 60
        self.assertIsNotNone(model_advice.advice_for(account(65), self.opus, self.cfg, NOW))
        cached = model_advice.summarize([ans("claude-opus-5-5", out=10_000, cr=10_000_000)])
        self.assertIsNone(model_advice.advice_for(account(90), cached, self.cfg, NOW))

    def test_reset_already_passed_does_not_count(self):
        acc = AccountState("perso", True, [Limit("session", "S", 95, NOW - timedelta(minutes=1))],
                           NOW.timestamp(), None)
        self.assertIsNone(model_advice.advice_for(acc, self.opus, self.cfg, NOW))

    def test_fable_goes_to_opus(self):
        fable = model_advice.summarize([ans("claude-fable-5-1", out=1_000_000)])
        a = model_advice.advice_for(account(90), fable, self.cfg, NOW)
        self.assertEqual(a.target, "opus")
        self.assertIn("/model opus", model_advice.alert_for(a).body)


class RecentUsageTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ccs-model-"))
        self.addCleanup(shutil.rmtree, self.dir)
        model_advice.clear_cache()

    def journal(self, rel, rows, mtime=None):
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(r) + "\n" for r in rows))
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def row(self, msg_id, model, minutes_ago, out=1000):
        return {"type": "assistant", "cwd": "/w/App",
                "timestamp": (NOW - timedelta(minutes=minutes_ago)).isoformat(),
                "message": {"id": msg_id, "model": model, "usage": {"output_tokens": out}}}

    def test_reads_recent_answers_of_recent_journals(self):
        self.journal("-w-App/s1.jsonl", [self.row("a", "claude-sonnet-5-5", 90),
                                         self.row("b", "claude-opus-5-5", 10),
                                         self.row("c", "claude-opus-5-5", 2)], NOW.timestamp())
        self.journal("-w-Old/s0.jsonl", [self.row("z", "claude-haiku-5-5", 1, out=10**7)],
                     (NOW - timedelta(hours=3)).timestamp())
        u = model_advice.recent_usage(NOW, self.dir)
        self.assertEqual(u.family, "opus")
        self.assertEqual(u.answers, 2)

    def test_tail_is_cached_until_the_journal_changes(self):
        self.journal("-w-App/s1.jsonl", [self.row("b", "claude-opus-5-5", 10)], NOW.timestamp())
        model_advice.recent_usage(NOW, self.dir)
        with mock.patch.object(model_advice, "_read_tail", wraps=model_advice._read_tail) as reader:
            model_advice.recent_usage(NOW, self.dir)
        reader.assert_not_called()

    def test_only_the_tail_is_read(self):
        big = [self.row(f"old{i}", "claude-haiku-5-5", 20, out=1) for i in range(3000)]
        p = self.journal("-w-App/s1.jsonl", big + [self.row("new", "claude-opus-5-5", 1)], NOW.timestamp())
        with mock.patch.object(model_advice, "TAIL_BYTES", 4096):
            answers = model_advice.tail_answers(p)
        self.assertLess(len(answers), 40)
        self.assertEqual(answers[-1].model, "claude-opus-5-5")

    def test_nothing_recent(self):
        self.assertIsNone(model_advice.recent_usage(NOW, self.dir))
        self.assertIsNone(model_advice.recent_usage(NOW, self.dir / "absent"))


class StatuslineHintTest(unittest.TestCase):
    def setUp(self):
        self.settings = copy.deepcopy(DEFAULTS)
        self.state = {"active": "perso", "accounts": [
            {"name": "perso", "limits": [
                {"kind": "session", "percent": 85, "resets_at": RESET.isoformat()},
                {"kind": "weekly_all", "percent": 40, "resets_at": (NOW + timedelta(days=3)).isoformat()}]}]}

    def hint(self, model, state=None):
        return model_advice.statusline_hint(state or self.state, model, self.settings, NOW)

    def test_hint_with_expensive_model_above_threshold(self):
        self.assertEqual(self.hint({"id": "claude-opus-5-5", "display_name": "Opus 5.5"}), "→ sonnet ?")
        self.assertEqual(self.hint("claude-fable-5-1"), "→ opus ?")

    def test_no_hint(self):
        self.assertEqual(self.hint({"id": "claude-haiku-5-5"}), "")
        self.assertEqual(self.hint(None), "")
        low = json.loads(json.dumps(self.state))
        low["accounts"][0]["limits"][0]["percent"] = 50
        self.assertEqual(self.hint("claude-opus-5-5", low), "")
        self.settings["alerts"]["model_advice"] = False
        self.assertEqual(self.hint("claude-opus-5-5"), "")

    def test_expired_window_does_not_count(self):
        st = json.loads(json.dumps(self.state))
        st["accounts"][0]["limits"][0]["resets_at"] = (NOW - timedelta(minutes=5)).isoformat()
        self.assertEqual(self.hint("claude-opus-5-5", st), "")


if __name__ == "__main__":
    unittest.main()
