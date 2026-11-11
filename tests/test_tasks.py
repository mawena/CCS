import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from ccs_app import tasks
from tests.helpers import HomeTestCase

TZ = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 11, 12, 14, 0, tzinfo=timezone.utc)    # 15:00 à Paris


def state(session=10, weekly=10, now=NOW, error=None):
    return {"updated_at": now.timestamp(), "accounts": [
        {"name": "perso", "active": True, "error": error, "fetched_at": now.timestamp(), "limits": [
            {"kind": "session", "label": "Session", "percent": session,
             "resets_at": (now + timedelta(hours=3)).isoformat()},
            {"kind": "weekly_all", "label": "Semaine", "percent": weekly,
             "resets_at": (now + timedelta(days=3)).isoformat()}]}]}


class StorageTest(HomeTestCase):
    def test_add_list_and_file_mode(self):
        t = tasks.add("Corrige les tests", cwd=str(self.home), rights="tout", model="opus", now=NOW)
        self.assertEqual((t.id, t.state, t.when, t.rights, t.model), ("1", "queued", "quota", "tout", "opus"))
        self.assertEqual(oct((self.store / "tasks.json").stat().st_mode & 0o777), "0o600")
        self.assertEqual([x.id for x in tasks.all()], ["1"])
        self.assertEqual(tasks.add("Autre", cwd=str(self.home)).id, "2")
        self.assertEqual(tasks.get(2).message, "Autre")

    def test_ids_are_not_reused_after_removal(self):
        a = tasks.add("a", cwd=str(self.home))
        tasks.cancel(a.id)
        tasks.remove(a.id)
        self.assertEqual(tasks.add("b", cwd=str(self.home)).id, "2")

    def test_invalid_input(self):
        for kw in ({"message": " "}, {"message": "x", "rights": "root"}, {"message": "x", "when": "demain"},
                   {"message": "x", "when": "25:00"}, {"message": "x", "cwd": str(self.home / "nope")},
                   {"message": "x", "model": "-bad"}):
            with self.assertRaises(ValueError, msg=str(kw)):
                tasks.add(**kw)

    def test_when_is_normalized_and_not_before_set(self):
        t = tasks.add("x", cwd=str(self.home), when="7:30", now=NOW, tz=TZ)
        self.assertEqual(t.when, "07:30")
        self.assertEqual(datetime.fromtimestamp(t.not_before, TZ), datetime(2026, 11, 13, 7, 30, tzinfo=TZ))
        t = tasks.add("x", cwd=str(self.home), when="16:00", now=NOW, tz=TZ)
        self.assertEqual(datetime.fromtimestamp(t.not_before, TZ), datetime(2026, 11, 12, 16, 0, tzinfo=TZ))

    def test_unreadable_or_foreign_file_gives_no_tasks(self):
        (self.store / "tasks.json").write_text("{pas du json")
        self.assertEqual(tasks.all(), [])
        (self.store / "tasks.json").write_text(json.dumps({"version": 9, "tasks": [{"id": "1"}]}))
        self.assertEqual(tasks.all(), [])
        (self.store / "tasks.json").write_text(json.dumps({"version": 1, "tasks": [
            {"id": "../x", "message": "m", "cwd": "/tmp"}, {"id": "3", "message": "ok", "cwd": "/tmp",
                                                           "state": "bizarre", "when": "n'importe"}, 5]}))
        self.assertEqual([(t.id, t.state, t.when) for t in tasks.all()], [("3", "queued", "quota")])

    def test_cancel_and_remove_rules(self):
        t = tasks.add("x", cwd=str(self.home))
        with self.assertRaises(ValueError):
            tasks.remove(t.id)                      # encore active
        self.assertEqual(tasks.cancel(t.id).state, "cancelled")
        with self.assertRaises(ValueError):
            tasks.cancel(t.id)                      # déjà annulée
        tasks.journal_dir().mkdir(parents=True)
        tasks.journal_path(t.id).write_text("{}\n")
        self.assertEqual(tasks.remove(t.id).id, t.id)
        self.assertFalse(tasks.journal_path(t.id).exists())
        self.assertIsNone(tasks.cancel("42"))
        self.assertIsNone(tasks.remove("42"))

    def test_cancel_running_stops_the_process(self):
        t = tasks.add("x", cwd=str(self.home))
        tasks.update(t.id, state="running", pid=1234)
        with mock.patch("ccs_app.task_runner.stop") as stop:
            tasks.cancel(t.id)
        stop.assert_called_once()
        self.assertEqual(tasks.get(t.id).state, "cancelled")
        self.assertIsNone(tasks.get(t.id).pid)


