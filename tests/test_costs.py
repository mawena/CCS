import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import costs
from ccs_app.costs import conversation_cost, format_cost

TS = "2026-11-04T10:00:00.000Z"


def answer(msg_id, model="claude-opus-5-5", inp=0, out=0, cw=0, cr=0, cw1h=None, speed=None, geo=None,
           sidechain=False):
    usage = {"input_tokens": inp, "output_tokens": out,
             "cache_creation_input_tokens": cw + (cw1h or 0), "cache_read_input_tokens": cr}
    if cw1h is not None:
        usage["cache_creation"] = {"ephemeral_5m_input_tokens": cw, "ephemeral_1h_input_tokens": cw1h}
    if speed:
        usage["speed"] = speed
    if geo:
        usage["inference_geo"] = geo
    return {"type": "assistant", "timestamp": TS, "isSidechain": sidechain, "uuid": f"u-{msg_id}",
            "message": {"id": msg_id, "model": model, "role": "assistant",
                        "content": [{"type": "text", "text": "ok"}], "usage": usage}}


class CostTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ccs-costs-"))
        self.addCleanup(shutil.rmtree, self.dir)
        costs.clear_cache()

    def journal(self, rows, name="s1.jsonl", raw_tail=""):
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(r) + "\n" for r in rows) + raw_tail)
        return p


class PriceTableTest(unittest.TestCase):
    def test_table_is_dated_and_sourced(self):
        self.assertRegex(costs.PRICES_DATE, r"^\d{4}-\d{2}-\d{2}$")
        self.assertIn("claude-api", costs.PRICES_SOURCE)

    def test_current_models_have_prices(self):
        for model in ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-haiku-5-5",
                      "claude-fable-5-1", "claude-haiku-4-5", "claude-sonnet-4-6"):
            self.assertIsNotNone(costs.price_for(model), model)

    def test_cache_writes_follow_the_documented_multipliers(self):
        p = costs.price_for("claude-opus-5-5")
        self.assertEqual((p.input, p.output, p.cache_read), (4.0, 20.0, 0.20))
        self.assertAlmostEqual(p.cache_write_5m, 5.0)
        self.assertAlmostEqual(p.cache_write_1h, 8.0)
        self.assertAlmostEqual(costs.price_for("claude-sonnet-5-5").cache_write_5m, 2.50)
        self.assertAlmostEqual(costs.price_for("claude-fable-5-1").cache_read, 0.25)

    def test_model_names_are_normalised(self):
        base = costs.price_for("claude-haiku-4-5")
        for name in ("claude-haiku-4-5-20251001", "anthropic.claude-haiku-4-5", "claude-haiku-4-5[1m]",
                     "us.anthropic.claude-haiku-4-5-20251001-v1:0", "claude-haiku-4-5@20251001",
                     "Claude-Haiku-4-5"):
            self.assertEqual(costs.price_for(name), base, name)

    def test_unknown_model(self):
        self.assertIsNone(costs.price_for("claude-opus-4-1-20250805"))
        self.assertIsNone(costs.price_for("gpt-9"))
        self.assertIsNone(costs.price_for(""))


