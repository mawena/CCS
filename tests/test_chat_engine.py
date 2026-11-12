"""Moteur du chat (ccs_app/chat_engine) contre le faux `claude` de tests/fake_claude.py."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from ccs_app import chat_engine as eng
from ccs_app import chat_protocol as proto
from ccs_app.chat_options import ChatOptions

ROOT = Path(__file__).resolve().parent
FAKE = str(ROOT / "fake_claude.py")
FIX = ROOT / "fixtures" / "chat"
SCEN_LOCAL = str(FIX / "init-effort-controles.jsonl")      # 4 tours de commandes locales /effort
SCEN_PERM = str(FIX / "permissions-allow-toujours.jsonl")  # tour 1 : demande d'autorisation
SCEN_DENY = str(FIX / "refus-et-interruption.jsonl")       # tour 1 : autorisation, tour 2 : interruption
TIMEOUT = 20  # délai de garde : aucun test ne peut se bloquer


class Collector:
    """Reçoit les événements du fil de lecture ; attend une condition avec un délai."""

    def __init__(self):
        self.events = []
        self.cond = threading.Condition()

    def __call__(self, ev):
        with self.cond:
            self.events.append(ev)
            self.cond.notify_all()

    def wait(self, pred, timeout=TIMEOUT):
        with self.cond:
            ok = self.cond.wait_for(lambda: pred(self.events), timeout)
        if not ok:
            raise AssertionError(f"délai dépassé ; événements : {[type(e).__name__ for e in self.events]}")

    def of(self, cls):
        with self.cond:
            return [e for e in self.events if isinstance(e, cls)]

    def states(self):
        return [e.state for e in self.of(eng.StateChanged)]

    def wait_state(self, state, count=1):
        self.wait(lambda evs: sum(1 for e in evs if isinstance(e, eng.StateChanged) and e.state == state) >= count)

    def wait_exit(self, count=1):
        self.wait(lambda evs: sum(1 for e in evs if isinstance(e, eng.ProcessExited)) >= count)


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.argv_log = os.path.join(self.tmp.name, "argv.log")
        self.col = Collector()
        self.env_extra = {}
        self.sessions = []

    def make(self, scenario, session_id=None, options=None, clock=time.time, claude=FAKE, **env):
        environ = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "FAKE_CLAUDE_SCENARIO": scenario,
                   "FAKE_CLAUDE_ARGV_LOG": self.argv_log, **{k: str(v) for k, v in env.items()}}
        s = eng.ChatSession(self.tmp.name, session_id=session_id, options=options or ChatOptions(),
                            on_event=self.col, claude=claude, environ=environ, clock=clock)
        self.sessions.append(s)
        self.addCleanup(s.stop, 1)
        return s

    def argvs(self):
        try:
            with open(self.argv_log, encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
        except OSError:
            return []

    def wait_argvs(self, n):
        deadline = time.time() + TIMEOUT
        while time.time() < deadline:
            if len(self.argvs()) >= n:
                return self.argvs()
            time.sleep(0.05)
        raise AssertionError("le faux claude n'a pas noté ses arguments")


class ChatEngineTest(EngineCase):
    def test_first_send_starts_process_and_streams_text(self):
        s = self.make(SCEN_PERM)
        self.assertEqual(s.state, "stopped")
        self.assertTrue(s.send("Lance touch"))
        self.assertEqual(s.state, "busy")
        self.assertIsNotNone(s.pid)
        self.col.wait_state("permission")
        self.assertTrue(s.answer(self.col.of(proto.PermissionRequest)[0].request_id, "allow"))
        self.col.wait_state("idle")
        self.assertTrue(self.col.of(proto.Hello))
        self.assertTrue(self.col.of(proto.Init))
        self.assertTrue(self.col.of(proto.TextDelta) or self.col.of(proto.AssistantText))
        self.assertTrue(self.col.of(proto.TurnResult)[0].ok)
        self.assertIn("starting", self.col.states())
        self.assertEqual(self.col.states()[-1], "idle")
        argv = self.argvs()[0]
        for flag in ("-p", "--input-format", "--output-format", "--verbose", "--include-partial-messages",
                     "--permission-prompt-tool", "--permission-mode"):
            self.assertIn(flag, argv)
        self.assertNotIn("--resume", argv)
        self.assertTrue(s.session_id)

    def test_send_while_busy_is_refused(self):
        s = self.make(SCEN_PERM, FAKE_CLAUDE_DELAY_MS=30)
        self.assertTrue(s.send("un"))
        self.assertFalse(s.send("deux"))
        self.assertFalse(s.send("trois"))
        # rien d'autre n'a été écrit : un seul processus lancé
        self.col.wait_state("permission")
        self.assertFalse(s.send("pendant une autorisation"))
        self.assertEqual(len(self.wait_argvs(1)), 1)

    def test_interrupt_then_send_resumes(self):
        s = self.make(SCEN_DENY)
        s.send("un")
        self.col.wait_state("permission")
        s.answer(self.col.of(proto.PermissionRequest)[0].request_id, "deny", "Non.")
        self.col.wait_state("idle")
        self.assertTrue(s.send("deux"))
        self.col.wait(lambda evs: sum(1 for e in evs if isinstance(e, proto.Init)) >= 2)
        self.assertTrue(s.interrupt())
        self.col.wait_exit()
        self.col.wait_state("stopped")
        exited = self.col.of(eng.ProcessExited)[0]
        self.assertEqual(exited.code, 1)
        self.assertTrue(exited.requested)  # arrêt demandé : pas d'encart d'erreur
        self.assertTrue(any(r.interrupted for r in self.col.of(proto.TurnResult)))
        self.assertIsNone(s.pid)
        sid = s.session_id
        self.assertTrue(sid)
        self.assertTrue(s.send("trois"))  # relance par --resume
        argv = self.wait_argvs(2)[1]
        self.assertEqual(argv[argv.index("--resume") + 1], sid)

    def test_permission_round_trip_allow(self):
        s = self.make(SCEN_PERM)
        s.send("touch")
        self.col.wait_state("permission")
        req = self.col.of(proto.PermissionRequest)[0]
        self.assertEqual(req.tool_name, "Bash")
        self.assertEqual(s.state, "permission")
        self.assertFalse(s.answer("inconnu", "allow"))
        self.assertTrue(s.answer(req.request_id, "allow"))
        self.col.wait_state("idle")
        self.assertTrue(self.col.of(proto.ToolResult))
        self.assertIn("busy", self.col.states()[self.col.states().index("permission"):])

    def test_permission_deny(self):
        s = self.make(SCEN_DENY)
        s.send("touch")
        self.col.wait_state("permission")
        req = self.col.of(proto.PermissionRequest)[0]
        self.assertTrue(s.answer(req.request_id, "deny", "Refusé par le test."))
        self.col.wait_state("idle")
        self.assertTrue(self.col.of(proto.TurnResult)[0].ok)
        self.assertEqual(s.state, "idle")

    def test_set_model_live(self):
        s = self.make(SCEN_LOCAL)
        s.send("/effort high")
        self.col.wait_state("idle")
        pid = s.pid
        s.set_options(ChatOptions(model="sonnet"))
        self.col.wait(lambda evs: any(isinstance(e, proto.ControlReply) and e.data.get("model") == "claude-sonnet-5-5"
                                      for e in evs))
        s.set_options(ChatOptions(model="sonnet", rights="plan"))
        self.col.wait(lambda evs: any(isinstance(e, proto.Status) and e.permission_mode == "plan" for e in evs))
        self.assertEqual(s.pid, pid)  # aucune relance
        self.assertEqual(len(self.argvs()), 1)
        self.assertEqual(s.state, "idle")

    def test_effort_change_applies_before_next_message(self):
        s = self.make(SCEN_LOCAL)
        s.send("premier")
        self.col.wait_state("idle")
        s.set_options(ChatOptions(effort="low"))
        self.assertEqual(s.effort, "low")
        self.assertEqual(s.state, "idle")  # rien n'est envoyé tant qu'aucun message ne part
        self.assertEqual(len(self.col.of(proto.LocalCommand)), 1)
        self.assertTrue(s.send("second"))
        self.col.wait(lambda evs: len([e for e in evs if isinstance(e, eng.StateChanged) and e.state == "idle"]) >= 2)
        # `/effort low` a joué le tour 2 en silence ; le message a joué le tour 3 et reste montré
        self.assertEqual(len(self.col.of(proto.LocalCommand)), 2)
        self.assertEqual(s.state, "idle")

    def test_effort_and_ultracode_commands_in_order(self):
        s = self.make(SCEN_LOCAL)
        s.send("premier")
        self.col.wait_state("idle")
        s.set_options(ChatOptions(effort="high", ultracode=True))
        self.assertEqual(s._pending_cmds, ["/effort high", "/effort ultracode"])
        s._pending_cmds.clear()
        s.set_options(ChatOptions(effort="high", ultracode=False))
        self.assertEqual(s._pending_cmds, ["/effort ultracode off"])

    def test_options_before_start_go_to_launch_args(self):
        s = self.make(SCEN_LOCAL, options=ChatOptions(model="haiku", effort="high", rights="plan"))
        s.set_options(ChatOptions(model="sonnet", effort="max", rights="acceptEdits"))
        s.send("x")
        argv = self.wait_argvs(1)[0]
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")
        self.assertEqual(argv[argv.index("--effort") + 1], "max")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "acceptEdits")

    def test_resume_uses_session_id(self):
        s = self.make(SCEN_LOCAL, session_id="abc-123")
        s.send("x")
        argv = self.wait_argvs(1)[0]
        self.assertEqual(argv[argv.index("--resume") + 1], "abc-123")
        self.col.wait_state("idle")
        self.assertEqual(s.session_id, "abc-123")  # le faux reprend l'identifiant demandé

    def test_context_usage_event(self):
        s = self.make(SCEN_LOCAL)
        s.send("x")
        self.col.wait_state("idle")
        self.assertTrue(s.request_context())
        self.col.wait(lambda evs: any(isinstance(e, eng.ContextUsage) for e in evs))
        usage = self.col.of(eng.ContextUsage)[0]
        self.assertGreater(usage.maximum, 0)
        self.assertGreaterEqual(usage.total, 0)

    def test_suspend_after_idle_and_resume_on_send(self):
        now = [1000.0]
        s = self.make(SCEN_LOCAL, clock=lambda: now[0])
        s.send("x")
        self.col.wait_state("idle")
        self.assertFalse(s.suspend_if_idle(now[0] + 10, 60))  # pas assez longtemps
        self.assertEqual(s.state, "idle")
        self.assertTrue(s.suspend_if_idle(now[0] + 120, 60))
        self.assertEqual(s.state, "suspended")
        self.col.wait_exit()
        self.assertEqual(s.state, "suspended")  # la fin du processus ne l'écrase pas
        self.assertTrue(self.col.of(eng.ProcessExited)[0].requested)
        sid = s.session_id
        self.assertTrue(sid)
        self.assertTrue(s.send("encore"))
        argv = self.wait_argvs(2)[1]
        self.assertEqual(argv[argv.index("--resume") + 1], sid)
        self.col.wait_state("idle", count=2)

    def test_no_suspend_while_permission_pending(self):
        now = [1000.0]
        s = self.make(SCEN_PERM, clock=lambda: now[0])
        s.send("touch")
        self.col.wait_state("permission")
        self.assertFalse(s.suspend_if_idle(now[0] + 10 ** 6, 1))
        self.assertEqual(s.state, "permission")
        self.assertIsNotNone(s.pid)
        # même si l'état disait « idle », une autorisation en attente ou un outil ouvert interdit la veille
        s.state = "idle"
        self.assertFalse(s.suspend_if_idle(now[0] + 10 ** 6, 1))
        s._perms.clear()
        s._open_tools.add("toolu_x")
        self.assertFalse(s.suspend_if_idle(now[0] + 10 ** 6, 1))

    def test_process_dies_at_start(self):
        s = self.make(SCEN_LOCAL, FAKE_CLAUDE_EXIT=1)
        s.send("x")  # le processus sort tout de suite : le résultat de send importe peu
        self.col.wait_exit()
        self.col.wait_state("stopped")
        exited = self.col.of(eng.ProcessExited)[0]
        self.assertEqual(exited.code, 1)
        self.assertIn("Not logged in", exited.stderr_tail)
        self.assertFalse(exited.requested)
        time.sleep(0.2)
        self.assertEqual(s.state, "stopped")  # jamais « busy » après la mort
        self.assertIsNone(s.pid)

    def test_binary_missing(self):
        s = self.make(SCEN_LOCAL, claude="/nonexistent/claude")
        self.assertFalse(s.send("x"))
        self.assertEqual(s.state, "stopped")
        exited = self.col.of(eng.ProcessExited)[0]
        self.assertEqual(exited.code, 127)
        self.assertIn("claude", exited.stderr_tail)

    def test_two_megabyte_line_is_parsed(self):
        s = self.make(SCEN_LOCAL, FAKE_CLAUDE_BIG_LINE=2_000_000)
        s.send("x")
        self.col.wait_state("idle")
        big = [r for r in self.col.of(proto.ToolResult) if len(r.text) >= 2_000_000]
        self.assertEqual(len(big), 1)
        self.assertEqual(len(big[0].text), 2_000_000)

    def test_stop_kills_only_own_pid(self):
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(other.kill)
        s = self.make(SCEN_LOCAL)
        s.send("x")
        self.col.wait_state("idle")
        pid = s.pid
        self.assertIsNotNone(pid)
        s.stop(grace_s=2)
        self.assertEqual(s.state, "stopped")
        self.col.wait_exit()
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertIsNone(other.poll())  # le processus étranger tourne toujours
        self.assertTrue(self.col.of(eng.ProcessExited)[0].requested)

    def test_stop_without_process_is_harmless(self):
        s = self.make(SCEN_LOCAL)
        s.stop(grace_s=1)
        self.assertEqual(s.state, "stopped")


if __name__ == "__main__":
    unittest.main()
