#!/usr/bin/env python3
"""Faux `claude` pour les tests du chat : rejoue un scénario de `tests/fixtures/chat/`.

Il remplace `claude -p --input-format stream-json --output-format stream-json …`.

Variables d'environnement :
  FAKE_CLAUDE_SCENARIO   chemin d'un .jsonl (lignes {"t", "dir": "meta"|"envoye"|"recu", "data"}) ;
  FAKE_CLAUDE_ARGV_LOG   fichier où noter les arguments reçus (une liste JSON par lancement) ;
  FAKE_CLAUDE_EXIT       code de sortie : sort tout de suite, « Not logged in » sur stderr ;
  FAKE_CLAUDE_BIG_LINE   nombre de caractères : avant le `result` de chaque tour, émet un
                         `tool_result` d'une seule ligne de cette taille ;
  FAKE_CLAUDE_DELAY_MS   pause entre deux lignes rejouées (0 par défaut).
  FAKE_CLAUDE_MERGE      1 : un message reçu pendant un tour est absorbé par ce tour, sans
                         result à part (l'autre comportement possible de la CLI).
  FAKE_CLAUDE_ASK_UNKNOWN 1 : au premier tour, pose une control_request d'un sous-type inconnu
                         (question_mystere) et attend sa réponse avant de continuer.
  FAKE_CLAUDE_REFUSE_MODE mode refusé par set_permission_mode (comme la CLI qui refuse
                         bypassPermissions sans --allow-dangerously-skip-permissions).

Comportement :
  - `initialize`, `get_context_usage` : réponse tirée du scénario (sinon réponse minimale) ;
  - `set_model`, `set_permission_mode` : réponse comme dans le flux réel (`manual` → `default`,
    plus un `system/status` pour les droits) ; sous-type inconnu : erreur
    « Unsupported control request subtype: <x> » ;
  - `interrupt` : `{"still_queued": []}` ; si un tour est en cours, il se termine par le
    `result` `aborted_streaming` du scénario, puis le processus sort avec le code 1 ;
  - chaque message utilisateur rejoue le tour suivant du scénario (jusqu'à son `result`) ;
    à une demande d'autorisation (`can_use_tool`), il attend la `control_response` avant de
    continuer ; fin du scénario : un tour minimal « (fin du scénario) » ;
  - `--resume <id>` : l'identifiant de session du scénario est remplacé par `<id>` ;
  - stdin fermé : sortie 0.
"""

import json
import os
import select
import sys
import time

MODELS = {"sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5", "haiku": "claude-haiku-5-5",
          "fable": "claude-fable-5-2", "default": "claude-opus-5-5"}


def out(obj):
    try:
        sys.stdout.write(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False))
        sys.stdout.write("\n")
        sys.stdout.flush()
    except (BrokenPipeError, ValueError):   # le lecteur est parti : on ne reste pas pour rien
        os._exit(0)


def load(path):
    entries = []
    if path:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
    return entries


def argv_value(argv, name):
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


