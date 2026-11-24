"""Proxy local : l'API Anthropic (`/v1/messages`) traduite vers l'API OpenAI (`/chat/completions`).

Claude Code ne parle que l'API Anthropic ; des services comme Venice ne parlent que l'API
OpenAI. Ce petit traducteur, sans dépendance, se place entre les deux :

  claude ──/v1/messages──> 127.0.0.1:PORT/<fournisseur> ──/chat/completions──> service OpenAI

- Lancé à la demande par CCS (`ensure_running`, appelé par `providers.claude_args`) ; un seul
  processus sert tous les fournisseurs `"api": "openai"`, choisis par le début du chemin.
- Ne lit jamais de clé : claude envoie la sienne (`apiKeyHelper` → `x-api-key`), le proxy la
  transmet au service en `Authorization: Bearer`. Il n'écoute que sur 127.0.0.1.
- S'arrête seul quand plus aucun processus n'a son adresse dans sa ligne de commande (les
  sessions claude la portent dans `--settings`) : avec la dernière session, pour la RAM.
"""

import argparse
import json
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
DEFAULT_PORT = 47447
PORT_ENV = "CCS_OPENAI_PROXY_PORT"
HEALTH_PATH = "/ccs-proxy"
CHECK_S = 15          # intervalle de recherche des sessions qui utilisent le proxy
GRACE_S = 90          # délai sans session avant l'arrêt (laisse à claude le temps de démarrer)
UPSTREAM_TIMEOUT_S = 600

STOP_REASONS = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use",
                "function_call": "tool_use", "content_filter": "end_turn"}
ERROR_TYPES = {400: "invalid_request_error", 401: "authentication_error", 402: "billing_error",
               403: "permission_error", 404: "not_found_error", 413: "request_too_large",
               429: "rate_limit_error", 529: "overloaded_error"}


