"""Mémoire des sessions : faux /proc, fausses fiches, aucun vrai processus mesuré."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import session_memory as sm
from ccs_app.sessions import Session

NOW = 1_800_000_000.0


def fake_proc(root, procs):
    """procs : {pid: (ppid, pss_ko ou None, rss_ko ou None)}."""
    for pid, (ppid, pss, rss) in procs.items():
        d = Path(root) / str(pid)
        d.mkdir(parents=True)
        (d / "stat").write_text(f"{pid} (cl au de) S {ppid} 1 1 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 1\n")
        if pss is not None:
            (d / "smaps_rollup").write_text(f"00400000-ffff r-xp 0 00:00 0 [rollup]\nRss: 9999 kB\nPss: {pss} kB\n")
        if rss is not None:
            (d / "status").write_text(f"Name:\tx\nVmRSS:\t{rss} kB\n")
    (Path(root) / "self").mkdir(exist_ok=True)       # entrée non numérique ignorée
    (Path(root) / "cpuinfo").write_text("x")


def session(pid=10, state="idle", since=NOW - 3 * 3600, cwd="/home/u/App", sid="s1"):
    return Session(pid=pid, session_id=sid, name="n", cwd=cwd, project="App", state=state, waiting_for=None,
                   started_at=NOW - 5 * 3600, state_since=since, kind="interactive", entrypoint="cli")


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-proc-")
        self.addCleanup(shutil.rmtree, self.tmp, True)


class RamTest(TmpCase):
    def test_sums_pss_of_process_and_descendants_only(self):
        fake_proc(self.tmp, {1: (0, 5, 5), 10: (1, 1000, 2000), 11: (10, 500, 700), 12: (11, 250, None),
                             20: (1, 9999, 9999)})
        self.assertEqual(sm.session_bytes(10, self.tmp), (1000 + 500 + 250) * 1024)

    def test_falls_back_to_rss_when_no_pss(self):
        fake_proc(self.tmp, {10: (1, None, 2048), 11: (10, 100, 5000)})
        self.assertEqual(sm.session_bytes(10, self.tmp), (2048 + 100) * 1024)

    def test_vanished_process_counts_zero_without_raising(self):
        fake_proc(self.tmp, {10: (1, 100, None)})
        self.assertEqual(sm.session_bytes(999, self.tmp), 0)
        self.assertEqual(sm.process_bytes(10, str(Path(self.tmp) / "absent")), 0)
        self.assertEqual(sm.children_map(str(Path(self.tmp) / "absent")), {})

    def test_unreadable_stat_is_skipped_and_loops_are_safe(self):
        fake_proc(self.tmp, {10: (11, 100, None), 11: (10, 50, None)})   # boucle de parenté
        (Path(self.tmp) / "12").mkdir()                                  # processus sans stat
        self.assertEqual(sm.session_bytes(10, self.tmp), 150 * 1024)


class IdleTest(unittest.TestCase):
    def test_busy_is_never_idle(self):
        self.assertEqual(sm.idle_seconds(session(state="busy"), NOW, NOW - 99999), 0.0)

    def test_latest_of_journal_and_state(self):
        s = session(since=NOW - 3 * 3600)
        self.assertEqual(sm.idle_seconds(s, NOW), 3 * 3600)
        self.assertEqual(sm.idle_seconds(s, NOW, mtime=NOW - 600), 600)
        self.assertEqual(sm.idle_seconds(s, NOW, mtime=NOW - 9 * 3600), 3 * 3600)

    def test_falls_back_to_start_date(self):
        self.assertEqual(sm.idle_seconds(session(since=0), NOW), 5 * 3600)

    def test_idle_hours_setting_with_fallback(self):
        self.assertEqual(sm.idle_hours(None), 2.0)
        self.assertEqual(sm.idle_hours({"sessions": {"idle_hours": 4}}), 4.0)
        for bad in ({"sessions": {"idle_hours": "x"}}, {"sessions": {"idle_hours": -1}}, {"sessions": 3}):
            self.assertEqual(sm.idle_hours(bad), 2.0)


class SnapshotTest(TmpCase):
    def setUp(self):
        super().setUp()
        fake_proc(self.tmp, {10: (1, 1024 * 1024, None), 20: (1, 512 * 1024, None), 30: (1, 256 * 1024, None)})

    def test_snapshot_and_summary(self):
        found = [session(10, since=NOW - 3 * 3600), session(20, since=NOW - 30 * 60, sid="s2"),
                 session(30, state="busy", sid="s3")]
        snap = sm.snapshot(found, NOW, {"sessions": {"idle_hours": 2}}, self.tmp, mtime=lambda s: 0.0)
        self.assertEqual([snap[p].idle for p in (10, 20, 30)], [True, False, False])
        self.assertEqual(snap[10].ram, 1024 ** 3)
        total = sm.summary(snap)
        self.assertEqual((total.count, total.idle_count, total.idle_total), (3, 1, 1024 ** 3))
        self.assertEqual(total.total, 1024 ** 3 + 512 * 1024 ** 2 + 256 * 1024 ** 2)
        self.assertEqual(sm.banner_text(total), "1 session inactive occupe 1,0 Go")

    def test_journal_mtime_read_from_a_fake_home(self):
        home = Path(self.tmp) / "home"
        j = home / ".claude" / "projects" / "-home-u-App" / "s1.jsonl"
        j.parent.mkdir(parents=True)
        j.write_text("{}\n")
        os.utime(j, (NOW - 100, NOW - 100))
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
            self.assertEqual(sm.journal_mtime(session()), NOW - 100)
            self.assertEqual(sm.journal_mtime(session(sid="absent")), 0.0)
            self.assertEqual(sm.journal_mtime(session(sid="")), 0.0)


class FormatTest(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(sm.fmt_bytes(0), "0 Mo")
        self.assertEqual(sm.fmt_bytes(820 * 1024 ** 2), "820 Mo")
        self.assertEqual(sm.fmt_bytes(int(1.4 * 1024 ** 3)), "1,4 Go")

    def test_idle(self):
        self.assertEqual(sm.fmt_idle(20), "")
        self.assertEqual(sm.fmt_idle(25 * 60), "inactive depuis 25 min")
        self.assertEqual(sm.fmt_idle(3 * 3600 + 12 * 60), "inactive depuis 3 h 12")

    def test_banner_and_line(self):
        self.assertIsNone(sm.banner_text(sm.Summary(10, 2, 0, 0)))
        self.assertEqual(sm.banner_text(sm.Summary(0, 3, 2, 1536 * 1024 ** 2)),
                         "2 sessions inactives occupent 1,5 Go")
        self.assertEqual(sm.line_text(sm.SessionMemory(1, 300 * 1024 ** 2, 7200, True)),
                         "300 Mo · inactive depuis 2 h 00")
        self.assertEqual(sm.line_text(sm.SessionMemory(1, 300 * 1024 ** 2, 5, False)), "300 Mo")


if __name__ == "__main__":
    unittest.main()
