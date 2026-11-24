"""Proxy Anthropic → OpenAI : traduction, flux SSE, cycle de vie, aller-retour en local.

Aucun appel réseau réel : le « service OpenAI » est un faux serveur sur 127.0.0.1."""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock

from ccs_app import openai_proxy as op, providers
from tests.helpers import HomeTestCase


def events_of(pairs):
    return [name for name, _ in pairs]


class RequestTest(unittest.TestCase):
    def test_messages_system_and_params(self):
        body = {"model": "m", "max_tokens": 100, "temperature": 0.2, "stop_sequences": ["X"],
                "system": [{"type": "text", "text": "Sois bref.", "cache_control": {}}],
                "thinking": {"type": "enabled"}, "metadata": {"user_id": "u"},
                "messages": [{"role": "user", "content": "Bonjour"},
                             {"role": "assistant", "content": [{"type": "thinking", "thinking": "…"},
                                                               {"type": "text", "text": "Salut"}]}]}
        out = op.to_openai(body, extra={"venice_parameters": {"x": False}})
        self.assertEqual(out["messages"], [
            {"role": "system", "content": "Sois bref."},
            {"role": "user", "content": "Bonjour"},
            {"role": "assistant", "content": "Salut"}])
        self.assertEqual((out["model"], out["max_tokens"], out["temperature"], out["stop"]),
                         ("m", 100, 0.2, ["X"]))
        self.assertNotIn("thinking", out)
        self.assertNotIn("metadata", out)
        self.assertNotIn("stream", out)
        self.assertEqual(out["venice_parameters"], {"x": False})

    def test_tools_tool_use_and_tool_result(self):
        body = {"model": "m", "stream": True,
                "tools": [{"name": "Bash", "description": "shell",
                           "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}}}],
                "tool_choice": {"type": "any"},
                "messages": [
                    {"role": "user", "content": "liste"},
                    {"role": "assistant", "content": [
                        {"type": "text", "text": "Je regarde."},
                        {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "ls"}}]},
                    {"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": "toolu_1",
                         "content": [{"type": "text", "text": "a.txt"}]},
                        {"type": "text", "text": "et ensuite ?"}]}]}
        out = op.to_openai(body)
        self.assertEqual(out["tools"], [{"type": "function", "function": {
            "name": "Bash", "description": "shell",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}}])
        self.assertEqual(out["tool_choice"], "required")
        self.assertTrue(out["stream"])
        self.assertEqual(out["stream_options"], {"include_usage": True})
        asst, tool, user = out["messages"][1:]
        self.assertEqual(asst["content"], "Je regarde.")
        self.assertEqual(asst["tool_calls"], [{"id": "toolu_1", "type": "function",
                                               "function": {"name": "Bash", "arguments": '{"command": "ls"}'}}])
        self.assertEqual(tool, {"role": "tool", "tool_call_id": "toolu_1", "content": "a.txt"})
        self.assertEqual(user, {"role": "user", "content": "et ensuite ?"})

    def test_tool_only_assistant_error_result_and_image(self):
        out = op.to_openai({"model": "m", "tool_choice": {"type": "tool", "name": "Read"},
                            "tools": [{"name": "Read", "input_schema": {}}],
                            "messages": [
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "Read", "input": {}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t", "content": "introuvable", "is_error": True},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}},
                {"type": "text", "text": "vois"}]}]})
        self.assertIsNone(out["messages"][0]["content"])
        self.assertEqual(out["messages"][1]["content"], "[erreur] introuvable")
        self.assertEqual(out["messages"][2]["content"], [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
            {"type": "text", "text": "vois"}])
        self.assertEqual(out["tool_choice"], {"type": "function", "function": {"name": "Read"}})


