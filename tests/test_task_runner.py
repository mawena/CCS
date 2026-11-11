"""Exécution des tâches : faux `claude` et faux `gagarine` (jamais les vrais)."""

import json
import os
import stat
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from ccs_app import task_runner, tasks
from tests.helpers import HomeTestCase, write

NOW = datetime(2026, 11, 12, 14, 0, tzinfo=timezone.utc)

FAKE_CLAUDE = """#!{python}
import json, os, sys
args = sys.argv[1:]
mode = os.environ.get("FAKE_MODE", "ok")
open(os.environ["FAKE_LOG"], "a").write(json.dumps({{"args": args, "cwd": os.getcwd()}}) + "\\n")
def out(**ev):
    print(json.dumps(ev), flush=True)
out(type="system", subtype="init", session_id="sess-1")
if mode == "ok":
    out(type="assistant", session_id="sess-1", message={{"content": [{{"type": "text", "text": "Bonjour"}}]}})
    out(type="result", subtype="success", is_error=False, result="Fini", session_id="sess-1",
        duration_ms=4200, total_cost_usd=0.5)
elif mode == "limit":
    out(type="result", subtype="success", is_error=True, result="Claude AI usage limit reached|1793000000",
        session_id="sess-1")
    sys.exit(1)
elif mode == "fail":
    out(type="result", subtype="error_during_execution", is_error=True, result="Une erreur", session_id="sess-1")
    sys.exit(1)
elif mode == "crash":
    sys.exit(3)
elif mode == "slow":
    import time
    time.sleep(60)
"""

FAKE_GAGARINE = """#!{python}
import json, os, sys
args = sys.argv[1:]
open(os.environ["FAKE_GAGARINE_LOG"], "a").write(json.dumps(args) + "\\n")
print("  en file d'attente (messages de gagarine qui ne doivent pas finir dans le journal)")
i = args.index("--")
os.execv(args[i + 1], args[i + 1:])
"""


def script(path, text):
    path.write_text(text.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


class RunnerCase(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.claude = script(self.bin / "claude", FAKE_CLAUDE)
        self.gagarine = script(self.bin / "gagarine", FAKE_GAGARINE)
        self.log = self.home / "claude.log"
        self.glog = self.home / "gagarine.log"
        self.work = self.home / "proj"
        self.work.mkdir()
        self.env = dict(os.environ, FAKE_LOG=str(self.log), FAKE_GAGARINE_LOG=str(self.glog), FAKE_MODE="ok")
        self.procs = []

    def tearDown(self):
        for t in tasks.all():
            if t.id in task_runner._PROCS:
                task_runner.stop(t)
        task_runner._PROCS.clear()
        super().tearDown()

    def new(self, **kw):
        return tasks.add("Corrige les tests", cwd=str(self.work), **kw)

    def run_task(self, task, mode="ok", gagarine=None, resume=False, timeout=15):
        self.env["FAKE_MODE"] = mode
        task_runner.start(task, NOW, resume=resume, attempts=1 if resume else 0, claude=self.claude,
                          gagarine=gagarine, env=self.env)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            res = task_runner.poll(tasks.get(task.id), NOW + timedelta(seconds=5))
            if res is not None:
                return res
            time.sleep(0.05)
        self.fail("la tâche ne se termine pas")

    def calls(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()]


class CommandTest(RunnerCase):
    def test_arguments_follow_rights_model_and_message(self):
        t = self.new(rights="modifications", model="opus")
        argv = task_runner.claude_argv(t, claude="claude")
        self.assertEqual(argv[:5], ["claude", "-p", "--output-format", "stream-json", "--verbose"])
        self.assertIn("--permission-mode", argv)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "acceptEdits")
        self.assertEqual(argv[argv.index("--model") + 1], "opus")
        self.assertEqual(argv[-2:], ["--", "Corrige les tests"])

    def test_rights_read_only_has_no_permission_option_and_all_is_bypass(self):
        self.assertNotIn("--permission-mode", task_runner.claude_argv(self.new(rights="lecture"), claude="c"))
        argv = task_runner.claude_argv(self.new(rights="tout"), claude="c")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "bypassPermissions")

    def test_message_starting_with_a_dash_stays_a_message(self):
        t = tasks.add("--help", cwd=str(self.work))
        self.assertEqual(task_runner.claude_argv(t, claude="c")[-2:], ["--", "--help"])

    def test_resume_uses_session_and_continue(self):
        t = self.new()
        with self.assertRaises(ValueError):
            task_runner.claude_argv(t, resume=True, claude="c")
        t = tasks.update(t.id, session_id="sess-1")
        argv = task_runner.claude_argv(t, resume=True, claude="c")
        self.assertEqual(argv[argv.index("--resume") + 1], "sess-1")
        self.assertEqual(argv[-2:], ["--", "continue"])

    def test_gagarine_wraps_in_background_priority(self):
        t = self.new()
        argv = task_runner.build_command(t, claude="c", gagarine="/x/gagarine")
        self.assertEqual(argv[:8], ["/x/gagarine", "file", "--priorite", "fond", f"ccs tâche {t.id}", "1", "1", "--"])
        self.assertEqual(argv[8:10], ["sh", "-c"])
        self.assertEqual(task_runner.build_command(t, claude="c")[0], "sh")

    def test_environment_drops_parent_session_variables(self):
        os.environ["CLAUDECODE"] = "1"
        self.addCleanup(os.environ.pop, "CLAUDECODE", None)
        self.assertNotIn("CLAUDECODE", task_runner.environment())


