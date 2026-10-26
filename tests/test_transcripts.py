import json
import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from ccs_app import transcripts
from ccs_app.transcripts import UsageRow, advice, aggregate, scan

T0 = datetime(2026, 10, 26, 10, 15).astimezone().timestamp()


def line(msg_id, ts, model="claude-opus-5-5", cwd="/home/u/Work/App", inp=10, out=100,
         cw=1000, cr=5000):
    return json.dumps({
        "type": "assistant", "cwd": cwd,
        "timestamp": datetime.fromtimestamp(ts).astimezone().isoformat(),
        "message": {"id": msg_id, "model": model, "usage": {
            "input_tokens": inp, "output_tokens": out,
            "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr}},
    })


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)

    def write(self, rel, lines):
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(lines) + "\n")
        return p

    def test_scan_reads_usage_and_dedups_message_ids(self):
        self.write("-home-u-Work-App/s1.jsonl", [
            json.dumps({"type": "user", "message": {"content": "salut"}}),
            line("m1", T0, out=50), line("m1", T0, out=100),  # même message en 2 blocs
            line("m2", T0 + 60, model="claude-sonnet-5-5", cwd="/home/u/Other"),
        ])
        self.write("-home-u-Work-App/s1/subagents/a.jsonl", [line("m3", T0 + 120)])
        rows = sorted(scan(self.dir, since=0), key=lambda r: r.ts)
        self.assertEqual([r.project for r in rows], ["App", "Other", "App"])
        self.assertEqual(rows[0].output, 100)
        self.assertEqual(rows[1].model, "sonnet")

    def test_scan_skips_malformed_lines(self):
        self.write("p/s.jsonl", ["{pas du json", json.dumps({"type": "assistant"}), line("ok", T0)])
        self.assertEqual(len(scan(self.dir, since=0)), 1)

    def test_scan_since_filters_old_files_and_rows(self):
        old = self.write("p/old.jsonl", [line("a", T0 - 10 * 86400)])
        os.utime(old, (T0 - 10 * 86400, T0 - 10 * 86400))
        self.write("p/new.jsonl", [line("b", T0 - 9 * 86400), line("c", T0)])
        self.assertEqual([r.ts for r in scan(self.dir, since=T0 - 86400)], [T0])

    def test_scan_skips_zero_usage_messages(self):
        self.write("p/s.jsonl", [line("z", T0, model="<synthetic>", inp=0, out=0, cw=0, cr=0),
                                 line("ok", T0)])
        self.assertEqual([r.model for r in scan(self.dir, since=0)], ["opus"])

    def test_scan_missing_dir(self):
        self.assertEqual(scan(self.dir / "absent", since=0), [])


class AggregateTest(unittest.TestCase):
    def rows(self):
        return [UsageRow(T0, "App", "opus", 10, 100, 1000, 5000),
                UsageRow(T0 + 3600, "App", "opus", 10, 100, 1000, 5000),
                UsageRow(T0 + 7200, "Blog", "sonnet", 10, 10, 100, 100)]

    def test_weighted(self):
        self.assertAlmostEqual(self.rows()[0].weighted, 10 + 1000 + 500 + 500)

    def test_aggregate_by_project_model_hour(self):
        r = aggregate(self.rows(), [], days=7)
        self.assertAlmostEqual(r.total, 2 * 2010 + (10 + 100 + 50 + 10))
        self.assertEqual(max(r.by_project, key=r.by_project.get), "App")
        self.assertEqual(set(r.by_model), {"opus", "sonnet"})
        self.assertEqual(len(r.by_hour), 24)
        self.assertAlmostEqual(r.by_hour[10], 2010)

    def test_aggregate_attributes_accounts_from_periods(self):
        periods = [(T0 - 1, T0 + 3000, "perso"), (T0 + 3000, T0 + 4000, "pro")]
        r = aggregate(self.rows(), periods, days=7)
        self.assertEqual(r.by_account, {"perso": 2010, "pro": 2010, "inconnu": 170})

    def test_advice_project_share_and_opus(self):
        tips = advice(aggregate(self.rows(), [], days=7))
        self.assertLessEqual(len(tips), 5)
        self.assertTrue(any("App" in t for t in tips))
        self.assertTrue(any("Opus" in t for t in tips))
        self.assertTrue(any("10 h" in t for t in tips))

    def test_advice_empty(self):
        self.assertEqual(advice(aggregate([], [], days=7)), [])
