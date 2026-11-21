"""Chats du pont : un `ChatSession` (moteur du chat) par conversation ouverte, qui vit dans le pont (il survit aux
déconnexions). Chaque événement est numéroté et gardé (2000 par chat) : un appareil qui revient
demande ce qu'il a manqué depuis son dernier numéro ; tous les appareils attachés reçoivent les
mêmes événements. Identifiants `c<boot>-<n>` : `boot` est tiré au hasard à chaque démarrage du
pont, un identifiant d'avant un redémarrage ne désigne donc jamais un autre chat.

Compactage automatique (réglage `context_alert.auto_compact`) : quand Claude revient au repos, le
pont mesure le contexte ; au-delà du seuil il envoie `/compact` lui-même, même sans appareil
attaché, et l'écrit dans le fil (`events.Notice`).

Relance après une limite (`limit_resume`) : toutes les CHECK_S secondes, le pont fait avancer les
marqueurs de limite et, pour chaque chat bloqué, écrit « relance prévue à HH:MM » dans le fil puis
envoie « continue » quand la limite est levée (web, Android, iPhone et TUI passent tous par ici)."""

import asyncio
import base64
import binascii
import collections
import dataclasses
import itertools
import os
import re
import secrets
import time
import uuid as uuidlib
from pathlib import Path

from .. import chat_engine, chat_options, conversations, chat_protocol as proto, context_alert, limit_events, \
    limit_resume, markdown_render, message_tags, notify, sessions, settings
from ..chat_engine import ChatSession
from . import events, rpc
from .bridge_data import safe_path

BUFFER = 2000
BUSY = ("starting", "busy", "permission")
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")      # nom d'un journal `<id>.jsonl`


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
            "path": transcript_of(chat.cwd, sid), "history_before": _history_before(chat)}


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
    return chat_options.ChatOptions(**{k: v for k, v in raw.items() if k in names})


class ChatHub:
    def __init__(self, bridge, claude=None, environ=None):
        self.bridge = bridge
        self.claude = claude
        self.environ = environ
        self.chats = {}
        self.boot = secrets.token_hex(3)
        self._ids = itertools.count(1)
        self._loop = None
        self._limited = False        # un chat attend la levée d'une limite : le pont reste ouvert
        bridge.busy_checks.append(self.busy)
        bridge.tick_hooks.append(self.limits_pass)
        bridge.close_hooks.append(self._forget)
        bridge.add_handlers({
            "chat.open": self.open, "chat.list": self.list, "chat.attach": self.attach,
            "chat.send": self.send, "chat.answer": self.answer, "chat.questions": self.questions,
            "chat.interrupt": self.interrupt, "chat.options": self.options,
            "chat.close": self.close, "chat.render": self.render, "chat.context": self.context,
            "chat.tags": self.tags, "chat.tag": self.tag,
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
        auto = context_alert.auto_on(cfg)
        if auto and isinstance(ev, chat_engine.ContextUsage):
            ev = dataclasses.replace(ev, auto_compact=True)     # les appareils ne proposent rien
        if isinstance(ev, proto.TurnResult) and ev.is_limit:
            chat.follower.limit_hit()
        chat.seq += 1
        item = {"seq": chat.seq, "ts": time.time(), "event": events.to_json(ev)}
        chat.buf.append(item)
        for conn in list(chat.conns):
            if not conn.closed:
                asyncio.ensure_future(conn.push("chat.event", {"chat_id": chat.chat_id, **item}))
        note = self._auto_compact(chat, ev, cfg, auto)
        if note:
            self._record(chat, events.Notice(*note))

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
        chat = _Chat(f"c{self.boot}-{next(self._ids)}", cwd)
        chat.engine = ChatSession(cwd, session_id=session_id or None,
                                  options=_options(params.get("options")),
                                  on_event=self._on_event(chat), claude=self.claude,
                                  environ=self.environ)
        chat.conns.add(conn)
        self.chats[chat.chat_id] = chat
        return {"chat_id": chat.chat_id, "seq": 0, "cwd": chat.cwd, **_info(chat)}

    async def list(self, _conn, _params):
        chats = [{"chat_id": c.chat_id, "cwd": c.cwd, "state": c.engine.state, "seq": c.seq,
                  **_info(c)} for c in self.chats.values()]

        def titles():
            for c in chats:
                c["title"] = journal_title(c["path"])
        await asyncio.to_thread(titles)
        return {"chats": chats}

    async def attach(self, conn, params):
        chat = self._get(params)
        since = params.get("since") if isinstance(params.get("since"), int) else 0
        chat.conns.add(conn)
        return {"events": [i for i in chat.buf if i["seq"] > since], "seq": chat.seq,
                "state": chat.engine.state, **_info(chat)}

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

    async def interrupt(self, _conn, params):
        await asyncio.to_thread(self._get(params).engine.interrupt)
        return {}

    async def options(self, _conn, params):
        chat = self._get(params)
        await asyncio.to_thread(chat.engine.set_options, _options(params.get("options")))
        return {}

    async def context(self, _conn, params):
        await asyncio.to_thread(self._get(params).engine.request_context)
        return {}

    async def close(self, _conn, params):
        chat = self._get(params)
        del self.chats[chat.chat_id]
        await asyncio.to_thread(chat.engine.stop)
        return {}

    async def close_all(self):
        chats, self.chats = list(self.chats.values()), {}
        for chat in chats:
            await asyncio.to_thread(chat.engine.stop)

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