class RunTest(RunnerCase):
    def test_success_without_gagarine(self):
        t = self.new()
        res = self.run_task(t)
        self.assertTrue(res.ok)
        self.assertFalse(res.limit)
        self.assertEqual((res.session_id, res.duration, res.cost), ("sess-1", 4.2, 0.5))
        call = self.calls()[0]
        self.assertEqual(os.path.realpath(call["cwd"]), os.path.realpath(self.work))
        self.assertEqual(call["args"][-2:], ["--", "Corrige les tests"])
        self.assertEqual(oct(tasks.journal_path(t.id).stat().st_mode & 0o777), "0o600")
        text = "\n".join(task_runner.readable(x) for x in tasks.journal_path(t.id).read_text().splitlines())
        self.assertIn("Bonjour", text)
        self.assertIn("✓ Fini", text)
        got = tasks.get(t.id)
        self.assertEqual((got.state, got.account), ("running", "perso"))

    def test_through_gagarine_queue_keeps_its_messages_out_of_the_journal(self):
        t = self.new()
        res = self.run_task(t, gagarine=self.gagarine)
        self.assertTrue(res.ok)
        queued = json.loads(self.glog.read_text().splitlines()[0])
        self.assertEqual(queued[:6], ["file", "--priorite", "fond", f"ccs tâche {t.id}", "1", "1"])
        self.assertNotIn("gagarine", tasks.journal_path(t.id).read_text())
        self.assertTrue(tasks.get(t.id).extra["queued"])

    def test_limit_detected_with_session_for_resume(self):
        res = self.run_task(self.new(), mode="limit")
        self.assertTrue(res.limit)
        self.assertFalse(res.ok)
        self.assertEqual(res.session_id, "sess-1")

    def test_failure_has_the_error_text(self):
        res = self.run_task(self.new(), mode="fail")
        self.assertFalse(res.ok or res.limit)
        self.assertEqual(res.error, "Une erreur")

    def test_crash_without_result(self):
        res = self.run_task(self.new(), mode="crash")
        self.assertFalse(res.ok or res.limit)
        self.assertIn("code 3", res.error)

    def test_resume_appends_to_the_journal_and_only_reads_the_new_part(self):
        t = self.new()
        self.run_task(t, mode="limit")
        t = tasks.update(t.id, state="waiting", session_id="sess-1")
        res = self.run_task(t, mode="ok", resume=True)
        self.assertTrue(res.ok)                       # la limite du premier lancement n'est plus lue
        self.assertEqual(self.calls()[1]["args"][-2:], ["--", "continue"])
        self.assertIn("--resume", self.calls()[1]["args"])
        lines = tasks.journal_path(t.id).read_text().splitlines()
        self.assertGreater(len(lines), 4)
        self.assertEqual(sum(1 for x in lines if '"type": "ccs"' in x), 2)

    def test_stop_kills_a_running_task(self):
        t = self.new()
        self.env["FAKE_MODE"] = "slow"
        task_runner.start(t, NOW, claude=self.claude, gagarine=None, env=self.env)
        pid = tasks.get(t.id).pid
        self.assertTrue(task_runner._alive(pid))
        task_runner.stop(tasks.get(t.id))
        self.assertFalse(task_runner._alive(pid))

    def test_poll_waits_for_a_process_started_before_a_restart(self):
        t = self.new()
        tasks.update(t.id, state="running", pid=os.getpid())     # vivant, inconnu de ce processus
        self.assertIsNone(task_runner.poll(tasks.get(t.id), NOW))

    def test_total_cost_comes_from_claude_code_journal_when_found(self):
        t = self.new()
        proj = self.home / ".claude" / "projects" / "-home-proj"
        entry = {"type": "assistant", "timestamp": "2026-11-12T10:00:00Z", "message": {
            "model": "claude-sonnet-4-5", "id": "m1", "usage": {"input_tokens": 1_000_000, "output_tokens": 0}}}
        write(proj / "sess-1.jsonl", json.dumps(entry) + "\n")
        res = self.run_task(t)
        self.assertTrue(res.total)
        self.assertGreater(res.cost, 0.5)