class ConversationCostTest(CostTestCase):
    def test_sums_tokens_and_dollars_per_type(self):
        p = self.journal([
            {"type": "user", "message": {"role": "user", "content": "bonjour"}},
            answer("m1", inp=1_000_000),
            answer("m2", out=1_000_000),
            answer("m3", cw=1_000_000),
            answer("m4", cr=1_000_000),
        ])
        c = conversation_cost(p)
        self.assertEqual(c.tokens_par_type, {"entree": 1_000_000, "sortie": 1_000_000,
                                            "cache_ecriture": 1_000_000, "cache_lecture": 1_000_000})
        self.assertEqual(c.total_tokens, 4_000_000)
        self.assertAlmostEqual(c.dollars, 4 + 20 + 5 + 0.20)
        self.assertFalse(c.inconnu)
        self.assertEqual(c.reponses, 4)
        self.assertEqual(list(c.modeles), ["claude-opus-5-5"])
        self.assertAlmostEqual(c.modeles["claude-opus-5-5"].dollars, 29.20)

    def test_one_hour_cache_writes_cost_twice_the_input(self):
        p = self.journal([answer("m1", cw=1_000_000, cw1h=1_000_000)])
        c = conversation_cost(p)
        self.assertEqual(c.tokens_par_type["cache_ecriture"], 2_000_000)
        self.assertAlmostEqual(c.dollars, 5.0 + 8.0)

    def test_duplicate_message_ids_are_counted_once(self):
        # Claude Code écrit une ligne par bloc de contenu, avec le même identifiant et le même usage.
        p = self.journal([answer("m1", inp=10, out=100), answer("m1", inp=10, out=100),
                          answer("m2", inp=5, out=5)])
        c = conversation_cost(p)
        self.assertEqual(c.tokens_par_type["entree"], 15)
        self.assertEqual(c.tokens_par_type["sortie"], 105)
        self.assertEqual(c.reponses, 2)

    def test_several_models_and_unknown_model(self):
        p = self.journal([answer("m1", model="claude-sonnet-5-5", out=1_000_000),
                          answer("m2", model="claude-opus-4-1-20250805", out=1_000_000)])
        c = conversation_cost(p)
        self.assertTrue(c.inconnu)
        self.assertAlmostEqual(c.dollars, 10.0)  # minimum : le modèle inconnu ne compte pas
        self.assertEqual(c.modeles_inconnus, ["claude-opus-4-1-20250805"])
        self.assertIsNone(c.modeles["claude-opus-4-1-20250805"].dollars)
        self.assertEqual(c.total_tokens, 2_000_000)

    def test_synthetic_and_empty_usage_are_ignored(self):
        p = self.journal([answer("m1", model="<synthetic>"), answer("m2", inp=0, out=0)])
        c = conversation_cost(p)
        self.assertEqual(c.reponses, 0)
        self.assertFalse(c.inconnu)
        self.assertEqual(c.dollars, 0)

    def test_corrupt_lines_and_other_types_are_skipped(self):
        p = self.journal([{"type": "api-request-blob", "message": {"id": "x", "model": "claude-opus-5-5",
                                                                     "usage": {"input_tokens": 999}}},
                          answer("m1", inp=1_000_000)],
                         raw_tail='{"type": "assistant", "message": {"id": "m9", "usage": \n'
                                  'pas du json\n[1, 2]\n"texte"\n')
        c = conversation_cost(p)
        self.assertEqual(c.reponses, 1)
        self.assertAlmostEqual(c.dollars, 4.0)

    def test_haiku_5_5_long_prompt_uses_the_higher_rate_card(self):
        p = self.journal([answer("short", model="claude-haiku-5-5", inp=50_000, out=1000),
                          answer("long", model="claude-haiku-5-5", inp=50_000, cr=60_000, out=1000)])
        c = conversation_cost(p)
        short = 50_000 * 0.10 / 1e6 + 1000 * 0.50 / 1e6
        long_ = 50_000 * 0.50 / 1e6 + 60_000 * 0.05 / 1e6 + 1000 * 2.50 / 1e6
        self.assertAlmostEqual(c.dollars, short + long_)

    def test_fast_mode_and_us_inference(self):
        p = self.journal([answer("m1", out=1_000_000, speed="fast"),
                          answer("m2", out=1_000_000, geo="us")])
        c = conversation_cost(p)
        self.assertAlmostEqual(c.dollars, 40.0 + 22.0)
        self.assertFalse(c.inconnu)

    def test_fast_mode_without_known_price_is_unknown(self):
        p = self.journal([answer("m1", model="claude-sonnet-5-5", out=1_000_000, speed="fast")])
        c = conversation_cost(p)
        self.assertTrue(c.inconnu)
        self.assertEqual(c.dollars, 0)

    def test_subagents_are_included(self):
        p = self.journal([answer("m1", out=1_000_000)], name="s1.jsonl")
        self.journal([answer("a1", model="claude-haiku-4-5", out=1_000_000, sidechain=True)],
                     name="s1/subagents/agent-1.jsonl")
        self.assertAlmostEqual(conversation_cost(p).dollars, 20.0 + 5.0)
        self.assertAlmostEqual(conversation_cost(p, subagents=False).dollars, 20.0)

    def test_missing_file(self):
        c = conversation_cost(self.dir / "absent.jsonl")
        self.assertEqual((c.reponses, c.dollars, c.total_tokens), (0, 0, 0))


class CacheTest(CostTestCase):
    def test_unchanged_file_is_not_read_again(self):
        p = self.journal([answer("m1", inp=100)])
        first = conversation_cost(p)
        with mock.patch.object(costs, "_read_file", wraps=costs._read_file) as reader:
            again = conversation_cost(p)
        reader.assert_not_called()
        self.assertEqual(first, again)

    def test_changed_file_is_read_again(self):
        p = self.journal([answer("m1", inp=100)])
        conversation_cost(p)
        with open(p, "a") as f:
            f.write(json.dumps(answer("m2", inp=50)) + "\n")
        st = p.stat()
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        self.assertEqual(conversation_cost(p).tokens_par_type["entree"], 150)


class FormatTest(unittest.TestCase):
    def cost(self, tokens, dollars, unknown=False):
        return costs.Cost({"entree": tokens, "sortie": 0, "cache_ecriture": 0, "cache_lecture": 0}, dollars, {},
                          unknown, reponses=1)

    def test_format(self):
        self.assertEqual(format_cost(self.cost(1_200_000, 3.4)), "1,2 M tokens · ≈ 3,40 $")
        self.assertEqual(format_cost(self.cost(45_300, 0.123)), "45,3 k tokens · ≈ 0,12 $")
        self.assertEqual(format_cost(self.cost(800, 0.004)), "800 tokens · < 0,01 $")
        self.assertEqual(format_cost(self.cost(2_000_000_000, 1234.5)), "2000,0 M tokens · ≈ 1 234 $")

    def test_format_unknown(self):
        self.assertEqual(format_cost(self.cost(1_200_000, 0.0, unknown=True)), "1,2 M tokens · tarif inconnu")
        self.assertEqual(format_cost(self.cost(1_200_000, 3.4, unknown=True)),
                         "1,2 M tokens · ≥ 3,40 $ (tarif inconnu pour une partie)")

    def test_format_empty(self):
        self.assertEqual(format_cost(costs.Cost.empty()), "aucun usage enregistré")

    def test_details_per_model(self):
        p = Path(tempfile.mkdtemp(prefix="ccs-costs-"))
        self.addCleanup(shutil.rmtree, p)
        costs.clear_cache()
        f = p / "s.jsonl"
        f.write_text(json.dumps(answer("m1", out=1_000_000)) + "\n"
                     + json.dumps(answer("m2", model="claude-x", out=10)) + "\n")
        lines = costs.format_details(conversation_cost(f))
        self.assertEqual(lines[0], "claude-opus-5-5 : 1,0 M tokens · ≈ 20,00 $ (1 réponse)")
        self.assertEqual(lines[1], "claude-x : 10 tokens · tarif inconnu (1 réponse)")


if __name__ == "__main__":
    unittest.main()