class Fake:
    def __init__(self, entries, argv):
        self.entries = entries
        self.delay = float(os.environ.get("FAKE_CLAUDE_DELAY_MS") or 0) / 1000
        self.big = int(os.environ.get("FAKE_CLAUDE_BIG_LINE") or 0)
        self.mode = argv_value(argv, "--permission-mode") or "default"
        self.model = argv_value(argv, "--model") or "default"
        self.resume = argv_value(argv, "--resume")
        self.session = self.scenario_session()
        self.turn = 0
        self.contexts = 0
        self.last_request_id = None
        self.queue = []          # lignes lues pendant un tour et pas encore traitées
        self.merge = os.environ.get("FAKE_CLAUDE_MERGE") == "1"
        self._buf = b""          # octets lus sur stdin et pas encore découpés en lignes
        self.turns = self.split_turns()

    def scenario_session(self):
        for e in self.entries:
            data = e.get("data")
            if e.get("dir") == "recu" and isinstance(data, dict) and isinstance(data.get("session_id"), str):
                return data["session_id"]
        return "00000000-0000-4000-8000-000000000000"

    def split_turns(self):
        """Pour chaque message utilisateur « envoye » : les entrées jusqu'à son `result`."""
        turns, current = [], None
        for e in self.entries:
            data = e.get("data")
            if e["dir"] == "envoye" and isinstance(data, dict) and data.get("type") == "user":
                current = []
                turns.append(current)
            elif current is not None and e["dir"] in ("recu", "envoye"):
                current.append(e)
                if e["dir"] == "recu" and isinstance(data, dict) and data.get("type") == "result":
                    current = None
        return turns

    def first_response(self, key):
        found = []
        for e in self.entries:
            data = e.get("data")
            if e["dir"] == "recu" and isinstance(data, dict) and data.get("type") == "control_response":
                body = (data.get("response") or {}).get("response")
                if isinstance(body, dict) and key in body:
                    found.append(body)
        return found

    def session_id(self):
        return self.resume or self.session

    def emit(self, data):
        text = json.dumps(data, ensure_ascii=False)
        if self.resume and self.session in text:
            text = text.replace(self.session, self.resume)
        out(text)
        if self.delay:
            time.sleep(self.delay)

    # -- lecture de stdin
    def _readline(self, timeout=None):
        """Une ligne de stdin, sans tampon caché (pour pouvoir regarder s'il reste des lignes) ;
        "" si rien n'est prêt avant `timeout`, None à la fin de stdin."""
        while b"\n" not in self._buf:
            if timeout is not None and not select.select([0], [], [], timeout)[0]:
                return ""
            chunk = os.read(0, 65536)
            if not chunk:
                rest, self._buf = self._buf, b""
                return rest.decode("utf-8", "replace") if rest else None
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        return line.decode("utf-8", "replace") + "\n"

    def read(self):
        if self.queue:
            return self.queue.pop(0)
        return self.read_stdin()

    def read_stdin(self):
        """La ligne suivante de stdin, sans passer par la file des messages mis de côté."""
        line = self._readline()
        if not line:
            return None
        try:
            return json.loads(line)
        except ValueError:
            return {}

    def absorb(self):
        """Mode FAKE_CLAUDE_MERGE : les messages reçus pendant le tour y sont absorbés."""
        self.queue = [m for m in self.queue if m.get("type") != "user"]
        while True:
            line = self._readline(timeout=0)
            if not line:
                return
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("type") == "control_request":
                self.handle_control(msg)

    def reply(self, request_id, body):
        self.emit({"type": "control_response", "response": {
            "subtype": "success", "request_id": request_id, "response": body}})

    def error(self, request_id, message):
        self.emit({"type": "control_response", "response": {
            "subtype": "error", "request_id": request_id, "error": message}})

    def status(self):
        self.emit({"type": "system", "subtype": "status", "status": None, "permissionMode": self.mode,
                   "session_id": self.session_id()})

    # -- requêtes de contrôle
    def handle_control(self, msg):
        request_id = msg.get("request_id")
        self.last_request_id = request_id
        request = msg.get("request") or {}
        sub = request.get("subtype")
        if sub == "initialize":
            found = self.first_response("commands")
            self.reply(request_id, found[0] if found else {
                "commands": [], "models": [], "current_permission_mode": self.mode,
                "capabilities": [], "session_state": "idle"})
        elif sub == "get_context_usage":
            found = self.first_response("totalTokens")
            body = found[min(self.contexts, len(found) - 1)] if found else {
                "totalTokens": 0, "maxTokens": 1000000, "percentage": 0, "categories": []}
            self.contexts += 1
            self.reply(request_id, body)
        elif sub == "set_model":
            name = request.get("model") or "default"
            self.model = name
            self.reply(request_id, {"model": MODELS.get(name, name)})
        elif sub == "set_permission_mode":
            mode = request.get("mode") or "default"
            allow_bypass = any(a in sys.argv for a in ("--allow-dangerously-skip-permissions",
                                                       "--dangerously-skip-permissions"))
            refused = os.environ.get("FAKE_CLAUDE_REFUSE_MODE", "")
            if mode == refused or (mode == "bypassPermissions" and not allow_bypass):
                # comme la CLI : bypassPermissions seulement si autorisé au lancement
                self.error(request_id, f"Cannot set permission mode to {mode}")
                return
            self.mode = "default" if mode == "manual" else mode
            self.reply(request_id, {"mode": self.mode})
            self.status()
        elif sub == "interrupt":
            self.reply(request_id, {"still_queued": []})
        else:
            self.error(request_id, f"Unsupported control request subtype: {sub}")

    # -- un tour
    def play_turn(self):
        if self.turn >= len(self.turns):
            self.turn += 1
            self.emit({"type": "result", "subtype": "success", "is_error": False, "result": "(fin du scénario)",
                       "session_id": self.session_id(), "total_cost_usd": 0, "num_turns": 1,
                       "terminal_reason": "completed", "modelUsage": {}, "model_usage_since_last_result": {},
                       "permission_denials": []})
            return True
        entries = self.turns[self.turn]
        self.turn += 1
        if os.environ.get("FAKE_CLAUDE_ASK_UNKNOWN") == "1" and self.turn == 1:
            self.emit({"type": "control_request", "request_id": "q-mystere", "request": {
                "subtype": "question_mystere", "question": "Activer les mods de cette session ?"}})
            while True:   # la vraie CLI attend la réponse du client
                msg = self.read_stdin()
                if msg is None:
                    return False
                if msg.get("type") == "control_response" and \
                        (msg.get("response") or {}).get("request_id") == "q-mystere":
                    break
                if msg.get("type") == "control_request":
                    self.handle_control(msg)
                elif msg.get("type") == "user":
                    self.queue.append(msg)
        for e in entries:
            data = e["data"]
            if e["dir"] == "envoye":
                # Une réponse attendue du client : autorisation ou interruption.
                msg = self.wait_for_client(data)
                if msg is None:
                    return False
                continue
            if isinstance(data, dict) and data.get("type") == "control_response" and self.last_request_id:
                data = {**data, "response": {**data["response"], "request_id": self.last_request_id}}
            if self.big and isinstance(data, dict) and data.get("type") == "result":
                self.emit({"type": "user", "message": {"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": "toolu_GROS", "is_error": False,
                    "content": "x" * self.big}]}, "parent_tool_use_id": None,
                    "session_id": self.session_id()})
            if self.merge and isinstance(data, dict) and data.get("type") == "result":
                self.absorb()
            self.emit(data)
            if isinstance(data, dict) and data.get("type") == "result" and data.get("terminal_reason") == "aborted_streaming":
                sys.exit(1)
        return True

    def wait_for_client(self, expected):
        """Attend la `control_response` (ou la requête `interrupt`) que le scénario a notée."""
        want_response = expected.get("type") == "control_response"
        while True:
            msg = self.read_stdin()   # pas self.read() : il rendrait sans fin le message mis de côté
            if msg is None:
                return None
            if msg.get("type") == "control_response" and want_response:
                return msg
            if msg.get("type") == "control_request":
                sub = (msg.get("request") or {}).get("subtype")
                if sub == "interrupt" and not want_response:
                    self.last_request_id = msg.get("request_id")
                    return msg      # la réponse et l'abandon viennent du scénario
                self.handle_control(msg)
                continue
            if msg.get("type") == "user":
                self.queue.append(msg)   # pas établi par l'essai : gardé pour le tour suivant

    def run(self):
        while True:
            msg = self.read()
            if msg is None:
                return 0
            kind = msg.get("type")
            if kind == "control_request":
                self.handle_control(msg)
            elif kind == "user":
                if not self.play_turn():
                    return 0


def main():
    argv = sys.argv[1:]
    log = os.environ.get("FAKE_CLAUDE_ARGV_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(argv) + "\n")
    code = os.environ.get("FAKE_CLAUDE_EXIT")
    if code not in (None, ""):
        sys.stderr.write("Not logged in\n")
        sys.stderr.flush()
        return int(code)
    entries = load(os.environ.get("FAKE_CLAUDE_SCENARIO"))
    return Fake(entries, argv).run()


if __name__ == "__main__":
    sys.exit(main())