def port():
    try:
        return int(os.environ.get(PORT_ENV) or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def url_for(name, port_=None):
    """Adresse à donner à claude (ANTHROPIC_BASE_URL) pour le fournisseur `name`."""
    return f"http://{HOST}:{port_ or port()}/{name}"


# --------------------------------------------------------------------------
# Traduction de la requête : Anthropic → OpenAI
# --------------------------------------------------------------------------

def _text_of(content):
    """Texte d'un contenu Anthropic (chaîne ou liste de blocs)."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content or ():
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(block.get("text") or "")
        elif block.get("type") == "image":
            parts.append("[image]")
        elif block.get("type") == "document":
            parts.append("[document]")
    return "\n".join(parts)


def _image_part(block):
    src = block.get("source") or {}
    if src.get("type") == "base64":
        url = f"data:{src.get('media_type') or 'image/png'};base64,{src.get('data') or ''}"
    else:
        url = src.get("url") or ""
    return {"type": "image_url", "image_url": {"url": url}}


def _user_messages(content):
    """Messages OpenAI d'un message utilisateur : résultats d'outils (rôle `tool`) d'abord,
    juste après l'appel de l'assistant, puis le reste (texte, images)."""
    if isinstance(content, str):
        return [{"role": "user", "content": content}]
    tools, parts = [], []
    for block in content or ():
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "tool_result":
            text = _text_of(block.get("content"))
            if block.get("is_error"):
                text = f"[erreur] {text}"
            tools.append({"role": "tool", "tool_call_id": block.get("tool_use_id") or "",
                          "content": text})
        elif kind == "text":
            parts.append({"type": "text", "text": block.get("text") or ""})
        elif kind == "image":
            parts.append(_image_part(block))
        elif kind == "document":
            parts.append({"type": "text", "text": "[document non transmis]"})
    out = list(tools)
    if parts:
        if all(p["type"] == "text" for p in parts):
            out.append({"role": "user", "content": "\n".join(p["text"] for p in parts)})
        else:
            out.append({"role": "user", "content": parts})
    return out


def _assistant_message(content):
    if isinstance(content, str):
        return {"role": "assistant", "content": content}
    texts, calls = [], []
    for block in content or ():
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            texts.append(block.get("text") or "")
        elif block.get("type") == "tool_use":
            calls.append({"id": block.get("id") or _tool_id(), "type": "function",
                          "function": {"name": block.get("name") or "",
                                       "arguments": json.dumps(block.get("input") or {},
                                                               ensure_ascii=False)}})
        # réflexion (thinking) : propre à Anthropic, pas renvoyée au service
    msg = {"role": "assistant", "content": "".join(texts) if texts or not calls else None}
    if calls:
        msg["tool_calls"] = calls
    return msg


def _tool_choice(choice):
    kind = (choice or {}).get("type")
    if kind == "any":
        return "required"
    if kind == "tool":
        return {"type": "function", "function": {"name": choice.get("name") or ""}}
    if kind in ("auto", "none"):
        return kind
    return None


def to_openai(body, model=None, extra=None):
    """Requête `/v1/messages` (dict) → requête `/chat/completions` (dict)."""
    messages = []
    system = body.get("system")
    if system:
        messages.append({"role": "system", "content": _text_of(system)})
    for msg in body.get("messages") or ():
        if msg.get("role") == "assistant":
            messages.append(_assistant_message(msg.get("content")))
        else:
            messages.extend(_user_messages(msg.get("content")))
    out = {"model": model or body.get("model"), "messages": messages}
    if body.get("max_tokens"):
        out["max_tokens"] = body["max_tokens"]
    for key in ("temperature", "top_p"):
        if body.get(key) is not None:
            out[key] = body[key]
    if body.get("stop_sequences"):
        out["stop"] = body["stop_sequences"]
    tools = [{"type": "function",
              "function": {"name": t.get("name") or "", "description": t.get("description") or "",
                           "parameters": t.get("input_schema") or {"type": "object", "properties": {}}}}
             for t in body.get("tools") or () if isinstance(t, dict) and t.get("name")]
    if tools:
        out["tools"] = tools
        choice = _tool_choice(body.get("tool_choice"))
        if choice:
            out["tool_choice"] = choice
    if body.get("stream"):
        out["stream"] = True
        out["stream_options"] = {"include_usage": True}
    if extra:
        out.update(extra)
    return out


# --------------------------------------------------------------------------
# Traduction de la réponse : OpenAI → Anthropic
# --------------------------------------------------------------------------

def _tool_id():
    return "toolu_" + uuid.uuid4().hex[:24]


def _msg_id(raw=None):
    return "msg_" + (str(raw) if raw else uuid.uuid4().hex[:24])


def _parse_args(text):
    try:
        value = json.loads(text or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _usage(usage):
    usage = usage or {}
    return {"input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0)}


def from_openai(data, model=None):
    """Réponse `/chat/completions` (dict, sans flux) → réponse `/v1/messages` (dict)."""
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = []
    if msg.get("content"):
        content.append({"type": "text", "text": msg["content"]})
    for call in msg.get("tool_calls") or ():
        fn = call.get("function") or {}
        content.append({"type": "tool_use", "id": call.get("id") or _tool_id(),
                        "name": fn.get("name") or "", "input": _parse_args(fn.get("arguments"))})
    stop = "tool_use" if msg.get("tool_calls") else STOP_REASONS.get(choice.get("finish_reason"), "end_turn")
    return {"id": _msg_id(data.get("id")), "type": "message", "role": "assistant",
            "model": model or data.get("model") or "", "content": content,
            "stop_reason": stop, "stop_sequence": None, "usage": _usage(data.get("usage"))}


class StreamTranslator:
    """Morceaux du flux OpenAI → événements du flux Anthropic (liste de (nom, données)).

    Le texte passe au fil de l'eau ; les appels d'outils sont rassemblés (leurs arguments
    arrivent par bouts, parfois entremêlés) et rendus complets à la fin, un bloc chacun."""

    def __init__(self, model=None):
        self.model = model
        self.started = False
        self.index = 0             # prochain numéro de bloc Anthropic
        self.text_open = False
        self.tools = {}            # index OpenAI -> {"id", "name", "args"}
        self.finish = None
        self.usage = {}
        self.done = False

    def _start(self, chunk):
        self.started = True
        return [("message_start", {"type": "message_start", "message": {
            "id": _msg_id(chunk.get("id")), "type": "message", "role": "assistant",
            "model": self.model or chunk.get("model") or "", "content": [],
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0}}})]

    def _close_text(self):
        if not self.text_open:
            return []
        self.text_open = False
        self.index += 1
        return [("content_block_stop", {"type": "content_block_stop", "index": self.index - 1})]

    def feed(self, chunk):
        events = [] if self.started else self._start(chunk)
        if chunk.get("usage"):
            self.usage = chunk["usage"]
        emitted = False
        for choice in chunk.get("choices") or ():
            delta = choice.get("delta") or {}
            text = delta.get("content")
            if text:
                if not self.text_open:
                    self.text_open = True
                    events.append(("content_block_start", {
                        "type": "content_block_start", "index": self.index,
                        "content_block": {"type": "text", "text": ""}}))
                events.append(("content_block_delta", {
                    "type": "content_block_delta", "index": self.index,
                    "delta": {"type": "text_delta", "text": text}}))
                emitted = True
            for call in delta.get("tool_calls") or ():
                slot = self.tools.setdefault(call.get("index", len(self.tools)),
                                             {"id": None, "name": "", "args": ""})
                fn = call.get("function") or {}
                slot["id"] = slot["id"] or call.get("id")
                if fn.get("name") and not slot["name"]:
                    slot["name"] = fn["name"]
                slot["args"] += fn.get("arguments") or ""
            if choice.get("finish_reason"):
                self.finish = choice["finish_reason"]
        if not emitted and not events:
            # réflexion du modèle ou bouts d'outils : garder la connexion vivante
            events.append(("ping", {"type": "ping"}))
        return events

    def close(self):
        """Événements de fin (blocs d'outils, raison d'arrêt, consommation)."""
        if self.done:
            return []
        self.done = True
        events = [] if self.started else self._start({})
        events += self._close_text()
        for key in sorted(self.tools):
            slot = self.tools[key]
            i = self.index
            events.append(("content_block_start", {
                "type": "content_block_start", "index": i,
                "content_block": {"type": "tool_use", "id": slot["id"] or _tool_id(),
                                  "name": slot["name"], "input": {}}}))
            events.append(("content_block_delta", {
                "type": "content_block_delta", "index": i,
                "delta": {"type": "input_json_delta",
                          "partial_json": json.dumps(_parse_args(slot["args"]), ensure_ascii=False)}}))
            events.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
            self.index += 1
        stop = "tool_use" if self.tools else STOP_REASONS.get(self.finish, "end_turn")
        events.append(("message_delta", {"type": "message_delta",
                                         "delta": {"stop_reason": stop, "stop_sequence": None},
                                         "usage": _usage(self.usage)}))
        events.append(("message_stop", {"type": "message_stop"}))
        return events


def sse_chunks(lines):
    """Objets JSON d'un flux SSE OpenAI (lignes en octets ou texte) ; s'arrête à `[DONE]`."""
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            yield json.loads(data)
        except ValueError:
            continue


def sse_event(name, data):
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


def error_body(status, message):
    return {"type": "error", "error": {"type": ERROR_TYPES.get(status, "api_error"),
                                       "message": str(message)[:2000]}}


def estimate_tokens(body):
    """Estimation grossière (4 caractères par jeton) pour `/v1/messages/count_tokens`."""
    return max(1, len(json.dumps(body, ensure_ascii=False)) // 4)


# --------------------------------------------------------------------------
# Serveur
# --------------------------------------------------------------------------

def _provider(name):
    from . import providers
    try:
        p = providers.load().get(name)
    except ValueError:
        return None
    return p if p is not None and p.api == "openai" else None


def _key_of(headers):
    key = headers.get("x-api-key") or ""
    auth = headers.get("authorization") or ""
    if not key and auth.lower().startswith("bearer "):
        key = auth[7:]
    return key.strip()


class Handler(BaseHTTPRequestHandler):
    server_version = "ccs-openai-proxy"
    lookup = staticmethod(_provider)    # nom -> Provider (remplaçable dans les tests)

    def log_message(self, fmt, *args):   # pas de journal par requête (ni clé ni contenu)
        pass

    def _json(self, status, data):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.split("?")[0] == HEALTH_PATH:
            return self._json(200, {"ccs_proxy": "openai", "pid": os.getpid()})
        return self._json(404, error_body(404, "chemin inconnu"))

    def do_POST(self):
        path = self.path.split("?")[0].strip("/").split("/")
        # /<fournisseur>/v1/messages[/count_tokens]
        if len(path) < 3 or path[1:3] != ["v1", "messages"]:
            return self._json(404, error_body(404, "chemin inconnu"))
        provider = self.lookup(path[0])
        if provider is None:
            return self._json(404, error_body(404, f"fournisseur OpenAI inconnu : {path[0]}"))
        try:
            length = int(self.headers.get("content-length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json(400, error_body(400, "JSON invalide"))
        if path[3:] == ["count_tokens"]:
            return self._json(200, {"input_tokens": estimate_tokens(body)})
        model = body.get("model")
        request = to_openai(body, model, provider.extra_body)
        req = urllib.request.Request(
            provider.base_url + "/chat/completions", data=json.dumps(request).encode("utf-8"),
            method="POST", headers={"Content-Type": "application/json", "User-Agent": "ccs",
                                    "Authorization": f"Bearer {_key_of(self.headers)}"})
        try:
            resp = urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT_S)
        except urllib.error.HTTPError as e:
            return self._json(e.code, error_body(e.code, _upstream_message(e)))
        except OSError as e:
            return self._json(502, error_body(502, f"{provider.label} injoignable : {e}"))
        with resp:
            if not body.get("stream"):
                try:
                    data = json.load(resp)
                except ValueError:
                    return self._json(502, error_body(502, "réponse illisible du service"))
                return self._json(200, from_openai(data, model))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            tr = StreamTranslator(model)
            try:
                for chunk in sse_chunks(resp):
                    for name, data in tr.feed(chunk):
                        self.wfile.write(sse_event(name, data))
                    self.wfile.flush()
                for name, data in tr.close():
                    self.wfile.write(sse_event(name, data))
                self.wfile.flush()
            except OSError:
                pass   # claude a coupé (Échap) ou le service s'est interrompu
        self.close_connection = True


def _upstream_message(err):
    try:
        raw = err.read().decode("utf-8", "replace")
    except OSError:
        raw = ""
    try:
        data = json.loads(raw)
        msg = data.get("error") or data.get("message") or raw
        if isinstance(msg, dict):
            msg = msg.get("message") or json.dumps(msg)
        return msg
    except ValueError:
        return raw or str(err)


# --------------------------------------------------------------------------
# Cycle de vie
# --------------------------------------------------------------------------

def users(port_, proc="/proc", me=None):
    """Nombre de processus (hors celui-ci) dont la ligne de commande contient l'adresse du
    proxy, c'est-à-dire les sessions claude lancées sur un fournisseur OpenAI. None si /proc
    est illisible (on ne sait pas : le proxy reste)."""
    marker = f"{HOST}:{port_}/".encode()
    me = os.getpid() if me is None else me
    try:
        entries = os.listdir(proc)
    except OSError:
        return None
    count = 0
    for entry in entries:
        if not entry.isdigit() or int(entry) == me:
            continue
        try:
            with open(os.path.join(proc, entry, "cmdline"), "rb") as f:
                if marker in f.read():
                    count += 1
        except OSError:
            continue
    return count


class IdleWatcher:
    """Décide l'arrêt : plus aucune session depuis `grace` secondes."""

    def __init__(self, count, grace=GRACE_S, clock=time.monotonic):
        self.count = count
        self.grace = grace
        self.clock = clock
        self.last_seen = clock()     # le démarrage compte comme une utilisation

    def should_stop(self):
        n = self.count()
        now = self.clock()
        if n is None or n > 0:
            self.last_seen = now
            return False
        return now - self.last_seen >= self.grace


def serve(port_=None, grace=GRACE_S, check=CHECK_S):
    port_ = port_ or port()
    server = ThreadingHTTPServer((HOST, port_), Handler)
    server.daemon_threads = True
    watcher = IdleWatcher(lambda: users(port_), grace)

    def watch():
        while True:
            time.sleep(check)
            if watcher.should_stop():
                server.shutdown()
                return

    threading.Thread(target=watch, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


def probe(port_=None, timeout=1.0):
    """PID du proxy qui répond sur ce port, ou None."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port_ or port()}{HEALTH_PATH}",
                                    timeout=timeout) as r:
            data = json.load(r)
    except (OSError, ValueError):
        return None
    return data.get("pid") if data.get("ccs_proxy") == "openai" else None


def log_path():
    from . import core
    return core.ccs_dir("cache") / "openai-proxy.log"


def spawn(port_):
    """Lance le proxy en arrière-plan, détaché (survit à l'appli qui l'a lancé)."""
    import subprocess
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(
        p for p in (pkg_root, os.environ.get("PYTHONPATH")) if p)}
    log = log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as out:
        return subprocess.Popen([sys.executable, "-m", "ccs_app.openai_proxy", "serve",
                                 "--port", str(port_)],
                                stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                                start_new_session=True, env=env, cwd=pkg_root)


def ensure_running(port_=None, wait=5.0, probe_=probe, spawn_=spawn, sleep=time.sleep):
    """Démarre le proxy s'il ne répond pas ; renvoie son PID. ValueError s'il ne démarre pas
    (port pris par autre chose, Python introuvable…)."""
    port_ = port_ or port()
    pid = probe_(port_)
    if pid:
        return pid
    spawn_(port_)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        sleep(0.1)
        pid = probe_(port_)
        if pid:
            return pid
    raise ValueError(f"le proxy OpenAI ne démarre pas sur {HOST}:{port_} (journal : {log_path()})")


def stop(port_=None, probe_=probe, kill=os.kill):
    """Arrête le proxy s'il tourne ; renvoie son PID ou None."""
    pid = probe_(port_ or port())
    if pid:
        kill(pid, signal.SIGTERM)
    return pid


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ccs_app.openai_proxy")
    parser.add_argument("action", choices=["serve", "status", "stop"], nargs="?", default="status")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    if args.action == "serve":
        return serve(args.port)
    if args.action == "stop":
        pid = stop(args.port)
        print(f"proxy arrêté (PID {pid})" if pid else "proxy à l'arrêt")
        return 0
    pid = probe(args.port)
    print(f"proxy actif (PID {pid}) sur {HOST}:{args.port or port()}" if pid else "proxy à l'arrêt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
