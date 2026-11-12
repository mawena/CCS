"""Moteur du chat : pilote un processus `claude -p` en stream-json (sans GTK).

Un processus vit par chat, entre les messages. `on_event(ev)` est appelé depuis un fil
de lecture (ou, pour `StateChanged`, depuis le fil qui change l'état) : l'interface
l'enveloppe dans `GLib.idle_add`. Le moteur n'a pas de file de messages : celle de
l'onglet (`TabState.queue`) attend que l'état redevienne `idle`.
"""

import collections
import logging
import subprocess
import threading
import time
from dataclasses import dataclass

from . import chat_options, chat_protocol as proto, sessions, task_runner
from .chat_options import ChatOptions

log = logging.getLogger(__name__)

STATES = ("stopped", "starting", "idle", "busy", "permission", "suspended")
STDERR_LINES = 20


# --------------------------------------------------------------------------
# Événements propres au moteur
# --------------------------------------------------------------------------

# Après un `result`, si des messages envoyés pendant le tour restent « non soldés » et que la
# CLI ne montre plus aucune activité pendant ce délai, on les tient pour absorbés par le tour
# (la CLI peut lire un message reçu en plein tour sans lui donner de `result` à part).
SETTLE_S = 3.0


@dataclass(frozen=True)
class StateChanged:
    state: str


@dataclass(frozen=True)
class ContextUsage:
    percentage: int
    total: int
    maximum: int


@dataclass(frozen=True)
class OptionRefused:
    """La CLI a refusé un changement en direct (`set_model`, `set_permission_mode`) : il sera
    appliqué en relançant le processus (`--resume`) avant le prochain message."""
    what: str
    error: str


@dataclass(frozen=True)
class UnhandledRequest:
    """La CLI a posé une question que CCS ne sait pas traiter (sous-type de `control_request`
    inconnu, ex. activation des mods) : elle a reçu « non pris en charge » pour ne pas attendre."""
    subtype: str
    summary: str


@dataclass(frozen=True)
class ProcessExited:
    code: int | None
    stderr_tail: str  # les 20 dernières lignes de stderr
    requested: bool = False  # arrêt voulu (interrupt, stop, mise en veille) : pas une erreur


