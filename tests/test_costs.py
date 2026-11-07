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


def at(msg_id, iso, **kw):
    """Réponse horodatée (`iso`, UTC) dans un projet."""
    row = answer(msg_id, **kw)
    row["timestamp"] = iso
    row["cwd"] = "/home/u/Work/App"
    return row


class AnswersTest(CostTestCase):
    def test_answers_keep_time_model_project_and_dollars(self):
        p = self.journal([at("m1", "2026-11-02T10:00:00Z", out=1_000_000),
                          at("m1", "2026-11-02T10:00:00Z", out=1_000_000),
                          at("m2", "2026-11-03T08:30:00.500Z", model="claude-sonnet-5-5", inp=1_000_000)])
        answers = costs.file_answers(p)
        self.assertEqual(len(answers), 2)
        first, second = sorted(answers, key=lambda a: a.ts)
        self.assertEqual(first.ts, 1793613600.0)
        self.assertEqual(first.model, "claude-opus-5-5")
        self.assertEqual(first.cwd, "/home/u/Work/App")
        self.assertEqual(first.tokens, (0, 1_000_000, 0, 0, 0))
        self.assertAlmostEqual(first.dollars, 20.0)
        self.assertAlmostEqual(second.dollars, 2.0)

    def test_answers_are_cached_until_the_file_changes(self):
        p = self.journal([at("m1", "2026-11-02T10:00:00Z", inp=10)])
        costs.file_answers(p)
        with mock.patch.object(costs, "_parse", wraps=costs._parse) as parser:
            costs.file_answers(p)
        parser.assert_not_called()

    def test_cost_of_answers(self):
        p = self.journal([at("m1", "2026-11-02T10:00:00Z", out=1_000_000),
                          at("m2", "2026-11-02T11:00:00Z", model="claude-opus-4-1", out=10)])
        c = costs.cost_of(costs.file_answers(p))
        self.assertEqual(c.reponses, 2)
        self.assertTrue(c.inconnu)
        self.assertAlmostEqual(c.dollars, 20.0)
        self.assertEqual(c.tokens_par_type["sortie"], 1_000_010)

    def test_period_answers_and_cost_filter_by_time(self):
        self.journal([at("m1", "2026-11-01T10:00:00Z", out=1_000_000),
                      at("m2", "2026-11-03T10:00:00Z", out=1_000_000)], name="-home-u-App/s1.jsonl")
        self.journal([at("a1", "2026-11-03T11:00:00Z", model="claude-haiku-4-5", out=1_000_000)],
                     name="-home-u-App/s1/subagents/agent-1.jsonl")
        old = self.journal([at("z", "2026-10-01T10:00:00Z", out=1_000_000)], name="-home-u-Old/s0.jsonl")
        os.utime(old, (1790000000, 1790000000))  # pas modifié depuis : pas même ouvert
        since = 1793700000.0   # 2026-11-03T10:00Z
        by_file = costs.period_answers(self.dir, since)
        self.assertEqual(sorted(p.name for p in by_file), ["agent-1.jsonl", "s1.jsonl"])
        self.assertEqual(sum(len(v) for v in by_file.values()), 2)
        c = costs.period_cost(self.dir, since)
        self.assertAlmostEqual(c.dollars, 20.0 + 5.0)
        self.assertAlmostEqual(costs.period_cost(self.dir, since, until=since + 1800).dollars, 20.0)
        self.assertEqual(costs.period_cost(self.dir / "absent", since).reponses, 0)

    def test_reprice_at_another_model(self):
        tokens = (1_000_000, 1_000_000, 0, 0, 1_000_000)
        self.assertAlmostEqual(costs.reprice(tokens, "claude-opus-5-5"), 4 + 20 + 0.2)
        self.assertAlmostEqual(costs.reprice(tokens, "claude-sonnet-5-5"), 2 + 10 + 0.2)
        self.assertIsNone(costs.reprice(tokens, "gpt-9"))


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

    def test_short_format_for_lists(self):
        self.assertEqual(costs.format_short(self.cost(1_200_000, 3.4)), "≈ 3,40 $")
        self.assertEqual(costs.format_short(self.cost(800, 0.004)), "< 0,01 $")
        self.assertEqual(costs.format_short(self.cost(1_200_000, 3.4, unknown=True)), "≥ 3,40 $")
        self.assertEqual(costs.format_short(self.cost(1_200_000, 0.0, unknown=True)), "tarif inconnu")
        self.assertEqual(costs.format_short(costs.Cost.empty()), "")

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


class LoaderTest(CostTestCase):
    """Calcul paresseux pour les listes : un journal après l'autre, hors de l'interface."""

    def setUp(self):
        super().setUp()
        self.posted = []
        self.loader = costs.Loader(post=lambda f, *a: self.posted.append((f, a)))

    def deliver(self):
        self.loader.join(5)
        posted, self.posted = self.posted, []
        for f, a in posted:
            f(*a)

    def test_results_come_back_in_order_through_post(self):
        a = self.journal([answer("m1", out=1000)], "a.jsonl")
        b = self.journal([answer("m2", out=2000)], "b.jsonl")
        got = []
        self.loader.request([("a", a), ("b", b)], lambda key, cost: got.append((key, cost.total_tokens)))
        self.assertEqual(got, [])  # rien n'est livré hors du fil de l'interface
        self.deliver()
        self.assertEqual(got, [("a", 1000), ("b", 2000)])

    def test_new_request_replaces_the_old_one(self):
        a = self.journal([answer("m1", out=1000)], "a.jsonl")
        b = self.journal([answer("m2", out=2000)], "b.jsonl")
        old, new = [], []
        gate = __import__("threading").Event()
        real = costs.conversation_cost
        loader = costs.Loader(post=lambda f, *x: self.posted.append((f, x)),
                              compute=lambda p: (gate.wait(5), real(p))[1])
        loader.request([("a", a), ("b", b)], lambda k, c: old.append(k))
        loader.request([("b", b)], lambda k, c: new.append(k))
        gate.set()
        loader.join(5)
        for f, x in self.posted:
            f(*x)
        self.assertEqual(old, [])      # résultats d'une liste déjà remplacée : ignorés
        self.assertEqual(new, ["b"])

    def test_cancel_and_errors(self):
        a = self.journal([answer("m1", out=1000)], "a.jsonl")
        got = []
        self.loader.request([("x", self.dir / "absent.jsonl"), ("a", a)], lambda k, c: got.append(k))
        self.deliver()
        self.assertEqual(got, ["x", "a"])  # journal absent : coût vide, jamais d'exception
        loader = costs.Loader(post=lambda f, *x: self.posted.append((f, x)),
                              compute=lambda p: 1 / 0)
        loader.request([("a", a)], lambda k, c: got.append(k))
        loader.join(5)
        self.assertEqual(self.posted, [])
        self.loader.request([("a", a)], lambda k, c: got.append("après annulation"))
        self.loader.cancel()
        self.deliver()
        self.assertNotIn("après annulation", got)


if __name__ == "__main__":
    unittest.main()
