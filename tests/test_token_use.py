"""Consommation de tokens d'un chat : usage d'un tour, cache expiré (token_use, moteur)."""

import json
import unittest
from pathlib import Path

from ccs_app import chat_engine, chat_protocol as proto, token_use

RESULT = {
    "type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 1.5,
    "usage": {"input_tokens": 4, "cache_creation_input_tokens": 15423, "cache_read_input_tokens": 35952,
              "output_tokens": 403,
              "cache_creation": {"ephemeral_1h_input_tokens": 15423, "ephemeral_5m_input_tokens": 0},
              "iterations": [{"input_tokens": 2, "output_tokens": 305, "cache_read_input_tokens": 24582,
                              "cache_creation_input_tokens": 2211}]},
    "model_usage_since_last_result": {"claude-opus-5-5": {"outputTokens": 403, "costUSD": 0.0365}},
}


class TurnUsageTest(unittest.TestCase):
    def test_turn_usage_from_result(self):
        u = token_use.turn_usage(RESULT)
        self.assertEqual(u, {"input": 4, "cache_read": 35952, "cache_write": 15423, "output": 403,
                             "cost_usd": 0.0365, "model": "claude-opus-5-5",
                             "context": 2 + 305 + 24582 + 2211, "cache_ttl_s": 3600})

    def test_turn_usage_5_min_cache_and_no_iterations(self):
        r = {"usage": {"input_tokens": 10, "cache_read_input_tokens": 50_000, "output_tokens": 5,
                       "cache_creation": {"ephemeral_5m_input_tokens": 9}}, "total_cost_usd": "x"}
        u = token_use.turn_usage(r)
        self.assertEqual((u["context"], u["cache_ttl_s"], u["cost_usd"]), (50_015, 300, 0.0))

    def test_no_usage(self):
        for bad in (None, {}, {"usage": "x"}, {"usage": {"input_tokens": 0}}):
            self.assertEqual(token_use.turn_usage(bad), {})

    def test_protocol_result_carries_usage(self):
        [ev] = proto.parse_line(json.dumps(RESULT))
        self.assertEqual(ev.usage["output"], 403)

    def test_summary_and_format(self):
        u = token_use.turn_usage(RESULT)
        self.assertEqual(token_use.summary(u), "36 k lus · 15 k écrits · 403 produits · 0,04 $")
        self.assertEqual(token_use.fmt_tokens(1_234_567), "1,2 M")
        self.assertEqual(token_use.summary({}), "")


class CacheExpiryTest(unittest.TestCase):
    def test_small_context_says_nothing(self):
        self.assertIsNone(token_use.cache_expiry({"context": 19_999, "cache_ttl_s": 3600}))

    def test_big_context_costs_a_rewrite(self):
        info = token_use.cache_expiry({"context": 200_000, "cache_ttl_s": 3600, "model": "claude-opus-5-5"})
        self.assertEqual(info["ttl_s"], 3600)
        self.assertEqual(info["rewrite_usd"], 1.6)           # 200 k × 4 $ × 2 (cache 1 h) / M
        self.assertIn("200 k tokens", info["text"])
        self.assertIn("1,60 $", info["text"])
        five = token_use.cache_expiry({"context": 200_000, "cache_ttl_s": 300, "model": "claude-opus-5-5"})
        self.assertEqual(five["rewrite_usd"], 1.0)           # × 1,25 (cache 5 min)
        self.assertIn("rien depuis 5 min", five["text"])
        self.assertIsNone(token_use.cache_expiry({"context": 50_000, "model": "inconnu"})["rewrite_usd"])


class EngineCacheTimerTest(unittest.TestCase):
    def engine(self):
        events = []
        chat = chat_engine.ChatSession(Path("/tmp"), on_event=events.append)
        return chat, events

    def test_expired_after_a_turn_when_idle(self):
        chat, events = self.engine()
        chat._arm_cache_timer({"context": 100_000, "cache_ttl_s": 3600, "model": "claude-opus-5-5"})
        timer = chat._cache_timer
        self.assertIsNotNone(timer)
        timer.cancel()
        chat.state = "idle"
        chat._cache_expired(chat._cache_turn, token_use.cache_expiry({"context": 100_000, "cache_ttl_s": 3600}))
        self.assertTrue(any(isinstance(e, chat_engine.CacheExpired) for e in events))

    def test_message_sent_cancels(self):
        chat, events = self.engine()
        chat._arm_cache_timer({"context": 100_000, "cache_ttl_s": 3600})
        turn = chat._cache_turn
        chat._forget_cache_timer()
        self.assertIsNone(chat._cache_timer)
        chat.state = "idle"
        chat._cache_expired(turn, {"context": 1, "ttl_s": 1, "rewrite_usd": None, "text": ""})
        self.assertEqual(events, [])

    def test_small_context_no_timer(self):
        chat, _ = self.engine()
        chat._arm_cache_timer({"context": 1000})
        self.assertIsNone(chat._cache_timer)


if __name__ == "__main__":
    unittest.main()
