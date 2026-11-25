"""Chats du pont : un `ChatSession` (moteur du chat) par conversation ouverte, qui vit dans le pont (il survit aux
déconnexions). Chaque événement est numéroté et gardé (2000 par chat) : un appareil qui revient
demande ce qu'il a manqué depuis son dernier numéro ; tous les appareils attachés reçoivent les
mêmes événements. Identifiants `c<boot>-<n>` : `boot` est tiré au hasard à chaque démarrage du
pont ; un chat rouvert après un redémarrage garde le sien, et aucun nouveau chat ne prend un
identifiant déjà pris : un identifiant ne désigne donc jamais un autre chat.

Reprise après un redémarrage (mise à jour, SIGTERM) : les chats ouverts sont écrits dans un fichier
d'état (`state_file`, sous `$XDG_STATE_HOME/ccs`) à chaque ouverture, fermeture, changement d'état
ou de conversation. Au démarrage (`restore`), chacun est recréé avec son identifiant, son dossier,
sa conversation et ses options, suspendu (sans processus : le prochain message relance `claude`
avec `--resume`) ; ceux qui travaillaient reçoivent « continue ». `chat.list`, `chat.attach` et
`chat.open` attendent la fin de la reprise. Un chat fermé exprès sort du fichier.

Compactage automatique (réglage `context_alert.auto_compact`) : quand Claude revient au repos, le
pont mesure le contexte ; au-delà du seuil il envoie `/compact` lui-même, même sans appareil
attaché, et l'écrit dans le fil (`events.Notice`).

Relance après une limite (`limit_resume`) : toutes les CHECK_S secondes, le pont fait avancer les
marqueurs de limite et, pour chaque chat bloqué, écrit « relance prévue à HH:MM » dans le fil puis
envoie « continue » quand la limite est levée (web, Android, iPhone et TUI passent tous par ici).

Mise en veille (réglage `chat.idle_suspend_min`) : au même passage, un chat au repos depuis ce
délai voit son processus `claude` arrêté (état `suspended`) ; le prochain message le relance.

Fermeture : `chat.close {keep_if_shared: true}` (onglet du bureau refermé) ne fait que détacher
l'appareil si un autre appareil suit encore ce chat ; sinon le chat est fermé comme avant. À
l'arrêt du pont (inactivité, relance après une mise à jour, SIGTERM), tous les chats sont fermés,
mais restent dans le fichier d'état pour être rouverts au démarrage suivant.

Sous-agents de fond : la CLI ne passe dans le flux que leur lancement et leur fin. Tant qu'il y en
a un en cours, le pont relit toutes les WATCH_S secondes sa transcription (`subagents.Tails`) et
écrit ses étapes dans le fil (`parent_id` : son appel Task/Agent), comme pour un sous-agent au
premier plan. `chat.attach` rend la liste des sous-agents (`agents`, disque compris : lancés avant
une reprise ou un compactage) et `chat.agent_log` les étapes d'un sous-agent, pour remplir sa vue."""

import asyncio
import base64
import binascii
import collections
import dataclasses
import hashlib
import itertools
import logging
import os
import re
import secrets
import time
import uuid as uuidlib
from pathlib import Path

from .. import core, chat_engine, chat_options, conversations, providers, chat_protocol as proto, context_alert, limit_events, \
    limit_resume, markdown_render, message_tags, notify, sessions, settings, subagents
from ..chat_engine import ChatSession
from . import events, rpc
from .bridge_data import safe_path

BUFFER = 2000
WATCH_S = 3                  # relecture des transcriptions des sous-agents de fond
BUSY = ("starting", "busy", "permission")
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")      # nom d'un journal `<id>.jsonl`
_CHAT_ID = re.compile(r"c([0-9a-f]{1,32})-([0-9]{1,9})")
STATE_VERSION = 1
RESTORE_WAIT_S = 60          # attente maximale de la reprise par list/attach/open
RESTORED_NOTE = "Pont relancé : « continue » envoyé."

log = logging.getLogger(__name__)