class ReadableTest(unittest.TestCase):
    def test_lines(self):
        r = task_runner.readable
        self.assertEqual(r("pas du json"), "pas du json")
        self.assertEqual(r(json.dumps({"type": "system"})), "")
        self.assertEqual(r(json.dumps({"type": "result", "is_error": True, "result": "Oups\nsuite"})), "✗ Oups")
        self.assertEqual(r(json.dumps({"type": "ccs", "resume": True})), "— reprise")
        self.assertEqual(r("[1, 2]"), "")

    def test_limit_events(self):
        L = task_runner.is_limit_event
        self.assertTrue(L({"type": "result", "is_error": True, "result": "Claude AI usage limit reached|1"}))
        self.assertTrue(L({"type": "assistant", "error": "rate_limit"}))
        self.assertTrue(L({"type": "rate_limit_event", "rate_limit_info": {"status": "rejected"}}))
        self.assertFalse(L({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}}))
        self.assertFalse(L({"type": "result", "is_error": False, "result": "limit reached dans le code"}))
        self.assertFalse(L({"type": "result", "is_error": True, "result": "Une erreur"}))


def state(session=10, name="perso", now=NOW):
    return {"orchestrator": {}, "accounts": [
        {"name": name, "active": True, "fetched_at": now.timestamp(), "error": None, "limits": [
            {"kind": "session", "label": "Session", "percent": session,
             "resets_at": (now + timedelta(hours=3)).isoformat()}]},
        {"name": "pro", "active": False, "fetched_at": now.timestamp(), "error": None, "limits": [
            {"kind": "session", "label": "Session", "percent": 5,
             "resets_at": (now + timedelta(hours=3)).isoformat()}]}]}


class PrepareTest(RunnerCase):
    def prepare(self, task, st, switch=None, active="perso"):
        decisions = []
        sw = switch or (lambda d: decisions.append(d) or True)
        return task_runner.prepare(task, st, None, NOW, switch=sw, active=active), decisions

    def test_no_switch_below_threshold(self):
        (ok, _), decisions = self.prepare(self.new(), state(session=50))
        self.assertTrue(ok)
        self.assertEqual(decisions, [])

    def test_switches_when_active_is_over_threshold(self):
        (ok, _), decisions = self.prepare(self.new(), state(session=99))
        self.assertTrue(ok)
        self.assertEqual([d.target for d in decisions], ["pro"])

    def test_switch_failure_makes_the_task_wait(self):
        (ok, msg), _ = self.prepare(self.new(), state(session=99), switch=lambda d: False)
        self.assertFalse(ok)
        self.assertIn("pro", msg)

    def test_no_other_account_available(self):
        st = state(session=99)
        st["accounts"][1]["limits"][0]["percent"] = 100
        (ok, msg), _ = self.prepare(self.new(), st)
        self.assertFalse(ok)
        self.assertIn("aucun compte disponible", msg)

    def test_resume_after_limit_switches_unless_account_already_changed(self):
        t = tasks.update(self.new().id, state="waiting", account="perso", session_id="s")
        (ok, _), decisions = self.prepare(t, state(session=60), active="perso")
        self.assertTrue(ok)
        self.assertEqual(len(decisions), 1)                 # compte inchangé : bascule
        (ok, _), decisions = self.prepare(t, state(session=60), active="pro")
        self.assertEqual((ok, decisions), (True, []))       # déjà basculé ailleurs

    def test_never_during_a_pause(self):
        from ccs_app import pause
        pause.set_pause(NOW + timedelta(hours=1), now=NOW)
        (ok, msg), decisions = self.prepare(self.new(), state(session=99))
        self.assertEqual((ok, msg, decisions), (False, "CCS est en pause", []))


if __name__ == "__main__":
    unittest.main()