class ResponseTest(unittest.TestCase):
    def test_text_and_tool_calls(self):
        data = {"id": "abc", "model": "glm", "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                "choices": [{"finish_reason": "tool_calls", "message": {
                    "content": "Voilà", "tool_calls": [{"id": "call_1", "type": "function", "function": {
                        "name": "Bash", "arguments": '{"command": "pwd"}'}}]}}]}
        out = op.from_openai(data, "glm-x")
        self.assertEqual(out["model"], "glm-x")
        self.assertEqual(out["content"], [
            {"type": "text", "text": "Voilà"},
            {"type": "tool_use", "id": "call_1", "name": "Bash", "input": {"command": "pwd"}}])
        self.assertEqual(out["stop_reason"], "tool_use")
        self.assertEqual(out["usage"], {"input_tokens": 10, "output_tokens": 3})

    def test_stop_reasons_and_bad_arguments(self):
        out = op.from_openai({"choices": [{"finish_reason": "length", "message": {"content": "x"}}]})
        self.assertEqual(out["stop_reason"], "max_tokens")
        out = op.from_openai({"choices": [{"message": {"tool_calls": [
            {"function": {"name": "f", "arguments": "{pas du json"}}]}}]})
        self.assertEqual(out["content"][0]["input"], {})
        self.assertTrue(out["content"][0]["id"].startswith("toolu_"))


