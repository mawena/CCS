"""Protocole stream-json de Claude Code (essai réel du 12/11/2026) et faux `claude`."""

import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from ccs_app import chat_protocol as cp

FIXTURES = Path(__file__).parent / "fixtures" / "chat"
FAKE = Path(__file__).parent / "fake_claude.py"


def recu(name):
    """Les lignes « recu » d'un jeu d'essai, en texte, dans l'ordre."""
    out = []
    for line in (FIXTURES / f"{name}.jsonl").read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry["dir"] == "recu":
            out.append(json.dumps(entry["data"]))
    return out


def events(name):
    return [ev for line in recu(name) for ev in cp.parse_line(line)]


def of_type(evs, cls):
    return [e for e in evs if isinstance(e, cls)]


def j(obj):
    return json.dumps(obj)


class ParseTest(unittest.TestCase):
    def test_init_fields(self):
        init = of_type(events("lancement-effort-ultracode"), cp.Init)[0]
        self.assertEqual(init.model, "claude-haiku-5-5")
        self.assertEqual(init.permission_mode, "default")
        self.assertEqual(init.slash_commands, ("compact", "clear", "review"))
        self.assertRegex(init.session_id, r"^[0-9a-f-]{36}$")

    def test_hello_from_initialize_response(self):
        hello = of_type(events("init-effort-controles"), cp.Hello)[0]
        self.assertEqual([c[0] for c in hello.commands], ["compact", "clear", "review"])
        self.assertIn("opus", [m[0] for m in hello.models])
        self.assertEqual(hello.permission_mode, "default")
        self.assertIn("ui_surface_v1", hello.capabilities)

    def test_text_deltas_and_full_text(self):
        evs = j({"type": "stream_event", "api_message_id": "msg_1", "parent_tool_use_id": None, "event": {
            "type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Bon"}}})
        self.assertEqual(cp.parse_line(evs), [cp.TextDelta("msg_1", 1, "Bon")])
        full = j({"type": "assistant", "message": {"id": "msg_1", "content": [{"type": "text", "text": "Bonjour"}]}})
        self.assertEqual(cp.parse_line(full), [cp.AssistantText("msg_1", "Bonjour")])
        # Sur le flux réel : des deltas de texte, puis le texte complet.
        real = events("refus-et-interruption")
        self.assertTrue(of_type(real, cp.AssistantText))

    def test_thinking_is_reported(self):
        evs = events("permissions-allow-toujours")
        self.assertTrue(of_type(evs, cp.Thinking))

    def test_tool_use_and_result_pair_by_id(self):
        evs = events("permissions-allow-toujours")
        use = of_type(evs, cp.ToolUse)[0]
        result = of_type(evs, cp.ToolResult)[0]
        self.assertEqual(use.name, "Bash")
        self.assertEqual(use.input["command"], "touch essai1.txt && ls -l essai1.txt")
        self.assertIsNone(use.parent_id)
        self.assertEqual(result.tool_id, use.tool_id)
        self.assertFalse(result.is_error)
        self.assertIn("essai1.txt", result.text)

    def test_tool_result_parts_and_subagent_parent(self):
        line = j({"type": "user", "parent_tool_use_id": "toolu_P", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_X", "is_error": True,
             "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}]}})
        self.assertEqual(cp.parse_line(line), [cp.ToolResult("toolu_X", "a\nb", True, "toolu_P")])

    def test_todos_from_tool_use(self):
        todos = [{"content": "Écrire", "status": "completed", "activeForm": "Écriture"},
                 {"content": "Tester", "status": "in_progress", "activeForm": "Test"}]
        line = j({"type": "assistant", "message": {"id": "m", "content": [
            {"type": "tool_use", "id": "toolu_T", "name": "TodoWrite", "input": {"todos": todos}}]}})
        evs = cp.parse_line(line)
        self.assertIsInstance(evs[0], cp.ToolUse)
        self.assertEqual(evs[1], cp.Todos((("Écrire", "completed"), ("Tester", "in_progress"))))

    def test_permission_request_shape(self):
        req = of_type(events("permissions-allow-toujours"), cp.PermissionRequest)[0]
        self.assertEqual(req.tool_name, "Bash")
        self.assertEqual(req.display_name, "Bash")
        self.assertEqual(req.input["command"], "touch essai1.txt && ls -l essai1.txt")
        self.assertEqual(req.description, "Create essai1.txt in the working directory")
        self.assertEqual(req.blocked_path, "/tmp/essai/projet/essai1.txt")
        self.assertEqual([s["type"] for s in req.suggestions], ["addRules", "addDirectories", "setMode"])
        self.assertFalse(hasattr(req, "title"))

    def test_permission_request_from_a_subagent(self):
        line = j({"type": "control_request", "request_id": "r9", "request": {
            "subtype": "can_use_tool", "tool_name": "Bash", "input": {"command": "ls"},
            "agent_id": "agent-42"}})
        req = cp.parse_line(line)[0]
        self.assertEqual(req.agent_id, "agent-42")
        self.assertIsNone(cp.parse_line(line.replace(', "agent_id": "agent-42"', ""))[0].agent_id)

    def test_permission_request_without_optional_fields(self):
        line = j({"type": "control_request", "request_id": "r1", "request": {
            "subtype": "can_use_tool", "tool_name": "Read", "input": {"file_path": "/x"}}})
        req = cp.parse_line(line)[0]
        self.assertEqual((req.display_name, req.blocked_path, req.suggestions, req.description),
                         ("Read", None, [], ""))

    def test_interrupted_result_flagged(self):
        results = of_type(events("refus-et-interruption"), cp.TurnResult)
        self.assertFalse(results[0].interrupted)
        self.assertTrue(results[-1].interrupted)
        self.assertEqual(results[-1].subtype, "error_during_execution")
        self.assertFalse(results[-1].ok)

    def test_success_result_fields(self):
        res = of_type(events("permissions-allow-toujours"), cp.TurnResult)[0]
        self.assertTrue(res.ok)
        self.assertEqual(res.text, "OK")
        self.assertAlmostEqual(res.cost_usd, 0.00524697)
        self.assertEqual(res.context_window, 1000000)
        self.assertIn("claude-haiku-5-5", res.turn_usage)
        self.assertFalse(res.is_limit)

    def test_effort_command_result_is_local(self):
        evs = events("init-effort-controles")
        local = of_type(evs, cp.LocalCommand)
        self.assertEqual(len(local), 4)
        self.assertTrue(local[0].text.startswith("Set effort level to high"))
        # Une commande locale n'est jamais un tour du modèle, ni une réponse de l'assistant.
        self.assertEqual(of_type(evs, cp.TurnResult), [])
        self.assertEqual(of_type(evs, cp.AssistantText), [])

    def test_status_carries_permission_mode(self):
        evs = events("init-effort-controles")
        self.assertEqual([e.permission_mode for e in of_type(evs, cp.Status)], ["acceptEdits", "default"])
        # `status: requesting` sans changement de mode : rien.
        self.assertEqual(cp.parse_line(j({"type": "system", "subtype": "status", "status": "requesting"})), [])

    def test_control_reply_ok_and_error(self):
        evs = events("init-effort-controles")
        replies = of_type(evs, cp.ControlReply)
        by_id = {r.request_id: r for r in replies}
        self.assertTrue(by_id["req_3"].ok)
        self.assertEqual(by_id["req_3"].data, {"model": "claude-sonnet-5-5"})
        self.assertFalse(by_id["req_7"].ok)
        self.assertIn("Unsupported control request subtype", by_id["req_7"].error)
        context = [r for r in replies if "totalTokens" in r.data][0]
        self.assertIsInstance(context.data["percentage"], int)

    def test_limit_result_is_flagged(self):
        line = j({"type": "result", "subtype": "success", "is_error": True,
                  "result": "Claude usage limit reached. Your limit will reset at 5pm."})
        res = cp.parse_line(line)[0]
        self.assertTrue(res.is_limit)
        self.assertFalse(res.ok)

    def test_rate_limit_event_only_when_rejected(self):
        allowed = of_type(events("permissions-allow-toujours"), cp.Unknown)
        self.assertEqual(allowed, [])
        rejected = j({"type": "rate_limit_event", "rate_limit_info": {"status": "rejected"}})
        self.assertIsInstance(cp.parse_line(rejected)[0], cp.Unknown)

    def test_compacted_and_retrying(self):
        compact = cp.parse_line(j({"type": "system", "subtype": "compact_boundary",
                                   "compact_metadata": {"trigger": "auto", "pre_tokens": 150000}}))
        self.assertEqual(compact, [cp.Compacted(150000, "auto")])
        retry = cp.parse_line(j({"type": "system", "subtype": "api_retry", "attempt": 2, "retry_delay_ms": 1500}))
        self.assertEqual(retry, [cp.Retrying(2, 1.5)])

    def test_noise_is_dropped(self):
        for ev in ({"type": "system", "subtype": "hook_response", "output": "x" * 100},
                   {"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 5}):
            self.assertEqual(cp.parse_line(j(ev)), [])

    def test_unknown_event_is_kept_not_raised(self):
        raw = {"type": "brand_new", "x": 1}
        self.assertEqual(cp.parse_line(j(raw)), [cp.Unknown(raw)])
        odd = {"type": "assistant", "message": 12}
        self.assertEqual(cp.parse_line(j(odd)), [])
        weird = {"type": "result", "modelUsage": 5, "total_cost_usd": "x"}
        self.assertIsInstance(cp.parse_line(j(weird))[0], cp.TurnResult)

    def test_garbage_line_gives_nothing(self):
        for line in ("", "pas du json", "{", "[1, 2]", "42", "null", None):
            self.assertEqual(cp.parse_line(line), [])

    def test_every_fixture_line_parses(self):
        for path in FIXTURES.glob("*.jsonl"):
            for entry in map(json.loads, path.read_text(encoding="utf-8").splitlines()):
                if entry["dir"] == "recu":
                    cp.parse_line(json.dumps(entry["data"]))


class WriteTest(unittest.TestCase):
    def test_lines_end_with_newline_and_are_ascii(self):
        for line in (cp.user_message("é "), cp.control("interrupt", "r1"), cp.allow("r", {"a": "é"}),
                     cp.deny("r", "non")):
            self.assertTrue(line.endswith("\n"))
            self.assertEqual(line.count("\n"), 1)
            self.assertTrue(line.isascii())

    def test_user_message_text(self):
        msg = json.loads(cp.user_message("Bonjour"))
        self.assertEqual(msg, {"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": "Bonjour"}]}, "parent_tool_use_id": None})

    def test_user_message_with_image_is_base64(self):
        data = bytes(range(256))
        msg = json.loads(cp.user_message("Regarde", [("image/png", data)]))
        text, image = msg["message"]["content"]
        self.assertEqual(text["type"], "text")
        self.assertEqual(image["type"], "image")
        self.assertEqual(image["source"]["type"], "base64")
        self.assertEqual(image["source"]["media_type"], "image/png")
        self.assertEqual(base64.b64decode(image["source"]["data"]), data)

    def test_control_request(self):
        msg = json.loads(cp.control("set_model", "req_9", model="sonnet"))
        self.assertEqual(msg, {"type": "control_request", "request_id": "req_9",
                               "request": {"subtype": "set_model", "model": "sonnet"}})
        self.assertEqual(json.loads(cp.control("initialize", "req_1"))["request"], {"subtype": "initialize"})

    def test_allow_matches_real_flow(self):
        msg = json.loads(cp.allow("rid", {"command": "ls"}))
        self.assertEqual(msg, {"type": "control_response", "response": {
            "subtype": "success", "request_id": "rid",
            "response": {"behavior": "allow", "updatedInput": {"command": "ls"}}}})

    def test_allow_always_carries_suggestions(self):
        rule = {"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "touch a"}],
                "behavior": "allow", "destination": "localSettings"}
        body = json.loads(cp.allow_always("rid", {"command": "touch a"}, [rule]))["response"]["response"]
        self.assertEqual(body["behavior"], "allow")
        self.assertEqual(body["updatedInput"], {"command": "touch a"})
        self.assertEqual(body["updatedPermissions"], [rule])

    def test_allow_always_keeps_only_add_rules(self):
        rule = {"type": "addRules", "rules": [], "behavior": "allow", "destination": "localSettings"}
        others = [{"type": "addDirectories", "directories": ["/p"], "destination": "session"},
                  {"type": "setMode", "mode": "acceptEdits", "destination": "session"}]
        body = json.loads(cp.allow_always("r", {}, others[:1] + [rule] + others[1:]))["response"]["response"]
        self.assertEqual(body["updatedPermissions"], [rule])
        only_mode = json.loads(cp.allow_always("r", {}, others))["response"]["response"]
        self.assertNotIn("updatedPermissions", only_mode)
        self.assertEqual(only_mode["behavior"], "allow")

    def test_deny_message(self):
        body = json.loads(cp.deny("rid", "Refusé."))["response"]["response"]
        self.assertEqual(body, {"behavior": "deny", "message": "Refusé."})
        body = json.loads(cp.deny("rid", "Stop", interrupt=True))["response"]["response"]
        self.assertTrue(body["interrupt"])


class FakeClaudeTest(unittest.TestCase):
    """Le faux `claude` rejoue les scénarios comme le flux réel."""

    def start(self, scenario, **env):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.argv_log = os.path.join(self.tmp.name, "argv.jsonl")
        full = {**os.environ, "FAKE_CLAUDE_ARGV_LOG": self.argv_log, **env}
        if scenario:
            full["FAKE_CLAUDE_SCENARIO"] = str(FIXTURES / f"{scenario}.jsonl")
        self.proc = subprocess.Popen([sys.executable, str(FAKE), "-p", "--model", "haiku"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, env=full)
        self.addCleanup(self.close_pipes, self.proc)
        # Garde-fou : un scénario qui attend pour rien ne doit pas bloquer la suite.
        watchdog = threading.Timer(15, self.proc.kill)
        watchdog.daemon = True
        watchdog.start()
        self.addCleanup(watchdog.cancel)
        return self.proc

    @staticmethod
    def close_pipes(proc):
        proc.kill()
        proc.wait(timeout=10)
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            if pipe:
                pipe.close()

    def send(self, line):
        self.proc.stdin.write(line)
        self.proc.stdin.flush()

    def until(self, kind, limit=500):
        """Lit des événements jusqu'à en trouver un de ce type ; renvoie tout ce qui a été lu."""
        seen = []
        for _ in range(limit):
            line = self.proc.stdout.readline()
            self.assertTrue(line, f"flux fermé avant {kind.__name__} : {seen[-3:]}")
            for ev in cp.parse_line(line):
                seen.append(ev)
                if isinstance(ev, kind):
                    return seen
        self.fail(f"{kind.__name__} introuvable")

    def test_argv_is_logged(self):
        proc = self.start("reprise-resume")
        proc.stdin.close()
        proc.wait(timeout=10)   # EOF sur stdin : le faux claude sort
        self.assertEqual(json.loads(Path(self.argv_log).read_text().splitlines()[0]), ["-p", "--model", "haiku"])

    def test_exit_code_and_not_logged_in(self):
        proc = self.start("reprise-resume", FAKE_CLAUDE_EXIT="1")
        _out, err = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Not logged in", err)

    def test_initialize_and_controls(self):
        self.start("init-effort-controles")
        self.send(cp.control("initialize", "req_1"))
        self.assertIsInstance(self.until(cp.Hello)[-1], cp.Hello)
        self.send(cp.control("set_model", "req_2", model="sonnet"))
        reply = self.until(cp.ControlReply)[-1]
        self.assertEqual((reply.request_id, reply.data), ("req_2", {"model": "claude-sonnet-5-5"}))
        self.send(cp.control("set_permission_mode", "req_3", mode="manual"))
        seen = self.until(cp.Status)
        self.assertEqual(seen[0].data, {"mode": "default"})
        self.assertEqual(seen[-1].permission_mode, "default")
        self.send(cp.control("set_effort", "req_4", effort="high"))
        reply = self.until(cp.ControlReply)[-1]
        self.assertFalse(reply.ok)
        self.assertIn("Unsupported control request subtype: set_effort", reply.error)
        self.send(cp.control("get_context_usage", "req_5"))
        reply = self.until(cp.ControlReply)[-1]
        self.assertIn("totalTokens", reply.data)

    def test_user_message_replays_next_turn_with_permission(self):
        self.start("permissions-allow-toujours")
        self.send(cp.user_message("Lance la commande"))
        seen = self.until(cp.PermissionRequest)
        self.assertTrue(of_type(seen, cp.TextDelta) or of_type(seen, cp.ToolUse))
        request = seen[-1]
        self.send(cp.allow(request.request_id, request.input))
        seen = self.until(cp.TurnResult)
        self.assertEqual(of_type(seen, cp.ToolResult)[0].is_error, False)
        self.assertEqual(seen[-1].text, "OK")
        # Le tour suivant du scénario (2e message) suit.
        self.send(cp.user_message("Encore"))
        self.assertIsInstance(self.until(cp.PermissionRequest)[-1], cp.PermissionRequest)

    def test_interrupt_ends_turn_then_exits_1(self):
        self.start("refus-et-interruption")
        self.send(cp.user_message("Un"))
        request = self.until(cp.PermissionRequest)[-1]
        self.send(cp.deny(request.request_id, "Non"))
        self.until(cp.TurnResult)
        self.send(cp.user_message("Deux"))
        self.until(cp.Init)
        self.send(cp.control("interrupt", "req_77"))
        seen = self.until(cp.TurnResult)
        reply = [e for e in seen if isinstance(e, cp.ControlReply)][0]
        self.assertEqual((reply.request_id, reply.data), ("req_77", {"still_queued": []}))
        self.assertTrue(seen[-1].interrupted)
        self.assertEqual(self.proc.wait(timeout=10), 1)

    def test_resume_rewrites_session_id(self):
        full = {**os.environ, "FAKE_CLAUDE_SCENARIO": str(FIXTURES / "reprise-resume.jsonl")}
        proc = subprocess.Popen([sys.executable, str(FAKE), "--resume", "abc-123"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, text=True, env=full)
        self.addCleanup(self.close_pipes, proc)
        guard = threading.Timer(15, proc.kill)
        guard.daemon = True
        guard.start()
        proc.stdin.write(cp.user_message("Bonjour"))
        proc.stdin.flush()
        ids = set()
        for _ in range(50):
            for ev in cp.parse_line(proc.stdout.readline()):
                if isinstance(ev, cp.Init):
                    ids.add(ev.session_id)
                if isinstance(ev, cp.LocalCommand):
                    self.assertEqual(ids, {"abc-123"})
                    return
        self.fail("pas de résultat")

    def test_big_line(self):
        self.start("reprise-resume", FAKE_CLAUDE_BIG_LINE=str(2 * 1024 * 1024))
        self.send(cp.user_message("Bonjour"))
        seen = self.until(cp.LocalCommand)   # ce scénario ne contient que des commandes /effort
        big = of_type(seen, cp.ToolResult)[0]
        self.assertEqual(len(big.text), 2 * 1024 * 1024)

    def test_past_end_of_scenario_gives_minimal_result(self):
        self.start("lancement-effort-ultracode")
        self.send(cp.user_message("/effort ultracode"))
        self.assertIsInstance(self.until(cp.LocalCommand)[-1], cp.LocalCommand)
        self.send(cp.user_message("x"))
        self.assertEqual(self.until(cp.TurnResult)[-1].text, "(fin du scénario)")


if __name__ == "__main__":
    unittest.main()