class ConfigTest(unittest.TestCase):
    def test_defaults_and_fallbacks(self):
        self.assertEqual(tasks.config(None), tasks.DEFAULTS)
        self.assertEqual(tasks.config({"tasks": {"enabled": False, "max_attempts": 5,
                                                 "night": {"start": "22:00", "end": "bad"}}}),
                         {"enabled": False, "max_attempts": 5, "night": {"start": "22:00", "end": "07:00"}})
        self.assertEqual(tasks.config({"tasks": {"max_attempts": 99}})["max_attempts"], 3)
        self.assertEqual(tasks.config({"tasks": 3}), tasks.DEFAULTS)


def T(id_, when="quota", state="queued", **kw):
    return tasks.Task(id_, "m", "/tmp", when=when, state=state, **kw)


class DecideTest(unittest.TestCase):
    def d(self, items, now=NOW, st=None, paused=False, settings=None):
        return tasks.decide(items, now, settings, st if st is not None else state(), paused, TZ)

    def test_quota_task_starts_in_order(self):
        self.assertEqual(self.d([T("1"), T("2")]).id, "1")

    def test_one_at_a_time(self):
        self.assertIsNone(self.d([T("1", state="running"), T("2")]))

    def test_pause_and_disabled_block(self):
        self.assertIsNone(self.d([T("1")], paused=True))
        self.assertIsNone(self.d([T("1")], settings={"tasks": {"enabled": False}}))

    def test_no_quota_or_no_data(self):
        self.assertIsNone(self.d([T("1")], st=state(session=97)))
        self.assertIsNone(self.d([T("1")], st=state(weekly=96)))
        self.assertIsNone(self.d([T("1")], st=state(error="invalid_grant")))
        self.assertIsNone(self.d([T("1")], st={}))
        self.assertEqual(self.d([T("1")], st=state(error="HTTP 429")).id, "1")

    def test_expired_window_counts_as_free(self):
        st = state(session=100)
        st["accounts"][0]["limits"][0]["resets_at"] = (NOW - timedelta(minutes=1)).isoformat()
        self.assertEqual(self.d([T("1")], st=st).id, "1")

    def test_clock_time_waits_for_not_before(self):
        t = T("1", when="16:00", not_before=(NOW + timedelta(hours=1)).timestamp())
        self.assertIsNone(self.d([t]))
        later = NOW + timedelta(hours=1, minutes=1)
        self.assertEqual(self.d([t], now=later, st=state(now=later)).id, "1")

    def test_waiting_after_limit_goes_first_and_respects_retry(self):
        w = T("2", state="waiting", retry_at=NOW.timestamp() - 1)
        self.assertEqual(self.d([T("1"), w]).id, "2")
        w.retry_at = NOW.timestamp() + 100
        self.assertEqual(self.d([T("1"), w]).id, "1")

    def test_cancelled_and_finished_never_start(self):
        self.assertIsNone(self.d([T("1", state="cancelled"), T("2", state="done"), T("3", state="failed")]))

    def test_why_it_waits(self):
        self.assertEqual(tasks.due(T("1"), NOW, None, state(), True, TZ), (False, "CCS est en pause"))
        self.assertEqual(tasks.due(T("1"), NOW, None, state(session=99), False, TZ),
                         (False, "aucun compte n'a de quota"))


class NightTest(unittest.TestCase):
    def test_window_across_midnight(self):
        at = datetime(2026, 11, 12, 23, 30, tzinfo=TZ).astimezone(timezone.utc)
        s, e = tasks.night_window(at, "23:00", "07:00", TZ)
        self.assertEqual((s.astimezone(TZ).hour, e.astimezone(TZ).day, e.astimezone(TZ).hour), (23, 13, 7))
        after_midnight = datetime(2026, 11, 13, 2, 0, tzinfo=TZ).astimezone(timezone.utc)
        s, e = tasks.night_window(after_midnight, "23:00", "07:00", TZ)
        self.assertEqual((s.astimezone(TZ).day, e.astimezone(TZ).day), (12, 13))

    def test_next_window_when_outside(self):
        s, e = tasks.night_window(NOW, "23:00", "07:00", TZ)
        self.assertEqual(s.astimezone(TZ), datetime(2026, 11, 12, 23, 0, tzinfo=TZ))
        self.assertGreater(s, NOW)

    def test_window_same_day(self):
        at = datetime(2026, 11, 12, 13, 0, tzinfo=TZ).astimezone(timezone.utc)
        s, e = tasks.night_window(at, "12:00", "14:00", TZ)
        self.assertEqual((s.astimezone(TZ).hour, e.astimezone(TZ).hour), (12, 14))

    def night_state(self, session, reset_h):
        night = datetime(2026, 11, 12, 23, 30, tzinfo=TZ).astimezone(timezone.utc)
        st = state(session=session, now=night)
        st["accounts"][0]["limits"][0]["resets_at"] = (night + timedelta(hours=reset_h)).isoformat()
        return night, st

    def test_night_task_waits_for_the_night_then_starts(self):
        t = T("1", when="nuit")
        self.assertIsNone(tasks.decide([t], NOW, None, state(), False, TZ))
        # fenêtre qui expire dans 1 h : le meilleur créneau est maintenant
        night, st = self.night_state(90, 1)
        ok, why = tasks.night_due(night, None, st, TZ)
        self.assertTrue(ok, why)
        self.assertEqual(tasks.decide([t], night, None, st, False, TZ).id, "1")

    def test_night_waits_for_a_better_slot(self):
        # le meilleur créneau est à 00:30 : on attend
        night, st = self.night_state(10, 3)
        ok, why = tasks.night_due(night, None, st, TZ)
        self.assertFalse(ok)
        self.assertIn("meilleur créneau (00:30)", why)
        later = night + timedelta(hours=1)
        st["accounts"][0]["fetched_at"] = later.timestamp()
        self.assertTrue(tasks.night_due(later, None, st, TZ)[0])

    def test_night_without_any_slot(self):
        ok, why = tasks.night_due(datetime(2026, 11, 12, 23, 30, tzinfo=TZ).astimezone(timezone.utc),
                                  None, {}, TZ)
        self.assertEqual((ok, why), (False, "aucun créneau avec du quota cette nuit"))