class StreamTest(unittest.TestCase):
    def test_text_then_tool_calls(self):
        tr = op.StreamTranslator("glm")
        ev = tr.feed({"id": "c1", "choices": [{"delta": {"role": "assistant", "content": "Bon"}}]})
        ev += tr.feed({"choices": [{"delta": {"content": "jour"}}]})
        ev += tr.feed({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_a", "function": {"name": "Bash", "arguments": '{"comm'}}]}}]})
        ev += tr.feed({"choices": [{"delta": {"tool_calls": [
            {"index": 1, "id": "call_b", "function": {"name": "Read", "arguments": '{"file_path":"/a"}'}}]}}]})
        ev += tr.feed({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": 'and":"ls"}'}}]}, "finish_reason": "tool_calls"}]})
        ev += tr.feed({"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 5}})
        ev += tr.close()
        self.assertEqual(events_of(ev), [
            "message_start", "content_block_start", "content_block_delta", "content_block_delta",
            "ping", "ping", "ping", "ping",
            "content_block_stop",
            "content_block_start", "content_block_delta", "content_block_stop",
            "content_block_start", "content_block_delta", "content_block_stop",
            "message_delta", "message_stop"])
        data = [d for _, d in ev]
        self.assertEqual(data[0]["message"]["model"], "glm")
        self.assertEqual(data[2]["delta"], {"type": "text_delta", "text": "Bon"})
        self.assertEqual(data[9]["index"], 1)
        self.assertEqual(data[9]["content_block"], {"type": "tool_use", "id": "call_a", "name": "Bash", "input": {}})
        self.assertEqual(json.loads(data[10]["delta"]["partial_json"]), {"command": "ls"})
        self.assertEqual(data[12]["content_block"]["name"], "Read")
        self.assertEqual(data[12]["index"], 2)
        self.assertEqual(data[15]["delta"]["stop_reason"], "tool_use")
        self.assertEqual(data[15]["usage"], {"input_tokens": 7, "output_tokens": 5})
        self.assertEqual(tr.close(), [])

    def test_empty_stream_and_end_turn(self):
        tr = op.StreamTranslator()
        ev = tr.close()
        self.assertEqual(events_of(ev), ["message_start", "message_delta", "message_stop"])
        self.assertEqual(ev[1][1]["delta"]["stop_reason"], "end_turn")

    def test_sse_parsing(self):
        lines = [b": commentaire\n", b"data: {\"a\": 1}\n", b"\n", b"data: pas du json\n",
                 "data: {\"b\": 2}\n", b"data: [DONE]\n", b"data: {\"c\": 3}\n"]
        self.assertEqual(list(op.sse_chunks(lines)), [{"a": 1}, {"b": 2}])
        raw = op.sse_event("ping", {"type": "ping"})
        self.assertEqual(raw, b'event: ping\ndata: {"type": "ping"}\n\n')


class LifecycleTest(unittest.TestCase):
    def test_ensure_running_reuses_or_spawns(self):
        spawn = mock.Mock()
        self.assertEqual(op.ensure_running(5000, probe_=lambda p: 42, spawn_=spawn), 42)
        spawn.assert_not_called()
        answers = iter([None, None, 77])
        pid = op.ensure_running(5000, probe_=lambda p: next(answers), spawn_=spawn, sleep=lambda s: None)
        self.assertEqual(pid, 77)
        spawn.assert_called_once_with(5000)

    def test_ensure_running_fails_clearly(self):
        with self.assertRaises(ValueError):
            op.ensure_running(5000, wait=0.05, probe_=lambda p: None, spawn_=mock.Mock(),
                              sleep=lambda s: None)

    def test_stop(self):
        kill = mock.Mock()
        self.assertEqual(op.stop(5000, probe_=lambda p: 9, kill=kill), 9)
        kill.assert_called_once()
        self.assertIsNone(op.stop(5000, probe_=lambda p: None, kill=kill))

    def test_users_counts_sessions_with_proxy_url(self):
        with tempfile.TemporaryDirectory() as proc:
            def make(pid, args):
                os.makedirs(os.path.join(proc, pid))
                with open(os.path.join(proc, pid, "cmdline"), "wb") as f:
                    f.write(b"\0".join(a.encode() for a in args))
            settings = json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:5000/venice"}})
            make("10", ["claude", "--settings", settings])
            make("11", ["python3", "-m", "ccs_app.openai_proxy", "serve", "--port", "5000"])
            make("12", ["claude", "--settings", settings.replace("5000", "5001")])
            make("13", ["moi", "127.0.0.1:5000/venice"])
            os.makedirs(os.path.join(proc, "self"))
            self.assertEqual(op.users(5000, proc, me=13), 1)
            self.assertIsNone(op.users(5000, os.path.join(proc, "absent")))

    def test_idle_watcher_stops_after_last_session(self):
        now = [0.0]
        counts = iter([0, 1, 0, 0, None, 0])
        w = op.IdleWatcher(lambda: next(counts), grace=90, clock=lambda: now[0])
        now[0] = 30
        self.assertFalse(w.should_stop())   # démarrage récent : on attend claude
        now[0] = 60
        self.assertFalse(w.should_stop())   # une session
        now[0] = 100
        self.assertFalse(w.should_stop())   # dernière session partie il y a 40 s
        now[0] = 151
        self.assertTrue(w.should_stop())
        now[0] = 300
        self.assertFalse(w.should_stop())   # /proc illisible : on reste
        now[0] = 400
        self.assertTrue(w.should_stop())


class FakeUpstream(BaseHTTPRequestHandler):
    """Faux service OpenAI : enregistre la requête et répond selon `stream`."""
    seen = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        FakeUpstream.seen.append((self.path, self.headers.get("authorization"), body))
        if body["model"] == "refus":
            raw = json.dumps({"error": {"message": "clé refusée"}}).encode()
            self.send_response(401)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if not body.get("stream"):
            raw = json.dumps({"id": "x", "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
                              "usage": {"prompt_tokens": 4, "completion_tokens": 1}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for chunk in ({"choices": [{"delta": {"content": "Je lance"}}]},
                      {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_z", "function": {
                          "name": "Bash", "arguments": '{"command":"ls"}'}}]}, "finish_reason": "tool_calls"}]}):
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


def start(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class RoundTripTest(unittest.TestCase):
    def setUp(self):
        FakeUpstream.seen.clear()
        self.upstream = start(FakeUpstream)
        base = f"http://127.0.0.1:{self.upstream.server_port}/api/v1"
        venice = SimpleNamespace(base_url=base, label="Venice", extra_body={"venice_parameters": {"k": 1}})
        handler = type("H", (op.Handler,), {"lookup": staticmethod(lambda n: venice if n == "venice" else None)})
        self.proxy = start(handler)
        self.url = f"http://127.0.0.1:{self.proxy.server_port}"

    def tearDown(self):
        for s in (self.proxy, self.upstream):
            s.shutdown()
            s.server_close()

    def post(self, path, body):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"x-api-key": "cle-de-test", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.read().decode()

    def test_streaming_with_tool(self):
        raw = self.post("/venice/v1/messages?beta=true", {
            "model": "glm-5-3-flash-uncensored", "max_tokens": 50, "stream": True,
            "tools": [{"name": "Bash", "input_schema": {"type": "object"}}],
            "messages": [{"role": "user", "content": "liste"}]})
        path, auth, body = FakeUpstream.seen[0]
        self.assertEqual(path, "/api/v1/chat/completions")
        self.assertEqual(auth, "Bearer cle-de-test")
        self.assertEqual(body["venice_parameters"], {"k": 1})
        self.assertEqual(body["tools"][0]["function"]["name"], "Bash")
        names = [line[7:] for line in raw.splitlines() if line.startswith("event: ")]
        self.assertEqual(names[0], "message_start")
        self.assertEqual(names[-2:], ["message_delta", "message_stop"])
        datas = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]
        tool = [d for d in datas if d.get("content_block", {}).get("type") == "tool_use"]
        self.assertEqual(tool[0]["content_block"]["id"], "call_z")
        self.assertEqual(datas[-2]["delta"]["stop_reason"], "tool_use")

    def test_non_stream_count_tokens_and_errors(self):
        out = json.loads(self.post("/venice/v1/messages", {"model": "m", "messages": [{"role": "user", "content": "x"}]}))
        self.assertEqual(out["content"], [{"type": "text", "text": "ok"}])
        self.assertEqual(out["usage"], {"input_tokens": 4, "output_tokens": 1})
        n = json.loads(self.post("/venice/v1/messages/count_tokens", {"messages": [{"role": "user", "content": "x" * 400}]}))
        self.assertGreater(n["input_tokens"], 90)
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.post("/venice/v1/messages", {"model": "refus", "messages": []})
        self.assertEqual(e.exception.code, 401)
        err = json.loads(e.exception.read())
        self.assertEqual(err["error"], {"type": "authentication_error", "message": "clé refusée"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.post("/inconnu/v1/messages", {"model": "m", "messages": []})
        self.assertEqual(e.exception.code, 404)
        with urllib.request.urlopen(self.url + op.HEALTH_PATH, timeout=5) as r:
            self.assertEqual(json.load(r)["pid"], os.getpid())


class VeniceProviderTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        os.environ.pop("XDG_CONFIG_HOME", None)
        os.environ.pop(op.PORT_ENV, None)

    def test_preset(self):
        p = providers.load()["venice"]
        self.assertEqual(p.api, "openai")
        self.assertEqual(p.base_url, "https://api.venice.ai/api/v1")
        self.assertEqual(p.key_path(), str(self.home / ".config" / "venice" / "cle"))
        self.assertEqual([m for _, m in p.models], ["glm-5-3-flash-uncensored",
                                                     "deepseek-v4-1-flash-1017-uncensored", "venice-uncensored"])
        self.assertEqual(p.claude_url(), "http://127.0.0.1:47447/venice")

    def test_claude_args_start_proxy_and_point_to_it(self):
        with self.assertRaises(ValueError):          # pas de clé : refus avant de lancer quoi que ce soit
            providers.claude_args("venice")
        providers.save_key("venice", "cle-factice")
        with mock.patch.object(op, "ensure_running") as ensure:
            args = providers.claude_args("venice", "venice-uncensored")
        ensure.assert_called_once_with()
        settings = json.loads(args[args.index("--settings") + 1])
        self.assertEqual(settings["env"]["ANTHROPIC_BASE_URL"], "http://127.0.0.1:47447/venice")
        self.assertIn("venice", settings["apiKeyHelper"])
        self.assertEqual(args[-2:], ["--model", "venice-uncensored"])
        self.assertEqual(providers.from_args(args), ("venice", "venice-uncensored"))
        with mock.patch.object(op, "ensure_running") as ensure:
            providers.claude_args("venice", check=False)
        ensure.assert_not_called()

    def test_bad_api_rejected(self):
        cfg = providers.config_path()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"x": {"base_url": "https://x", "api": "grpc"}}))
        with self.assertRaises(ValueError):
            providers.load()


if __name__ == "__main__":
    unittest.main()