class _Chat:
    def __init__(self, chat_id, cwd):
        self.chat_id = chat_id
        self.cwd = cwd
        self.engine = None
        self.buf = collections.deque(maxlen=BUFFER)
        self.seq = 0
        self.opened_at = time.time()
        self.conns = set()
        self.auto = context_alert.AutoCompact()
        self.follower = limit_resume.Follower()     # relance après une limite
        self.agents = subagents.Subagents()         # sous-agents lancés (Jarvis)
        self.tails = subagents.Tails()              # étapes des sous-agents de fond
        self.working = False        # au travail au dernier changement d'état (hors arrêt)
        self.title = None           # titre du journal, pour le fichier d'état
        self.saved_sid = None       # conversation au dernier enregistrement


def transcript_of(cwd, session_id):
    """Chemin du journal `.jsonl` de la conversation s'il existe, sinon None."""
    if not session_id:
        return None
    for folder in dict.fromkeys((cwd, os.path.realpath(cwd))):
        path = sessions.transcript_path(folder, session_id)
        if path.is_file():
            return str(path)
    return None


_titles = {}  # chemin du journal → entrée lue jusqu'ici (lecture de la seule fin nouvelle)


def journal_title(path):
    """Titre d'une conversation ouverte : celui donné par `/rename` ou par CCS, sinon le titre
    automatique de Claude Code ; None s'il n'y en a pas encore."""
    if not path:
        return None
    try:
        entry = _titles[path] = conversations.read_entry(Path(path), _titles.get(path))
    except OSError:
        return None
    return entry["custom_title"] or entry["ai_title"] or None


def _history_before(chat):
    """Heure (epoch) depuis laquelle le tampon a tout gardé : l'ouverture du chat, ou son plus vieil
    événement s'il a débordé. Le client montre le journal d'avant cette heure, sans doublon."""
    if chat.buf and chat.buf[0]["seq"] > 1:
        return chat.buf[0]["ts"]
    return chat.opened_at


def _info(chat):
    """Champs communs de chat.open, chat.attach et chat.list : options du moteur, conversation,
    journal et heure de début du tampon."""
    sid = chat.engine.session_id
    return {"options": dataclasses.asdict(chat.engine.options), "session_id": sid,
            "path": transcript_of(chat.cwd, sid), "history_before": _history_before(chat),
            "pid": chat.engine.pid, "devices": len(chat.conns)}


def _uuid(raw):
    """Identifiant du message envoyé : celui proposé par l'appareil s'il a la forme d'un uuid
    (il le connaît ainsi sans attendre), sinon un nouveau."""
    try:
        return str(uuidlib.UUID(raw)) if isinstance(raw, str) else str(uuidlib.uuid4())
    except ValueError:
        return str(uuidlib.uuid4())


def _options(raw):
    raw = raw if isinstance(raw, dict) else {}
    names = {f.name for f in dataclasses.fields(chat_options.ChatOptions)}
    options = chat_options.ChatOptions(**{k: v for k, v in raw.items() if k in names})
    if options.provider:                 # fournisseur inconnu ou sans clé : refusé avant de lancer
        try:
            problem = providers.key_problem(providers.get(options.provider))
        except ValueError as e:
            problem = str(e)
        if problem:
            raise rpc.RpcError("invalide", problem)
    return options


def provider_list():
    """Fournisseurs à proposer : [{name, label, models: [[id, libellé]], problem}]."""
    out = []
    for name, label, models in providers.choices():
        problem = None
        if not providers.is_claude(name):
            try:
                problem = providers.key_problem(providers.get(name))
            except ValueError as e:
                problem = str(e)
        out.append({"name": name, "label": label, "models": [[m, lab] for lab, m in models],
                    "problem": problem})
    return out