class FakeRunner:
    def __init__(self, results=None, prep=(True, "")):
        self.results, self.prep, self.started, self.prepared = results or {}, prep, [], []

    def poll(self, task, now):
        return self.results.get(task.id)

    def prepare(self, task, state, settings, now):
        self.prepared.append(task.id)
        return self.prep

    def start(self, task, now, resume=False, attempts=0):
        self.started.append((task.id, resume, attempts))
        tasks.update(task.id, state="running", pid=1, started=now.timestamp(), attempts=attempts)


def R(**kw):
    base = {"ok": False, "limit": False, "cancelled": False, "session_id": None, "duration": 0.0, "cost": None,
            "total": False, "error": None, "code": 0}
    return SimpleNamespace(**{**base, **kw})


class TickTest(HomeTestCase):
    def tick(self, runner, now=NOW, st=None, paused=False, settings=None):
        return tasks.tick(now, settings, st if st is not None else state(), paused, runner, TZ)

    def test_starts_the_next_task(self):
        t = tasks.add("x", cwd=str(self.home))
        r = FakeRunner()
        self.assertEqual(self.tick(r), [])
        self.assertEqual(r.started, [(t.id, False, 0)])

    def test_nothing_when_paused(self):
        tasks.add("x", cwd=str(self.home))
        r = FakeRunner()
        self.tick(r, paused=True)
        self.assertEqual(r.started, [])

    def test_unprepared_task_waits_and_is_retried_later(self):
        t = tasks.add("x", cwd=str(self.home))
        r = FakeRunner(prep=(False, "aucun compte disponible"))
        self.tick(r)
        self.assertEqual(r.started, [])
        got = tasks.get(t.id)
        self.assertEqual((got.state, got.note), ("queued", "aucun compte disponible"))

    def test_success_gives_alert_with_duration_and_cost(self):
        t = tasks.add("Corrige les tests", cwd=str(self.home))
        tasks.update(t.id, state="running", pid=5)
        alerts = self.tick(FakeRunner({t.id: R(ok=True, duration=125, cost=1.5, total=True, session_id="s1")}))
        got = tasks.get(t.id)
        self.assertEqual((got.state, got.duration, got.cost, got.session_id), ("done", 125, 1.5, "s1"))
        self.assertEqual(len(alerts), 1)
        a = alerts[0]
        self.assertEqual((a.title, a.default, a.key), ("Tâche finie", f"task:{t.id}", f"task:{t.id}:done"))
        self.assertIn("2 min 05 s", a.body)
        self.assertIn("Corrige les tests", a.body)

    def test_failure_gives_alert(self):
        t = tasks.add("x", cwd=str(self.home))
        tasks.update(t.id, state="running", pid=5)
        a, = self.tick(FakeRunner({t.id: R(error="boom")}))
        self.assertEqual((a.title, a.urgency), ("Tâche échouée", 2))
        self.assertEqual((tasks.get(t.id).state, tasks.get(t.id).error), ("failed", "boom"))

    def test_limit_then_resume_up_to_max_attempts(self):
        t = tasks.add("x", cwd=str(self.home))
        r = FakeRunner()
        self.tick(r)                                               # démarrage
        tasks.update(t.id, session_id="s1")
        for n in (1, 2, 3):
            r.results = {t.id: R(limit=True, session_id="s1")}
            self.assertEqual(self.tick(r, now=NOW + timedelta(minutes=n)), [])
            self.assertEqual(tasks.get(t.id).state, "running")                 # reprise dans le même tour
            self.assertEqual(r.started[-1], (t.id, True, n))
        r.results = {t.id: R(limit=True, session_id="s1")}
        self.tick(r, now=NOW + timedelta(minutes=9))
        self.assertEqual(tasks.get(t.id).state, "failed")
        self.assertIn("limite atteinte 3 fois", tasks.get(t.id).error)

    def test_limit_while_paused_keeps_waiting_without_using_an_attempt(self):
        t = tasks.add("x", cwd=str(self.home))
        tasks.update(t.id, state="running", pid=5, session_id="s1")
        r = FakeRunner({t.id: R(limit=True, session_id="s1")})
        self.tick(r, paused=True)
        got = tasks.get(t.id)
        self.assertEqual((got.state, got.attempts), ("waiting", 0))
        self.assertEqual(r.started, [])

    def test_limit_without_session_fails(self):
        t = tasks.add("x", cwd=str(self.home))
        tasks.update(t.id, state="running", pid=5)
        self.tick(FakeRunner({t.id: R(limit=True)}))
        self.assertEqual(tasks.get(t.id).state, "failed")

    def test_cancelled_during_run_is_not_overwritten(self):
        t = tasks.add("x", cwd=str(self.home))
        tasks.update(t.id, state="cancelled")
        self.assertEqual(self.tick(FakeRunner({t.id: R(ok=True)})), [])

    def test_disabled_does_not_start_nor_poll_cancelled(self):
        t = tasks.add("x", cwd=str(self.home))
        tasks.update(t.id, state="running", pid=5)
        u = tasks.add("y", cwd=str(self.home))
        r = FakeRunner({t.id: R(ok=True)})
        alerts = self.tick(r, settings={"tasks": {"enabled": False}})
        self.assertEqual((len(alerts), r.started, tasks.get(u.id).state), (1, [], "queued"))


