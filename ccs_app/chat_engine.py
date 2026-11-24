"""Moteur du chat : pilote un processus `claude -p` en stream-json (sans GTK).

Un processus vit par chat, entre les messages. `on_event(ev)` est appelé depuis un fil
de lecture (ou, pour `StateChanged`, depuis le fil qui change l'état) : l'interface
l'enveloppe dans `GLib.idle_add`. Le moteur n'a pas de file de messages : celle de
l'onglet (`TabState.queue`) attend que l'état redevienne `idle`.
"""

import collections
import dataclasses
import logging
import os
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass

from . import (chat_options, chat_protocol as proto, core, distant, migrate, root_keeper, sessions,
               task_runner, token_use)
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

# Effacement automatique (phase 24) : en fin de sujet, Claude lance `ccs chat clear`, qui
# dépose une demande au nom du jeton de son chat ; au retour au repos, le moteur envoie `/clear`.
CLEAR_COMMAND = "/clear"
CLEAR_TRIGGER = "ccs_auto"
CLEAR_TOKEN_VAR = "CCS_CHAT_TOKEN"
OLD_CLEAR_TOKEN_VAR = "CCS_CHAT_JETON"   # lue encore (chats lancés avant la 1.0.0), à retirer en 2.0
# Chat riche : toujours donné (docs/chat-riche.md). Court : il part à chaque lancement.
RICH_HINT = (
    "Affichage riche : ce chat tourne dans CCS (bureau, web, téléphone). Les images Markdown "
    "(https ou chemin local) s'affichent ; un lien ou un `chemin` vers un son ou une vidéo "
    "(mp3, ogg, wav, m4a, opus, mp4, webm, mov) gagne un lecteur. Un bloc de code de langue "
    "`ccs` contenant un JSON devient un composant : "
    '{"type":"choix","titre":"…","options":["A",{"label":"Voir","message":"texte envoyé"}]} '
    "(boutons : un clic t'envoie le message) ; "
    '{"type":"cartes","items":[{"titre":"…","image":"https://…","prix":"…","description":"…",'
    '"lien":"https://…","actions":[{"label":"…","message":"…"}]}]} '
    "(fiches, une seule : type carte) ; "
    '{"type":"formulaire","titre":"…","champs":[{"nom":"…","label":"…","type":"texte|nombre|liste",'
    '"options":[…]}]} (web seulement). Utilise-les quand ils aident vraiment (choix fermé, '
    "comparaison d'articles), jamais à la place d'une réponse en texte."
)
CLEAR_HINT = (
    "Effacement automatique : ce chat tourne dans CCS. Quand un sujet est vraiment terminé "
    "(travail commité, poussé et publié, mémoire et feuille de route à jour) et que l'utilisateur "
    "n'attend plus de réponse sur ce sujet, lance `ccs chat clear` (outil Bash) dans ton dernier "
    "message, puis termine ta réponse en le disant en une ligne. CCS enverra `/clear` à la fin de "
    "ton tour : la conversation repart à vide (moins de contexte, moins de quota). Ne propose "
    "donc plus à l'utilisateur de taper `/clear` lui-même. Ne le fais pas si une question est en "
    "suspens, si un travail ou un sous-agent tourne encore, ou au milieu d'un sujet."
)


def clear_requests_dir():
    """Dossier des demandes d'effacement (une par jeton de chat)."""
    cache = core.ccs_dir("cache")
    return migrate.renamed(cache / "clear", cache / "effacer")


def request_clear(token):
    """Demande déposée par `ccs chat clear` : un fichier vide au nom du jeton."""
    if not token or not token.isalnum():
        raise ValueError("jeton de chat invalide")
    d = clear_requests_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / token).touch()


def auto_clear_setting():
    """Réglage `chat.auto_clear` (vrai par défaut)."""
    try:
        from . import settings
        value = (settings.load_settings().get("chat") or {}).get("auto_clear", True)
    except Exception:   # réglages illisibles : la valeur par défaut
        return True
    return value if isinstance(value, bool) else True
# Événements d'un tour en cours : reçus alors que le moteur est au repos, ils disent que la CLI
# s'est remise au travail (message envoyé pendant le tour précédent, `/compact` en file).
QUIET_EVENTS = (proto.TurnResult, proto.LocalCommand, proto.ControlReply, proto.Status, proto.Unknown,
                proto.TaskNotice)
WORK_EVENTS = (proto.Thinking, proto.TextDelta, proto.AssistantText, proto.ToolUse, proto.Compacting)


@dataclass(frozen=True)
class StateChanged:
    state: str


@dataclass(frozen=True)
class UserSent:
    """Message de l'utilisateur reçu par le pont : les autres appareils l'affichent ; celui qui
    l'a envoyé le reconnaît à son `nonce` et ne le montre pas deux fois. `uuid` : identifiant du
    message dans le journal (étiquettes)."""
    text: str
    images: int = 0
    nonce: str = ""
    uuid: str = ""