class ChatHub:
    def __init__(self, bridge, claude=None, environ=None):
        self.bridge = bridge
        self.claude = claude
        self.environ = environ
        self.chats = {}
        self.boot = secrets.token_hex(3)
        self._ids = itertools.count(1)
        self._loop = None
        self._ready = asyncio.Event()  # reprise des chats d'avant le redémarrage finie
        self._saved = []             # dernier contenu écrit dans le fichier d'état
        self._closing = False        # close_all : plus rien n'est écrit
        self._limited = False        # un chat attend la levée d'une limite : le pont reste ouvert
        self._watch = None           # tâche qui suit les sous-agents de fond
        bridge.busy_checks.append(self.busy)
        bridge.tick_hooks.append(self.limits_pass)
        bridge.tick_hooks.append(self.suspend_pass)
        bridge.tick_hooks.append(self.persist_pass)
        getattr(bridge, "prepare_hooks", []).append(self.restore)
        getattr(bridge, "stop_hooks", []).append(self.close_all)
        bridge.close_hooks.append(self._forget)
        bridge.add_handlers({
            "chat.open": self.open, "chat.list": self.list, "chat.attach": self.attach,
            "chat.send": self.send, "chat.answer": self.answer, "chat.questions": self.questions,
            "chat.interrupt": self.interrupt, "chat.options": self.options,
            "chat.close": self.close, "chat.render": self.render, "chat.context": self.context,
            "chat.tags": self.tags, "chat.tag": self.tag, "chat.agent_log": self.agent_log,
            "chat.providers": self.providers,
        })

    # ---- état ------------------------------------------------------------------------

    def busy(self):
        return self._limited or any(c.engine is not None and c.engine.state in BUSY
                                    for c in self.chats.values())

    def _forget(self, conn):
        for chat in self.chats.values():
            chat.conns.discard(conn)

    def _get(self, params):
        chat = self.chats.get(params.get("chat_id"))
        if chat is None:
            raise rpc.RpcError("introuvable", "Chat inconnu ou fermé.")
        return chat

    def _record(self, chat, ev, cfg=None):
        """Garde l'événement et l'envoie aux appareils attachés. `cfg` : réglages du contexte lus
        par `_on_event` (retour au repos, mesure du contexte), pour le compactage automatique."""
        if chat.chat_id not in self.chats:
            return
        if isinstance(ev, chat_engine.StateChanged) and ev.state != "stopped":
            # « stopped » (processus tué avec le pont, plantage) ne change pas le drapeau : un
            # chat coupé en plein travail reçoit « continue » à la reprise
            chat.working = ev.state in BUSY
        auto = context_alert.auto_on(cfg)
        if auto and isinstance(ev, chat_engine.ContextUsage):
            ev = dataclasses.replace(ev, auto_compact=True)     # les appareils ne proposent rien
        if isinstance(ev, proto.TurnResult) and ev.is_limit:
            chat.follower.limit_hit()
        chat.agents.feed(ev)
        if isinstance(ev, (proto.ToolUse, proto.ToolResult, proto.Unknown)):
            self._ensure_watch()
        chat.seq += 1
        item = {"seq": chat.seq, "ts": time.time(), "event": events.to_json(ev)}
        chat.buf.append(item)
        for conn in list(chat.conns):
            if not conn.closed:
                asyncio.ensure_future(conn.push("chat.event", {"chat_id": chat.chat_id, **item}))
        note = self._auto_compact(chat, ev, cfg, auto)
        if note:
            self._record(chat, events.Notice(*note))
        sid = getattr(chat.engine, "session_id", None)
        if isinstance(ev, chat_engine.StateChanged) or sid != chat.saved_sid:
            chat.saved_sid = sid
            self._persist()       # état ou conversation changés

    @staticmethod
    def _auto_compact(chat, ev, cfg, auto):
        """Suit le moteur pour le compactage automatique (`context_alert.AutoCompact`) : mesure
        le contexte à chaque retour au repos, envoie `/compact` au-delà du seuil. Renvoie la note
        (texte, genre) à écrire dans le fil, ou None."""
        state, engine = chat.auto, chat.engine
        kind = None
        if isinstance(ev, proto.Compacted):
            state.on_compacted()
        elif isinstance(ev, proto.TurnResult):
            state.on_turn(ev.ok and not ev.interrupted and not ev.is_limit)
        elif isinstance(ev, chat_engine.StateChanged):
            kind = state.on_state(ev.state)
            if auto and ev.state == "idle":
                engine.request_context()        # la réponse (ContextUsage) repasse par ici
        elif isinstance(ev, chat_engine.ContextUsage) and cfg is not None:
            kind = state.measured(cfg, ev.total)
            if kind == "compact":
                ok = engine.send_if_idle(context_alert.COMPACT_COMMAND)
                state.sent(ok)
                kind = kind if ok else None
        return context_alert.auto_note(kind, getattr(ev, "total", 0)) if kind else None

    @staticmethod
    def _context_cfg():
        try:
            return context_alert.config(settings.load_settings())
        except Exception:         # réglages illisibles : pas de compactage automatique
            return None

    def _on_event(self, chat):
        def handler(ev):          # appelé par le fil de lecture du moteur
            cfg = None
            if isinstance(ev, chat_engine.ContextUsage) or (
                    isinstance(ev, chat_engine.StateChanged) and ev.state == "idle"):
                cfg = self._context_cfg()       # lu ici, hors de la boucle du pont
            if self._loop is not None and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._record, chat, ev, cfg)
        return handler

    # ---- méthodes --------------------------------------------------------------------

    async def open(self, conn, params):
        self._loop = asyncio.get_running_loop()
        await self._wait_ready()
        cwd, session_id = params.get("cwd"), params.get("session_id")
        if isinstance(cwd, str) and cwd.startswith("~"):          # « ~/Repo/P » tapé au téléphone
            cwd = os.path.normpath(os.path.expanduser(cwd))
        if not isinstance(cwd, str) or not os.path.isabs(cwd) or not os.path.isdir(cwd):
            raise rpc.RpcError("invalide", "Dossier du projet introuvable.")
        safe_path(cwd)                       # dossier personnel ou dossiers de sites seulement
        if session_id is not None and session_id != "" and not (
                isinstance(session_id, str) and _SESSION_ID.fullmatch(session_id)):
            raise rpc.RpcError("invalide", "Conversation invalide.")
        if session_id:
            for chat in self.chats.values():
                if chat.engine.session_id == session_id:
                    chat.conns.add(conn)
                    return {"chat_id": chat.chat_id, "seq": chat.seq, "cwd": chat.cwd, **_info(chat)}
        raw = dict(params.get("options") or {}) if isinstance(params.get("options"), dict) else {}
        if session_id and not raw.get("provider"):
            # reprise : l'appareil ne connaît pas le fournisseur ; sans lui, claude enverrait le
            # modèle repris du journal (Venice, DeepSeek…) chez Anthropic, qui le refuse
            model = await asyncio.to_thread(providers.last_model, transcript_of(cwd, session_id))
            provider = providers.for_model(model)
            if provider and (not raw.get("model") or providers.for_model(raw["model"]) == provider):
                raw["provider"] = provider
                raw["model"] = raw.get("model") or model
        chat = _Chat(self._new_id(), cwd)
        chat.engine = ChatSession(cwd, session_id=session_id or None,
                                  options=_options(raw),
                                  on_event=self._on_event(chat), claude=self.claude,
                                  environ=self.environ)
        chat.conns.add(conn)
        self.chats[chat.chat_id] = chat
        self._persist()
        return {"chat_id": chat.chat_id, "seq": 0, "cwd": chat.cwd, **_info(chat)}

    async def list(self, _conn, _params):
        await self._wait_ready()
        chats = [{"chat_id": c.chat_id, "cwd": c.cwd, "state": c.engine.state, "seq": c.seq,
                  **_info(c)} for c in self.chats.values()]

        def titles():
            for c in chats:
                c["title"] = journal_title(c["path"])
        await asyncio.to_thread(titles)
        return {"chats": chats}

    async def attach(self, conn, params):
        await self._wait_ready()
        chat = self._get(params)
        since = params.get("since") if isinstance(params.get("since"), int) else 0
        chat.conns.add(conn)
        agents = await asyncio.to_thread(self._agents_of, chat)
        return {"events": [i for i in chat.buf if i["seq"] > since], "seq": chat.seq,
                "state": chat.engine.state, "agents": agents, **_info(chat)}

    async def send(self, _conn, params):
        chat = self._get(params)
        text = params.get("text")
        if not isinstance(text, str):
            raise rpc.RpcError("invalide", "Message manquant.")
        images = []
        for img in params.get("images") or ():
            try:
                images.append((str(img["media_type"]), base64.b64decode(img["data"], validate=True)))
            except (KeyError, TypeError, binascii.Error):
                raise rpc.RpcError("invalide", "Image illisible.") from None
        uid = _uuid(params.get("uuid"))
        chat.follower.typed()
        ok = await asyncio.to_thread(chat.engine.send, text, images, uid)
        if ok:
            shown, nonce = params.get("shown"), params.get("nonce")
            self._record(chat, chat_engine.UserSent(
                shown if isinstance(shown, str) else text, len(images),
                nonce if isinstance(nonce, str) else "", uid))
        return {"ok": bool(ok), "uuid": uid}

    async def answer(self, _conn, params):
        chat = self._get(params)
        rid, decision = params.get("request_id"), params.get("decision")
        if not isinstance(rid, str) or decision not in ("allow", "always", "deny"):
            raise rpc.RpcError("invalide", "Réponse invalide.")
        await asyncio.to_thread(chat.engine.answer, rid, decision, str(params.get("message") or ""))
        self._record(chat, events.PermissionSettled(rid, decision))
        return {}

    async def questions(self, _conn, params):
        chat = self._get(params)
        await asyncio.to_thread(chat.engine.answer_questions, str(params.get("request_id")),
                                params.get("answers") or {})
        self._record(chat, events.PermissionSettled(str(params.get("request_id")), "answered"))
        return {}

    async def providers(self, _conn, _params):
        def work():
            return {"providers": provider_list(),
                    "form": chat_options.new_session_form(settings.load_settings())}
        return await asyncio.to_thread(work)

    async def interrupt(self, _conn, params):
        await asyncio.to_thread(self._get(params).engine.interrupt)
        return {}

    async def options(self, _conn, params):
        chat = self._get(params)
        raw = dict(params.get("options") or {}) if isinstance(params.get("options"), dict) else {}
        raw["provider"] = chat.engine.options.provider   # fixé à l'ouverture : claude n'en change pas en route
        await asyncio.to_thread(chat.engine.set_options, _options(raw))
        return {}

    async def context(self, _conn, params):
        await asyncio.to_thread(self._get(params).engine.request_context)
        return {}

    async def close(self, conn, params):
        chat = self._get(params)
        if params.get("keep_if_shared") is True:
            others = [c for c in chat.conns if c is not conn and not getattr(c, "closed", False)]
            if others:            # suivi ailleurs (web, téléphone) : on détache seulement cet appareil
                chat.conns.discard(conn)
                return {"closed": False, "devices": len(others)}
        del self.chats[chat.chat_id]
        self._persist()               # fermé exprès : ne sera pas rouvert
        await asyncio.to_thread(chat.engine.stop)
        return {"closed": True}

    async def close_all(self):
        """Arrêt du pont : enregistre les chats (avec ceux qui travaillent) puis les arrête ; le
        fichier d'état reste, pour les rouvrir au démarrage suivant."""
        if not self._closing:
            await asyncio.to_thread(self._refresh_titles)
            self._persist()
            self._closing = True
        if self._watch is not None:
            self._watch.cancel()
        chats, self.chats = list(self.chats.values()), {}
        for chat in chats:
            await asyncio.to_thread(chat.engine.stop)

    # ---- reprise après un redémarrage -------------------------------------------------------

    def state_file(self):
        """Fichier des chats ouverts : un par pont (local ou serveur, et socket écouté)."""
        mode = "local" if getattr(self.bridge, "local", False) else "serveur"
        sock = getattr(self.bridge, "socket_path", None)
        tag = hashlib.sha256(str(sock).encode()).hexdigest()[:12] if sock else "defaut"
        return core.ccs_dir("state") / f"chats-{mode}-{tag}.json"

    def _new_id(self):
        while True:
            chat_id = f"c{self.boot}-{next(self._ids)}"
            if chat_id not in self.chats:
                return chat_id

    async def _wait_ready(self):
        """Pendant le démarrage du pont, attend la reprise des chats (identifiants connus)."""
        if getattr(self.bridge, "preparing", False) and not self._ready.is_set():
            try:
                await asyncio.wait_for(self._ready.wait(), RESTORE_WAIT_S)
            except asyncio.TimeoutError:
                log.warning("reprise des chats trop longue : on répond sans attendre")

    def _snapshot(self):
        out = []
        for chat in self.chats.values():
            try:
                engine = chat.engine
                out.append({"chat_id": chat.chat_id, "cwd": chat.cwd,
                            "session_id": engine.session_id,
                            "options": dataclasses.asdict(engine.options),
                            "busy": bool(chat.working or engine.state in BUSY),
                            "title": chat.title})
            except Exception:       # moteur incomplet (tests) : ce chat n'est pas gardé
                continue
        return out

    def _persist(self):
        """Écrit les chats ouverts s'ils ont changé (fichier supprimé quand il n'y en a plus)."""
        if self._closing:
            return
        snap = self._snapshot()
        if snap == self._saved:
            return
        try:
            path = self.state_file()
            if snap:
                core.atomic_write_json(path, {"version": STATE_VERSION, "chats": snap})
            else:
                path.unlink(missing_ok=True)
            self._saved = snap
        except (OSError, TypeError, ValueError):
            log.warning("chats ouverts impossibles à enregistrer", exc_info=True)

    def _refresh_titles(self):
        for chat in list(self.chats.values()):
            try:
                title = journal_title(transcript_of(chat.cwd, chat.engine.session_id))
            except Exception:
                continue
            if title:
                chat.title = title

    async def persist_pass(self, now=None):
        """Un passage (chaque minute) : titres relus, fichier d'état réécrit s'il a changé."""
        if self.chats:
            await asyncio.to_thread(self._refresh_titles)
        self._persist()

    @staticmethod
    def _entry(raw):
        """Entrée valide du fichier d'état → (chat_id, cwd, session_id, options, busy, title),
        ou None (entrée abîmée, dossier disparu, fournisseur refusé)."""
        if not isinstance(raw, dict):
            return None
        chat_id, cwd, sid = raw.get("chat_id"), raw.get("cwd"), raw.get("session_id")
        if not isinstance(chat_id, str) or not _CHAT_ID.fullmatch(chat_id):
            return None
        if not isinstance(cwd, str) or not os.path.isabs(cwd) or not os.path.isdir(cwd):
            return None
        try:
            safe_path(cwd)
        except Exception:
            return None
        if sid is not None and not (isinstance(sid, str) and _SESSION_ID.fullmatch(sid)):
            return None
        try:
            options = _options(raw.get("options"))
        except Exception:
            return None
        title = raw.get("title") if isinstance(raw.get("title"), str) else None
        return chat_id, cwd, sid or None, options, raw.get("busy") is True, title

    async def restore(self):
        """Démarrage du pont : rouvre les chats du fichier d'état, suspendus ; ceux qui
        travaillaient reçoivent « continue »."""
        self._loop = asyncio.get_running_loop()
        try:
            await self._restore()
        finally:
            self._ready.set()

    async def _restore(self):
        data = await asyncio.to_thread(core.load_json, self.state_file())
        items = data.get("chats") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return
        resume = []
        for raw in items:
            entry = self._entry(raw)
            if entry is None or entry[0] in self.chats:
                if entry is None:
                    log.warning("chat d'avant le redémarrage ignoré : %r", raw)
                continue
            chat_id, cwd, sid, options, busy, title = entry
            boot, n = _CHAT_ID.fullmatch(chat_id).groups()
            if boot == self.boot:         # même tirage (rare) : les nouveaux numéros passent après
                self._ids = itertools.count(max(int(n) + 1, next(self._ids)))
            chat = _Chat(chat_id, cwd)
            chat.title, chat.saved_sid = title, sid
            chat.engine = ChatSession(cwd, session_id=sid, options=options,
                                      on_event=self._on_event(chat), claude=self.claude,
                                      environ=self.environ)
            chat.engine.state = "suspended"       # pas de processus : le prochain message le lance
            self.chats[chat_id] = chat
            if busy and sid:
                resume.append(chat)
        log.info("%d chat(s) rouvert(s) après le redémarrage", len(self.chats))
        for chat in resume:
            uid = await asyncio.to_thread(self._send_continue, chat.engine)
            if uid is None:
                self._record(chat, events.Notice(
                    "Pont relancé, mais la relance a échoué : tape « continue ».", "warning"))
                continue
            self._record(chat, chat_engine.UserSent(limit_resume.TEXT, 0, "", uid))
            self._record(chat, events.Notice(RESTORED_NOTE, "info"))
        self._saved = None            # réécrit tel quel (entrées ignorées retirées)
        self._persist()

    # ---- sous-agents -----------------------------------------------------------------------

    @staticmethod
    def _agents_of(chat):
        """Sous-agents du chat (suivis en direct, complétés par le disque). Ceux que le pont n'a pas
        vus lancer, d'avant l'ouverture du chat, sont morts avec l'ancien processus `claude`."""
        live = chat.agents.items()
        known = {i["tool_id"] for i in live}
        disk = subagents.from_transcript(transcript_of(chat.cwd, chat.engine.session_id))
        out = []
        for item in subagents.merge(live, disk):
            if item["tool_id"] not in known and item["state"] == "running" \
                    and (item["started"] or 0) < chat.opened_at:
                item["state"] = "stopped"
            out.append({k: item[k] for k in ("tool_id", "description", "type", "background",
                                             "state", "started", "summary")})
        return out

    async def agent_log(self, _conn, params):
        """Étapes d'un sous-agent lues dans sa transcription : sa vue reconstruite après un
        rechargement, une reprise ou un compactage."""
        chat = self._get(params)
        tool_id = params.get("tool_id")
        if not isinstance(tool_id, str) or not tool_id:
            raise rpc.RpcError("invalide", "Sous-agent manquant.")

        def work():
            path = transcript_of(chat.cwd, chat.engine.session_id)
            items = subagents.merge(chat.agents.items(), subagents.from_transcript(path))
            item = next((i for i in items if i["tool_id"] == tool_id), None)
            return [events.to_json(ev) for ev in subagents.read_log(path, item)] if item else []
        return {"events": await asyncio.to_thread(work)}

    def _ensure_watch(self):
        """Lance le suivi des transcriptions s'il y a un sous-agent de fond à suivre."""
        if self._watch is not None and not self._watch.done():
            return
        if any(c.tails.wants(c.agents.items()) for c in self.chats.values()):
            self._watch = asyncio.ensure_future(self._watch_agents())

    async def _watch_agents(self):
        """Toutes les WATCH_S secondes, les étapes nouvelles des sous-agents de fond ; s'arrête
        quand il n'y a plus rien à suivre (relancé au prochain lancement)."""
        def poll(chat, items):
            return chat.tails.poll(transcript_of(chat.cwd, chat.engine.session_id), items)
        while True:
            await asyncio.sleep(WATCH_S)
            followed = False
            for chat in list(self.chats.values()):
                items = chat.agents.items()
                if not chat.tails.wants(items):
                    continue
                followed = True
                try:
                    evs = await asyncio.to_thread(poll, chat, items)
                except Exception:          # transcription illisible : nouvel essai au passage suivant
                    evs = []
                for ev in evs:
                    self._record(chat, ev)
            if not followed:
                return

    # ---- mise en veille --------------------------------------------------------------------

    async def suspend_pass(self, now=None):
        """Un passage (chaque minute) : les chats au repos depuis `chat.idle_suspend_min` minutes
        arrêtent leur processus `claude` (le moteur dit lui-même s'il peut : rien en attente)."""
        if not self.chats:
            return
        try:
            minutes = int((await asyncio.to_thread(self._settings)).get("chat", {}).get("idle_suspend_min", 0))
        except (TypeError, ValueError, AttributeError):
            minutes = 0
        if minutes <= 0:
            return
        now = time.time() if now is None else now
        for chat in list(self.chats.values()):
            await asyncio.to_thread(chat.engine.suspend_if_idle, now, minutes * 60)

    # ---- relance après une limite -------------------------------------------------------

    @staticmethod
    def _send_continue(engine):
        """« continue » si Claude attend un message : au repos (processus en vie) ou suspendu
        (relancé par l'envoi)."""
        uid = str(uuidlib.uuid4())
        if engine.state == "idle":
            return uid if engine.send_if_idle(limit_resume.TEXT) else None
        if engine.state == "suspended":
            return uid if engine.send(limit_resume.TEXT, (), uid) else None
        return None

    async def limits_pass(self, now=None):
        """Un passage (chaque minute) : avance les marqueurs, puis notes et relances de chaque chat."""
        if not self.chats:
            self._limited = False
            return
        cfg = limit_resume.config(await asyncio.to_thread(self._settings))
        await asyncio.to_thread(limit_resume.advance, None, notifier=notify.send)
        marks = await asyncio.to_thread(limit_events.load_all)
        self._limited = any(c.engine.session_id in marks for c in self.chats.values())
        for chat in list(self.chats.values()):
            engine = chat.engine
            sid = engine.session_id
            ev = marks.get(sid) if sid else None
            can = engine.state in ("idle", "suspended")
            actions = await asyncio.to_thread(chat.follower.step, ev, time.time() if now is None else now,
                                              can, cfg["enabled"], sid, chat.cwd)
            for act in actions:
                if act[0] == "send":
                    uid = await asyncio.to_thread(self._send_continue, engine)
                    if uid is None:
                        self._record(chat, events.Notice(
                            "Limite levée, mais la relance a échoué : tape « continue ».", "warning"))
                        break
                    self._record(chat, chat_engine.UserSent(limit_resume.TEXT, 0, "", uid))
                else:
                    self._record(chat, events.Notice(act[1], act[2]))

    @staticmethod
    def _settings():
        try:
            return settings.load_settings()
        except Exception:
            return {}

    # ---- étiquettes ----------------------------------------------------------------------

    async def tags(self, _conn, params):
        """Messages étiquetés d'une conversation, et les étiquettes déjà utilisées ailleurs."""
        sid = params.get("session_id")
        if not message_tags.valid_session(sid):
            raise rpc.RpcError("invalide", "Conversation inconnue.")
        msgs, known = await asyncio.to_thread(
            lambda: (message_tags.load(sid), message_tags.known_tags()))
        return {"messages": msgs, "known": known}

    async def tag(self, _conn, params):
        """Pose (ou retire, liste vide) les étiquettes d'un message ; les appareils connectés
        reçoivent `chat.tags` et mettent leur fil à jour."""
        sid, msg_id, tags = params.get("session_id"), params.get("msg_id"), params.get("tags")
        if not message_tags.valid_session(sid) or not message_tags.valid_message(msg_id) \
                or not isinstance(tags, list):
            raise rpc.RpcError("invalide", "Étiquettes invalides.")
        text, role = params.get("text"), params.get("role")
        entry = await asyncio.to_thread(
            message_tags.set_tags, sid, msg_id, tags, text if isinstance(text, str) else "",
            role if isinstance(role, str) else "")
        await self.bridge.broadcast("chat.tags", {"session_id": sid, "msg_id": msg_id, "entry": entry})
        return {"entry": entry}

    async def render(self, _conn, params):
        text = params.get("markdown")
        if not isinstance(text, str):
            raise rpc.RpcError("invalide", "Texte manquant.")
        return {"html": markdown_render.to_html(text)}