class ChatSession:
    def __init__(self, cwd, session_id=None, options=None, on_event=None, claude=None,
                 environ=None, clock=time.time):
        self.cwd = str(cwd)
        self.session_id = session_id
        self.options = options or ChatOptions()
        self.on_event = on_event
        self._claude = claude
        self._environ = environ
        self._clock = clock
        self.state = "stopped"
        self.pid = None
        self.started_at = None
        self.last_activity = clock()
        self.effort = self.options.effort  # la CLI ne l'annonce jamais : retenu ici
        self._proc = None
        self._lock = threading.RLock()      # état, processus, compteurs
        self._wlock = threading.Lock()      # écriture sur stdin
        self._req_n = 0
        self._ctrl = {}                     # request_id -> sous-type attendu
        self._perms = {}                    # request_id -> PermissionRequest en attente
        self._open_tools = set()            # outils lancés sans résultat (outils de fond)
        self._expected = 0                  # `result` attendus (un par ligne utilisateur)
        self._silent = 0                    # commandes locales du moteur dont la réponse est cachée
        self._pending_cmds = []             # `/effort …` à envoyer avant le prochain message
        self._relaunch_needed = False       # changement refusé en direct : relance au prochain message
        self._activity_at = 0.0             # dernier signe de vie de la CLI (hors result)
        self._background = False            # un sous-agent ou une tâche tourne en arrière-plan
        self._requested_stop = False

    # ------------------------------------------------------------------ état

    def _emit(self, ev):
        if self.on_event:
            try:
                self.on_event(ev)
            except Exception:
                log.exception("on_event a levé")

    def _set_state(self, state, proc=None):
        with self._lock:
            if proc is not None and proc is not self._proc:
                return
            if state == self.state:
                return
            self.state = state
        self._emit(StateChanged(state))

    def _next_id(self):
        with self._lock:
            self._req_n += 1
            return f"ccs_{self._req_n}"

    # ------------------------------------------------------------- lancement

    def _argv(self):
        argv = [self._claude or sessions._claude_bin(), "-p",
                "--input-format", "stream-json", "--output-format", "stream-json",
                "--verbose", "--include-partial-messages",
                "--permission-prompt-tool", "stdio",
                # permet de passer en « Tout autoriser » plus tard, sans l'activer
                "--allow-dangerously-skip-permissions",
                *chat_options.launch_args(self.options)]
        if self.session_id:
            argv += ["--resume", self.session_id]
        return argv

    def _env(self):
        from .terminal import SESSION_VARS
        env = dict(self._environ) if self._environ is not None else task_runner.environment()
        for v in SESSION_VARS:
            env.pop(v, None)
        return env

    def _spawn(self):
        """Lance le processus (verrou pris). Faux, avec ProcessExited, si impossible."""
        self._set_state("starting")
        try:
            proc = subprocess.Popen(self._argv(), cwd=self.cwd, env=self._env(),
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, bufsize=0)
        except OSError as e:
            self._set_state("stopped")
            self._emit(ProcessExited(127, f"Impossible de lancer claude : {e}"))
            return False
        self._proc = proc
        self.pid = proc.pid
        self.started_at = self._clock()
        self._requested_stop = False
        self._ctrl.clear()
        self._perms.clear()
        self._open_tools.clear()
        self._expected = 0
        self._silent = 0
        self._pending_cmds.clear()  # l'effort part avec les options de lancement
        self._background = False
        self.effort = self.options.effort
        tail = collections.deque(maxlen=STDERR_LINES)
        err = threading.Thread(target=self._read_stderr, args=(proc, tail), daemon=True)
        out = threading.Thread(target=self._read_stdout, args=(proc, tail, err), daemon=True)
        err.start()
        out.start()
        return True

    # --------------------------------------------------------------- lecture

    @staticmethod
    def _read_stderr(proc, tail):
        try:
            for raw in iter(proc.stderr.readline, b""):
                tail.append(raw.decode("utf-8", "replace").rstrip("\n"))
        except (OSError, ValueError):
            pass

    def _read_stdout(self, proc, tail, err_thread):
        try:
            buf = b""  # pas de limite de longueur de ligne (un tool_result peut peser 2 Mo)
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                buf += chunk
                start = 0
                while True:
                    i = buf.find(b"\n", start)
                    if i < 0:
                        break
                    self._handle_line(proc, buf[start:i].decode("utf-8", "replace"))
                    start = i + 1
                buf = buf[start:]
            if buf.strip():
                self._handle_line(proc, buf.decode("utf-8", "replace"))
        except (OSError, ValueError):
            pass
        code = proc.wait()
        err_thread.join(2)
        with self._lock:
            current = proc is self._proc
            requested = self._requested_stop if current else True
            if current:
                self._proc = None
                self.pid = None
        self._emit(ProcessExited(code, "\n".join(tail), requested))
        if current and self.state != "suspended":
            self._set_state("stopped")

    def _handle_line(self, proc, line):
        if proc is not self._proc:
            return
        self.last_activity = self._clock()
        for ev in proto.parse_line(line):
            self._handle_event(proc, ev)

    def _handle_event(self, proc, ev):
        forward = True
        if not isinstance(ev, (proto.TurnResult, proto.LocalCommand, proto.ControlReply, proto.Status)):
            self._activity_at = self._clock()   # la CLI travaille (nouveau tour, texte, outil…)
        if isinstance(ev, proto.Unknown) and isinstance(ev.raw, dict) and ev.raw.get("type") == "control_request":
            request = ev.raw.get("request") if isinstance(ev.raw.get("request"), dict) else {}
            sub = str(request.get("subtype") or "?")
            self._write(proto.control_error(str(ev.raw.get("request_id") or ""),
                                            f"Non pris en charge par CCS : {sub}"))
            summary = "; ".join(f"{k} : {v}" for k, v in request.items()
                                if k != "subtype" and isinstance(v, (str, int, float, bool)))[:300]
            self._emit(UnhandledRequest(sub, summary))
            return
        if isinstance(ev, proto.ToolUse) and ev.name in ("Task", "Agent") \
                and (ev.input or {}).get("run_in_background"):
            self._background = True   # sous-agent en arrière-plan : jamais de mise en veille
        if isinstance(ev, proto.Init):
            if ev.session_id:
                self.session_id = ev.session_id
        elif isinstance(ev, proto.ToolUse):
            self._open_tools.add(ev.tool_id)
        elif isinstance(ev, proto.ToolResult):
            self._open_tools.discard(ev.tool_id)
        elif isinstance(ev, proto.PermissionRequest):
            with self._lock:
                self._perms[ev.request_id] = ev
            self._set_state("permission", proc)
        elif isinstance(ev, proto.LocalCommand):
            with self._lock:
                if self._silent > 0:
                    self._silent -= 1
                    forward = False
        elif isinstance(ev, proto.ControlReply):
            sub = self._ctrl.pop(ev.request_id, None)
            if sub in ("set_model", "set_permission_mode") and not ev.ok:
                self._relaunch_needed = True   # appliqué par relance au prochain message
                self._emit(OptionRefused(sub, ev.error or ""))
                forward = False
            if sub == "get_context_usage" and ev.ok:
                d = ev.data or {}
                self._emit(ContextUsage(int(d.get("percentage", 0)), int(d.get("totalTokens", 0)),
                                        int(d.get("maxTokens", 0))))
                forward = False
        if forward:
            self._emit(ev)
        if isinstance(ev, (proto.TurnResult, proto.LocalCommand)):
            self._finish_one(proc, ev)

    def _finish_one(self, proc, ev):
        """Un `result` (tour ou commande locale) est arrivé : idle quand tous le sont. S'il reste
        des messages envoyés pendant le tour, un filet les solde si la CLI ne fait plus rien."""
        with self._lock:
            if self._expected > 0:
                self._expected -= 1
            done = self._expected == 0
            if done:
                self._perms.clear()
            at = self._clock()
        if done:
            self._set_state("idle", proc)
        else:
            timer = threading.Timer(SETTLE_S, self._settle, args=(proc, at))
            timer.daemon = True
            timer.start()

    def _settle(self, proc, result_at):
        """Filet : aucun signe de vie depuis le `result` → les messages restants ont été absorbés."""
        with self._lock:
            if (proc is not self._proc or self._expected == 0 or self._perms
                    or self._activity_at > result_at):
                return
            self._expected = 0
        self._set_state("idle", proc)

    # ---------------------------------------------------------------- écriture

    def _write(self, line):
        proc = self._proc
        if proc is None or proc.stdin is None:
            return False
        try:
            with self._wlock:
                proc.stdin.write(line.encode("utf-8"))
                proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def _control(self, subtype, **fields):
        rid = self._next_id()
        self._ctrl[rid] = subtype
        return self._write(proto.control(subtype, rid, **fields))

    # ------------------------------------------------------------------- API

    def send(self, text, images=()):
        """Envoie un message (lance ou relance le processus), même pendant un tour. Faux si le
        processus ne peut pas démarrer ou que l'écriture échoue."""
        if (self._relaunch_needed and self._proc is not None and not self._background
                and self.state not in ("busy", "permission")):
            self._relaunch_needed = False
            old = self._proc
            self.stop(grace_s=2)   # relance avec les options refusées en direct (`--resume`)
            with self._lock:       # sans attendre le fil de lecture : le processus est mort
                if self._proc is old:
                    self._proc, self.pid = None, None
        with self._lock:
            working = self.state in ("busy", "permission") and self._proc is not None
            if working:
                # Pendant un tour : écrit tout de suite, la CLI le lit (après le tour ou en cours
                # de route) ; l'état ne bouge pas, le message sera soldé par un result ou le filet.
                self._expected += 1
                ok = self._write(proto.user_message(text, list(images)))
                self.last_activity = self._clock()
                return ok
            if self._proc is None:
                if not self._spawn():
                    return False
                self._control("initialize")
            ok = True
            for cmd in self._pending_cmds:
                self._silent += 1
                self._expected += 1
                ok = self._write(proto.user_message(cmd)) and ok
            self._pending_cmds.clear()
            self._expected += 1
            self._set_state("busy")  # avant l'écriture : le fil de lecture peut conclure aussitôt
            ok = self._write(proto.user_message(text, list(images))) and ok
            self.last_activity = self._clock()
        return ok  # faux : le processus est mort, le fil de lecture signale la sortie

    def interrupt(self):
        with self._lock:
            if self._proc is None or self.state not in ("busy", "permission"):
                return False
            self._requested_stop = True  # la CLI s'arrête (code 1) après le tour interrompu
        return self._control("interrupt")

    def answer(self, request_id, decision, message=""):
        with self._lock:
            req = self._perms.pop(request_id, None)
            if req is None:
                return False
            rest = bool(self._perms)
        if decision == "allow":
            line = proto.allow(request_id, req.input)
        elif decision == "always":
            line = proto.allow_always(request_id, req.input, req.suggestions)
        else:
            line = proto.deny(request_id, message or "Refusé.")
        ok = self._write(line)
        if not rest:
            self._set_state("busy")
        return ok

    def set_options(self, options):
        with self._lock:
            old, self.options = self.options, options
            live = self._proc is not None
        self.effort = options.effort
        if not live:
            return  # tout part avec les options de lancement
        if options.model and options.model != old.model:
            self._control("set_model", model=options.model)
        if options.rights != old.rights:
            self._control("set_permission_mode", mode=options.rights)
        cmds = []
        if old.ultracode and not options.ultracode:
            cmds.append("/effort ultracode off")
        if options.effort and options.effort != old.effort:
            cmds.append(f"/effort {options.effort}")
        if options.ultracode and not old.ultracode:
            cmds.append("/effort ultracode")
        with self._lock:
            self._pending_cmds.extend(cmds)

    def request_context(self):
        return self._control("get_context_usage")

    def suspend_if_idle(self, now, idle_s):
        with self._lock:
            if (self.state != "idle" or self._proc is None or self._perms or self._open_tools
                    or self._background or now - self.last_activity < idle_s):
                return False
            proc = self._proc
            self._requested_stop = True
        self._set_state("suspended")
        threading.Thread(target=self._terminate, args=(proc, 5), daemon=True).start()
        return True

    def stop(self, grace_s=5):
        with self._lock:
            proc = self._proc
            self._requested_stop = True
        if proc is not None:
            self._terminate(proc, grace_s)
        self._set_state("stopped")

    @staticmethod
    def _terminate(proc, grace_s):
        """Ferme stdin, puis SIGTERM, puis SIGKILL, sur NOTRE pid seulement."""
        try:
            proc.stdin.close()
        except (OSError, ValueError):
            pass
        for step in (None, proc.terminate, proc.kill):
            if step:
                try:
                    step()
                except OSError:
                    pass
            try:
                proc.wait(timeout=grace_s)
                return
            except subprocess.TimeoutExpired:
                continue