@dataclass(frozen=True)
class TagsChanged:
    """Étiquettes d'un message changées (sur cet appareil ou un autre, chat d'un serveur) :
    `entry` est la nouvelle entrée de `message_tags`, None si elles ont toutes été retirées."""
    session_id: str
    msg_id: str
    entry: dict = None


@dataclass(frozen=True)
class ContextUsage:
    percentage: int
    total: int
    maximum: int
    # Le pont compacte tout seul au-delà du seuil (réglage du serveur) : les appareils ne
    # montrent pas l'alerte de contexte lourd et son bouton « Compacter ».
    auto_compact: bool = False


@dataclass(frozen=True)
class CacheExpired:
    """Le cache de la conversation a expiré (rien depuis sa durée de vie, 5 min ou 1 h) : le
    prochain message relira tout le contexte au prix fort (`token_use.cache_expiry`)."""
    context: int
    ttl_s: int
    rewrite_usd: float | None
    text: str


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
                 environ=None, clock=time.time, auto_clear=None):
        self.cwd = str(cwd)
        self.auto_clear = auto_clear        # None : réglage `chat.auto_clear`, lu au lancement
        self._clear_token = secrets.token_hex(12)
        self._auto_clearing = False         # `/clear` envoyé par le moteur, remise à zéro attendue
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
        self._cache_turn = 0                # numéro du dernier tour terminé (cache expiré)
        self._cache_timer = None
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
        self._background_ids = set()        # appels d'outil des sous-agents de fond pas encore finis
        self._noticed = set()               # avis de fin déjà transmis (tool_id)
        self._compacting = False            # la CLI compacte (`/compact` lu, même envoyé pendant un tour)
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
        if state == "idle":
            self._maybe_auto_clear()

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
        # calcul réparti disponible : Claude sait qu'il peut lancer un travail ailleurs ;
        # effacement automatique : il sait qu'il peut vider la conversation en fin de sujet
        # chat riche : il sait que ses images, médias et blocs ```ccs s'affichent
        hints = [h for h in (distant.hint(), CLEAR_HINT if self._auto_clear_on() else None, RICH_HINT) if h]
        argv += ["--append-system-prompt", "\n\n".join(hints)]
        return argv

    def _auto_clear_on(self):
        if self.auto_clear is None:
            self.auto_clear = auto_clear_setting()
        return self.auto_clear

    def _clear_request(self):
        return clear_requests_dir() / self._clear_token

    def _maybe_auto_clear(self):
        """Au repos : une demande de `ccs chat clear` attend → `/clear`. Pas tant qu'un
        sous-agent de fond tourne (il serait perdu) : la demande attend le repos suivant."""
        path = self._clear_request()
        if not path.exists():
            return
        if not self._auto_clear_on():
            path.unlink(missing_ok=True)
            return
        if self._background:
            return
        path.unlink(missing_ok=True)
        self._auto_clearing = True
        if not self.send_if_idle(CLEAR_COMMAND):
            self._auto_clearing = False

    def _env(self):
        from .terminal import SESSION_VARS
        env = dict(self._environ) if self._environ is not None else task_runner.environment()
        for v in SESSION_VARS:
            env.pop(v, None)
        # `claude -p` (stream-json) n'écrit les instantanés de fichiers, base du retour en
        # arrière, qu'avec cette variable ; sans effet si la version l'ignore.
        env["CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING"] = "1"
        # `sudo -A` marche seul dans les chats : le mot de passe vient du gardien de CCS
        # (demandé aux appareils, gardé une heure en mémoire ; voir `root_keeper`).
        askpass = root_keeper.askpass_path()
        if askpass:
            env["SUDO_ASKPASS"] = askpass
        env.pop(CLEAR_TOKEN_VAR, None)
        env.pop(OLD_CLEAR_TOKEN_VAR, None)
        if self._auto_clear_on():
            env[CLEAR_TOKEN_VAR] = self._clear_token     # pour `ccs chat clear`
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
        self._compacting = False
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

    def background_finished(self, tool_id):
        """L'avis de fin d'un sous-agent de fond est arrivé : plus rien en arrière-plan (la mise
        en veille redevient possible) quand tous ont fini."""
        if tool_id in self._background_ids:
            self._background_ids.discard(tool_id)
            self._background = bool(self._background_ids)

    def _handle_event(self, proc, ev):
        forward = True
        if isinstance(ev, proto.ConversationReset) and self._auto_clearing:
            self._auto_clearing = False
            ev = dataclasses.replace(ev, trigger=CLEAR_TRIGGER)    # les appareils le disent
        # la CLI travaille (nouveau tour, texte, outil…). Pas les événements inconnus : les CLI
        # récentes envoient `command_lifecycle` juste APRÈS le `result`, ce qui empêchait le
        # filet de remettre au repos (« Claude travaille » pour toujours).
        if not isinstance(ev, QUIET_EVENTS):
            self._activity_at = self._clock()
        if isinstance(ev, proto.TaskNotice):
            if ev.tool_id in self._noticed:
                return                          # même avis par le flux et par le message
            self._noticed.add(ev.tool_id)
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
            self._background_ids.add(ev.tool_id)
        if isinstance(ev, proto.TaskNotice):
            self.background_finished(ev.tool_id)
        if isinstance(ev, proto.Compacting):
            self._compacting = ev.active
            forward = False
        if isinstance(ev, WORK_EVENTS) and not getattr(ev, "parent_id", None) \
                and (not isinstance(ev, proto.Compacting) or ev.active):
            self._working_again(proc)
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
        if isinstance(ev, proto.TurnResult) and not getattr(ev, "parent_id", None):
            self._arm_cache_timer(ev.usage)

    # ---------------------------------------------------------------- cache expiré

    def _arm_cache_timer(self, usage):
        """Après un tour : prévient quand le cache aura expiré (`CacheExpired`), si le contexte
        est assez gros pour que ça compte et qu'aucun message n'est parti entre-temps."""
        info = token_use.cache_expiry(usage)
        with self._lock:
            self._cache_turn += 1
            turn = self._cache_turn
            if self._cache_timer is not None:
                self._cache_timer.cancel()
                self._cache_timer = None
            if info is None:
                return
            timer = threading.Timer(info["ttl_s"], self._cache_expired, args=(turn, info))
            timer.daemon = True
            self._cache_timer = timer
        timer.start()

    def _cache_expired(self, turn, info):
        with self._lock:
            if turn != self._cache_turn or self.state not in ("idle", "suspended"):
                return
            self._cache_timer = None
        self._emit(CacheExpired(info["context"], info["ttl_s"], info["rewrite_usd"], info["text"]))

    def _forget_cache_timer(self):
        """Un message part (ou le chat s'arrête) : le cache est relu ou n'a plus d'importance."""
        with self._lock:
            self._cache_turn += 1
            if self._cache_timer is not None:
                self._cache_timer.cancel()
                self._cache_timer = None

    def _working_again(self, proc):
        """La CLI travaille alors qu'on la croyait au repos : un message envoyé pendant un tour a
        été soldé par le filet (le compactage, par exemple, ne donne aucun signe de vie pendant
        plusieurs secondes), et son tour arrive maintenant. On repasse « occupé » et on attend son
        `result` : c'est lui qui remettra l'état au repos (et éteindra l'indicateur)."""
        with self._lock:
            if proc is not self._proc or self.state != "idle":
                return
            self._expected = max(self._expected, 1)
        self._set_state("busy", proc)

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
            if (proc is not self._proc or self._expected == 0 or self._perms or self._compacting
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

    def send(self, text, images=(), uuid=None):
        """Envoie un message (lance ou relance le processus), même pendant un tour. Faux si le
        processus ne peut pas démarrer ou que l'écriture échoue. `uuid` : identifiant de sa ligne
        du journal (voir `proto.user_message`)."""
        self._forget_cache_timer()
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
                ok = self._write(proto.user_message(text, list(images), uuid))
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
            ok = self._write(proto.user_message(text, list(images), uuid)) and ok
            self.last_activity = self._clock()
        return ok  # faux : le processus est mort, le fil de lecture signale la sortie

    def send_if_idle(self, text):
        """Envoi décidé par CCS (compactage automatique), seulement entre deux tours : processus
        en vie, Claude au repos, aucune demande d'autorisation en attente. Sinon faux, et rien
        n'est écrit. Ne lance ni ne relance jamais le processus."""
        with self._lock:
            if self.state != "idle" or self._proc is None or self._perms:
                return False
            self._forget_cache_timer()
            self._expected += 1
            self._set_state("busy")  # avant l'écriture : le fil de lecture peut conclure aussitôt
            ok = self._write(proto.user_message(text))
            self.last_activity = self._clock()
        return ok  # faux : le processus est mort, le fil de lecture signale la sortie

    def interrupt(self):
        with self._lock:
            if self._proc is None or self.state not in ("busy", "permission"):
                return False
            self._requested_stop = True  # la CLI s'arrête (code 1) après le tour interrompu
        return self._control("interrupt")

    def stop_task(self, task_id):
        """Arrête une tâche de fond de la CLI (sous-agent) par son `task_id` (événement système
        `task_started`), sans interrompre le reste du tour. Faux si la CLI ne tourne pas."""
        if not isinstance(task_id, str) or not task_id:
            return False
        return self._control("stop_task", task_id=task_id)

    def answer_questions(self, request_id, answers):
        """Réponses de l'utilisateur aux questions de Claude (outil AskUserQuestion)."""
        with self._lock:
            req = self._perms.pop(request_id, None)
            if req is None:
                return False
            rest = bool(self._perms)
        ok = self._write(proto.answer_questions(request_id, req.input, answers))
        if not rest:
            self._set_state("busy")
        return ok

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