class CommandTest(HomeTestCase):
    def run_cmd(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = tasks.command(list(args), out, err, now=NOW)
        return code, out.getvalue(), err.getvalue()

    def test_add_list_cancel_remove(self):
        code, out, _ = self.run_cmd("ajouter", "Fais le ménage", "-C", str(self.home), "--droits", "lecture",
                                    "--quand", "nuit", "--modele", "sonnet")
        self.assertEqual(code, 0)
        self.assertIn("Tâche 1 ajoutée", out)
        t = tasks.get("1")
        self.assertEqual((t.rights, t.when, t.model, t.cwd), ("lecture", "nuit", "sonnet", str(self.home)))
        code, out, _ = self.run_cmd()
        self.assertIn("En attente", out)
        self.assertIn("Fais le ménage", out)
        self.assertEqual(self.run_cmd("supprimer", "1")[0], 1)       # encore active
        self.assertEqual(self.run_cmd("annuler", "1")[0], 0)
        self.assertEqual(self.run_cmd("supprimer", "1")[0], 0)
        self.assertIn("Aucune tâche", self.run_cmd()[1])

    def test_option_forms(self):
        code, _, _ = self.run_cmd("ajouter", "--droits=tout", "--quand=07:05", "m", "--dossier", str(self.home))
        self.assertEqual(code, 0)
        self.assertEqual((tasks.get("1").rights, tasks.get("1").when), ("tout", "07:05"))

    def test_errors(self):
        for args in (("ajouter",), ("ajouter", "m", "--droits", "x"), ("ajouter", "a", "b"),
                     ("ajouter", "m", "--inconnue"), ("ajouter", "m", "-C")):
            code, _, err = self.run_cmd(*args)
            self.assertEqual(code, 1, args)
            self.assertTrue(err.startswith("ccs :"), args)
        self.assertEqual(self.run_cmd("annuler", "99")[0], 1)
        self.assertEqual(self.run_cmd("annuler")[0], 2)
        self.assertEqual(self.run_cmd("voir", "../x")[0], 2)
        self.assertEqual(self.run_cmd("bidule")[0], 2)
        self.assertEqual(self.run_cmd("voir", "9")[0], 1)

    def test_view_prints_readable_journal(self):
        t = tasks.add("x", cwd=str(self.home))
        tasks.update(t.id, state="done", duration=61)
        tasks.journal_dir().mkdir(parents=True)
        tasks.journal_path(t.id).write_text("\n".join(json.dumps(e) for e in [
            {"type": "ccs", "text": "démarrage"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Je commence"},
                                                          {"type": "tool_use", "name": "Bash",
                                                           "input": {"command": "ls"}}]}},
            {"type": "result", "is_error": False, "result": "Fini"}]) + "\n")
        code, out, _ = self.run_cmd("voir", t.id)
        self.assertEqual(code, 0)
        self.assertIn("Je commence", out)
        self.assertIn("▸ Bash ls", out)
        self.assertIn("✓ Fini", out)
        self.assertIn("Finie", out)


if __name__ == "__main__":
    unittest.main()
